from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.detect import iter_project_files
from quality_gates.js_resolve import resolve_js_module

IMPORT_RE = re.compile(
    r"""(?:from\s+['"]([^'"]+)['"]|import\(\s*['"]([^'"]+)['"]\s*\)|require\(\s*['"]([^'"]+)['"]\s*\))"""
)
GOTO_RE = re.compile(
    r"""(?:page\.goto|cy\.visit|page\.request\.(?:get|post)|router\.push)\(\s*['"`]([^'"`]+)"""
)
UI_IMPORT_MARKERS = (
    "@playwright/test",
    "playwright",
    "cypress",
    "@playwright/experimental-ct-react",
    "@playwright/experimental-ct-vue",
    "@playwright/experimental-ct-svelte",
)
SPEC_SUFFIXES = (
    ".spec.ts",
    ".spec.tsx",
    ".spec.js",
    ".spec.jsx",
    ".spec.mjs",
    ".test.ts",
    ".test.tsx",
    ".test.js",
    ".cy.ts",
    ".cy.js",
    ".cy.tsx",
)
UI_DIR_PARTS = {
    "e2e",
    "playwright",
    "cypress",
    "e2e-tests",
    "ui-tests",
    "pw",
}
SHARED_NAME_HINTS = (
    "playwright.config",
    "cypress.config",
    "global-setup",
    "global-teardown",
    "playwright/.auth",
)
SHARED_APP_SHELL = {
    "app/layout.tsx",
    "app/layout.ts",
    "app/layout.jsx",
    "app/layout.js",
    "src/app/layout.tsx",
    "src/app/layout.ts",
    "src/app/layout.jsx",
    "src/app/layout.js",
    "pages/_app.tsx",
    "pages/_app.ts",
    "pages/_app.jsx",
    "pages/_app.js",
    "pages/_document.tsx",
    "pages/_document.js",
    "src/pages/_app.tsx",
    "src/pages/_app.jsx",
    "src/pages/_document.tsx",
    "src/routes/+layout.svelte",
    "src/routes/+layout.ts",
}
PAGE_EXTS = (".tsx", ".ts", ".jsx", ".js", ".vue", ".svelte")
APP_PAGE_STEMS = (
    "page",
    "layout",
    "loading",
    "error",
    "template",
    "route",
    "default",
)
SOURCE_SUFFIXES = {
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".vue",
    ".svelte",
    ".css",
    ".scss",
}


@dataclass
class UiProject:
    framework: str
    config_file: Path
    root: Path


@dataclass
class Selection:
    specs: list[Path]
    reasons: dict[str, list[str]] = field(default_factory=dict)
    run_all: bool = False
    run_all_reason: str = ""
    notes: list[str] = field(default_factory=list)


def detect_ui_project(root: Path, preferred: str = "auto") -> UiProject | None:
    project: UiProject | None = None
    for name, framework in (
        ("playwright.config.ts", "playwright"),
        ("playwright.config.js", "playwright"),
        ("playwright.config.mts", "playwright"),
        ("playwright.config.mjs", "playwright"),
        ("cypress.config.ts", "cypress"),
        ("cypress.config.js", "cypress"),
        ("cypress.config.mjs", "cypress"),
        ("cypress.json", "cypress"),
    ):
        if preferred not in {"auto", framework}:
            continue
        direct = root / name
        if direct.is_file():
            project = UiProject(framework, direct, root)
            break
        matches = list(root.glob(f"**/{name}"))
        matches = [
            path
            for path in matches
            if "node_modules" not in path.parts and ".quality-gates" not in path.parts
        ]
        if matches:
            config = sorted(matches, key=lambda p: len(p.parts))[0]
            project = UiProject(framework, config, config.parent)
            break
    if project is None:
        package = root / "package.json"
        if package.is_file():
            try:
                data = json.loads(package.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            if preferred in {"auto", "playwright"} and (
                "@playwright/test" in deps or "playwright" in deps
            ):
                project = UiProject("playwright", package, root)
            elif preferred in {"auto", "cypress"} and "cypress" in deps:
                project = UiProject("cypress", package, root)
    if project and preferred not in {"auto", project.framework}:
        return None
    return project


def discover_specs(root: Path, config: QualityConfig, project: UiProject) -> list[Path]:
    specs: list[Path] = []
    search_root = project.root if project.root.is_dir() else root
    restrict = [_norm(item).rstrip("/") for item in config.ui_spec_dirs]
    for path in iter_project_files(search_root, config):
        if not _looks_like_spec(path):
            continue
        if restrict:
            rel = _rel(search_root, path)
            if not any(rel == item or rel.startswith(item + "/") for item in restrict):
                continue
        if _is_ui_spec(path, project):
            specs.append(path)
    return sorted(specs)


def select_specs(
    root: Path,
    config: QualityConfig,
    project: UiProject,
    changed: list[str] | None,
    *,
    force_all: bool = False,
) -> Selection:
    specs = discover_specs(root, config, project)
    if not specs:
        looked = ", ".join(_spec_dir_hints(config)[:6])
        return Selection(
            specs=[],
            notes=[f"no Playwright/Cypress spec files found (looked under {looked})"],
        )
    if force_all or config.ui_select == "all":
        return Selection(
            specs=specs,
            run_all=True,
            run_all_reason="forced all" if force_all else "ui.select=all",
            notes=[f"{len(specs)} spec(s)"],
        )

    changed_set = {_norm(name) for name in (changed or [])}
    if not changed_set:
        return Selection(
            specs=[],
            notes=["no changed files vs base — skipping UI tests"],
        )

    if _shared_config_changed(root, project, changed_set):
        return Selection(
            specs=specs,
            run_all=True,
            run_all_reason="shared Playwright/Cypress config or global setup changed",
            notes=[f"running all {len(specs)} spec(s)"],
        )

    coverage = _load_coverage(root, config)
    reasons: dict[str, list[str]] = {str(spec): [] for spec in specs}
    selected: set[Path] = set()

    for spec in specs:
        labels = _why_selected(spec, root, config, changed_set, coverage)
        if not labels:
            continue
        selected.add(spec)
        reasons[str(spec)].extend(labels)

    chosen = sorted(selected)
    if not chosen:
        return Selection(
            specs=[],
            reasons=reasons,
            notes=[
                f"no spec touches the {len(changed_set)} changed file(s) — skipping UI tests"
            ],
        )
    notes = [
        f"{len(chosen)} of {len(specs)} spec(s) whose touches overlap "
        f"{len(changed_set)} changed file(s)"
    ]
    if coverage:
        notes.append(f"coverage map: {len(coverage)} test(s)")
    return Selection(specs=chosen, reasons=reasons, notes=notes)


def spec_touches(
    spec: Path,
    root: Path,
    config: QualityConfig,
    coverage: dict[str, list[str]] | None = None,
) -> set[str]:
    """Files this spec actually uses: itself, imports, visited routes, coverage."""
    files = {_rel(root, spec)}
    files.update(_imported_files(spec, root, config))
    for route in _routes_in(spec):
        for page in _route_files(route, root):
            files.add(_rel(root, page))
            files.update(_imported_files(page, root, config))
    if coverage:
        rel = _rel(root, spec)
        name = _norm(spec.name)
        for test, mapped in coverage.items():
            key = _norm(test)
            if key in {rel, name} or key.endswith("/" + name):
                files.update(_norm(item) for item in mapped)
    return files


def _why_selected(
    spec: Path,
    root: Path,
    config: QualityConfig,
    changed: set[str],
    coverage: dict[str, list[str]],
) -> list[str]:
    rel = _rel(root, spec)
    imported = set(_imported_files(spec, root, config))
    pages: set[str] = set()
    page_imports: set[str] = set()
    for route in _routes_in(spec):
        for page in _route_files(route, root):
            page_rel = _rel(root, page)
            pages.add(page_rel)
            page_imports.update(_imported_files(page, root, config))
    covered: set[str] = set()
    if coverage:
        name = _norm(spec.name)
        for test, mapped in coverage.items():
            key = _norm(test)
            if key in {rel, name} or key.endswith("/" + name):
                covered.update(_norm(item) for item in mapped)

    touch = {rel} | imported | pages | page_imports | covered
    hits = sorted(path for path in touch if path in changed)
    if not hits:
        return []

    labels: list[str] = []
    if rel in changed:
        labels.append("spec file changed")
    import_hits = [path for path in hits if path in imported]
    if import_hits:
        labels.append("imports " + ", ".join(import_hits[:5]))
    page_hits = [path for path in hits if path in pages or path in page_imports]
    if page_hits:
        labels.append("visited page uses " + ", ".join(page_hits[:5]))
    cover_hits = [path for path in hits if path in covered]
    if cover_hits:
        labels.append("coverage map " + ", ".join(cover_hits[:5]))
    if not labels:
        labels.append("touches " + ", ".join(hits[:5]))
    return labels


def _looks_like_spec(path: Path) -> bool:
    name = path.name.lower()
    return any(name.endswith(suffix) for suffix in SPEC_SUFFIXES)


def spec_kind(path: Path) -> str:
    name = path.name.lower()
    if ".cy." in name or "cypress" in {p.lower() for p in path.parts}:
        return "cypress"
    return "playwright"


def _is_ui_spec(path: Path, project: UiProject) -> bool:
    parts = {part.lower() for part in path.parts}
    posix = path.as_posix().lower().split("/")
    if parts & UI_DIR_PARTS or "e2e" in posix:
        return project.framework in {"playwright", "cypress"}
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")[:80_000]
    except OSError:
        return False
    return any(marker in text for marker in UI_IMPORT_MARKERS)


def _shared_config_changed(root: Path, project: UiProject, changed: set[str]) -> bool:
    config_rel = _rel(root, project.config_file)
    if config_rel in changed:
        return True
    for name in changed:
        lower = name.lower()
        if any(hint in lower for hint in SHARED_NAME_HINTS):
            return True
        if _norm(name) in SHARED_APP_SHELL:
            return True
        if lower.endswith("cypress/support/e2e.ts") or lower.endswith(
            "cypress/support/e2e.js"
        ):
            return True
        if "/support/commands." in lower:
            return True
    return False


def _imported_files(spec: Path, root: Path, config: QualityConfig) -> list[str]:
    aliases = config.ui_path_aliases
    seen: set[Path] = set()
    stack = [spec]
    files: list[str] = []
    depth = 0
    while stack and depth < 400:
        current = stack.pop()
        depth += 1
        if current in seen or not current.is_file():
            continue
        seen.add(current)
        try:
            text = current.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if len(text) > 400_000:
            continue
        for match in IMPORT_RE.finditer(text):
            spec_path = next((group for group in match.groups() if group), "")
            resolved = _resolve_import(current, spec_path, root, aliases)
            if resolved is None or resolved in seen:
                continue
            if "node_modules" in resolved.parts:
                continue
            files.append(_rel(root, resolved))
            if resolved.suffix.lower() in SOURCE_SUFFIXES | {".ts", ".js"}:
                stack.append(resolved)
    return files


def _resolve_import(
    current: Path, spec: str, root: Path, aliases: dict[str, str]
) -> Path | None:
    return resolve_js_module(current, spec, root, aliases)


def _route_segments(route: str) -> list[str]:
    trimmed = route.strip("/")
    if not trimmed:
        return []
    parts: list[str] = []
    for part in trimmed.split("/"):
        if (
            not part
            or part.startswith(":")
            or part.startswith("*")
            or part.startswith("[")
            or part.isdigit()
        ):
            break
        parts.append(part)
    return parts


def _route_files(route: str, root: Path) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    segments = _route_segments(route)
    prefixes: list[list[str]] = []
    if not segments:
        prefixes.append([])
    else:
        prefixes.extend(segments[:index] for index in range(len(segments), 0, -1))

    for prefix in prefixes:
        for base in ("app", "src/app"):
            folder = root.joinpath(*Path(base).parts, *prefix)
            for stem in APP_PAGE_STEMS:
                for ext in PAGE_EXTS:
                    candidate = folder / f"{stem}{ext}"
                    if candidate.is_file() and candidate not in seen:
                        seen.add(candidate)
                        found.append(candidate)
        for base in ("pages", "src/pages"):
            file_base = root.joinpath(*Path(base).parts, *prefix)
            for ext in PAGE_EXTS:
                candidate = Path(str(file_base) + ext)
                if candidate.is_file() and candidate not in seen:
                    seen.add(candidate)
                    found.append(candidate)
                index = file_base / f"index{ext}"
                if index.is_file() and index not in seen:
                    seen.add(index)
                    found.append(index)
        svelte = root.joinpath("src", "routes", *prefix)
        for stem in ("+page", "+layout"):
            for ext in (".svelte", ".ts", ".js"):
                candidate = svelte / f"{stem}{ext}"
                if candidate.is_file() and candidate not in seen:
                    seen.add(candidate)
                    found.append(candidate)
    return found


def _routes_in(spec: Path) -> list[str]:
    try:
        text = spec.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    routes = []
    for match in GOTO_RE.finditer(text):
        raw = match.group(1)
        if raw.startswith("http"):
            from urllib.parse import urlparse

            path = urlparse(raw).path or "/"
        else:
            path = raw.split("?")[0].split("#")[0]
        if path.startswith("/"):
            routes.append(path)
    return routes


def _load_coverage(root: Path, config: QualityConfig) -> dict[str, list[str]]:
    path = root / config.ui_coverage_map
    if not path.is_file():
        fallback = root / ".quality-reports" / "ui-coverage.json"
        path = fallback if fallback.is_file() else path
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    result: dict[str, list[str]] = {}
    for key, value in data.items():
        if isinstance(value, list):
            result[_norm(str(key))] = [_norm(str(item)) for item in value]
    return result


def _spec_dir_hints(config: QualityConfig) -> list[str]:
    hints = list(config.ui_spec_dirs)
    if config.ui_framework in {"auto", "playwright"}:
        hints.extend(["e2e", "tests/e2e", "playwright", "tests/playwright"])
    if config.ui_framework in {"auto", "cypress"}:
        hints.extend(["cypress/e2e", "cypress/integration"])
    seen: set[str] = set()
    unique: list[str] = []
    for hint in hints:
        key = hint.replace("\\", "/")
        if key not in seen:
            seen.add(key)
            unique.append(hint)
    return unique


def _rel(root: Path, path: Path) -> str:
    try:
        return _norm(path.resolve().relative_to(root.resolve()).as_posix())
    except ValueError:
        return _norm(path.as_posix())


def _norm(value: str) -> str:
    return value.replace("\\", "/").lstrip("./")
