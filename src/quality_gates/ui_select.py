from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.detect import iter_project_files

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
        rel = _rel(root, spec)
        if rel in changed_set or _norm(spec.name) in {
            Path(c).name for c in changed_set
        }:
            selected.add(spec)
            reasons[str(spec)].append("spec file changed")

    for spec in specs:
        imported = _imported_files(spec, root, config)
        hits = [path for path in imported if _norm(path) in changed_set]
        if hits:
            selected.add(spec)
            reasons[str(spec)].append("imports " + ", ".join(hits[:5]))

    for spec in specs:
        for source in changed_set:
            if _name_related(spec, source):
                selected.add(spec)
                reasons[str(spec)].append(f"name/path related to {source}")
                break

    for spec in specs:
        routes = _routes_in(spec)
        for source in changed_set:
            for route in routes:
                if _route_covers(route, source):
                    selected.add(spec)
                    reasons[str(spec)].append(f"goto/visit {route} covers {source}")

    if coverage:
        inverted_hits = _coverage_hits(coverage, changed_set)
        for spec in specs:
            rel = _rel(root, spec)
            if rel in inverted_hits:
                selected.add(spec)
                reasons[str(spec)].append("prior coverage map")

    chosen = sorted(selected)
    notes = [
        f"{len(chosen)} of {len(specs)} spec(s) selected from {len(changed_set)} changed file(s)"
    ]
    if coverage:
        notes.append(f"coverage map: {len(coverage)} test(s)")
    return Selection(specs=chosen, reasons=reasons, notes=notes)


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
    if not spec or spec.startswith("node:"):
        return None
    for prefix, target in aliases.items():
        if spec.startswith(prefix):
            spec = str(Path(target) / spec[len(prefix) :])
            break
    if spec.startswith("."):
        base = current.parent / spec
    elif "/" in spec and not spec.startswith("@"):
        base = root / spec
    else:
        return None
    candidates = [
        base,
        Path(str(base) + ".ts"),
        Path(str(base) + ".tsx"),
        Path(str(base) + ".js"),
        Path(str(base) + ".jsx"),
        Path(str(base) + ".mjs"),
        base / "index.ts",
        base / "index.tsx",
        base / "index.js",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def _name_related(spec: Path, changed: str) -> bool:
    spec_stem = _spec_stem(spec)
    if len(spec_stem) < 4:
        return False
    changed_path = Path(changed)
    if changed_path.suffix.lower() not in SOURCE_SUFFIXES:
        return False
    parts = [changed_path.stem.lower()] + [part.lower() for part in changed_path.parts]
    if spec_stem in parts:
        return True
    collapsed = spec_stem.replace("-", "").replace("_", "")
    file_stem = changed_path.stem.lower().replace("-", "").replace("_", "")
    return len(collapsed) >= 4 and collapsed == file_stem


def _spec_stem(spec: Path) -> str:
    name = spec.name.lower()
    for suffix in SPEC_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name.replace(".spec", "").replace(".test", "").replace(".cy", "")


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
            path = raw.split("?")[0]
        if path.startswith("/"):
            routes.append(path)
    return routes


def _route_covers(route: str, changed: str) -> bool:
    trimmed = route.strip("/")
    if not trimmed:
        return False
    first = trimmed.split("/")[0].lower()
    if len(first) < 3:
        return False
    posix = changed.replace("\\", "/").lower()
    needles = (
        f"/{first}/",
        f"/{first}.",
        f"app/{first}/",
        f"pages/{first}/",
        f"src/pages/{first}",
        f"src/app/{first}/",
        f"src/routes/{first}",
        f"app/{first}/page.",
        f"pages/{first}.",
    )
    return any(
        needle in f"/{posix}" or posix.startswith(needle.lstrip("/"))
        for needle in needles
    )


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


def _coverage_hits(coverage: dict[str, list[str]], changed: set[str]) -> set[str]:
    hits: set[str] = set()
    changed_norm = changed
    for test, files in coverage.items():
        if any(_norm(item) in changed_norm for item in files):
            hits.add(_norm(test))
            hits.add(_norm(Path(test).name))
    return hits


def _rel(root: Path, path: Path) -> str:
    try:
        return _norm(path.resolve().relative_to(root.resolve()).as_posix())
    except ValueError:
        return _norm(path.as_posix())


def _norm(value: str) -> str:
    return value.replace("\\", "/").lstrip("./")
