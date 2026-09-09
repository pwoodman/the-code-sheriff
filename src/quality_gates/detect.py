from __future__ import annotations

import os
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.registry import (
    LANGUAGE_PROFILES,
    PROFILES,
    gate_language,
    profiles_for_path,
    profiles_for_shebang,
)

# Project config that quality should still read. Unknown dot-directories are
# editor/indexer caches (`.zvec-grep`, `.cursor`, `.idea`) and are not source.
KEEP_HIDDEN_DIRS = frozenset(
    {".github", ".quality", ".husky", ".circleci", ".devcontainer"}
)
ALWAYS_SKIP_DIRS = frozenset(
    {
        "node_modules",
        "dist",
        "build",
        "target",
        "vendor",
        "__pycache__",
        "venv",
        ".venv",
        ".git",
        ".quality-gates",
        ".quality-reports",
        ".ruff_cache",
        ".pytest_cache",
        ".mypy_cache",
        "htmlcov",
    }
)

LANGUAGE_BY_SUFFIX = {
    suffix: profile.id
    for profile in LANGUAGE_PROFILES
    for suffix in profile.detect_suffixes
}
SPECIAL_FILES = {
    name.lower(): profile.id
    for profile in LANGUAGE_PROFILES
    for name in profile.exact_names
}
TOOLCHAIN_BY_LANGUAGE = {
    profile.id: profile.toolchain or profile.id for profile in LANGUAGE_PROFILES
}


def _is_excluded(path: Path, root: Path, exclude: Iterable[str]) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    parts = relative.parts
    for rule in exclude:
        rule = rule.strip("/").replace("\\", "/")
        if rule in parts:
            return True
        as_posix = relative.as_posix()
        if as_posix == rule or as_posix.startswith(rule.rstrip("/") + "/"):
            return True
    return False


def _skip_walk_dir(name: str, full: Path, root: Path, exclude: Iterable[str]) -> bool:
    if name in ALWAYS_SKIP_DIRS:
        return True
    if name.startswith(".") and name not in KEEP_HIDDEN_DIRS:
        return True
    return _is_excluded(full, root, exclude)


def iter_project_files(root: Path, config: QualityConfig) -> list[Path]:
    files: list[Path] = []
    exclude = config.detect_exclude
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        dirnames[:] = [
            name
            for name in dirnames
            if not _skip_walk_dir(name, current / name, root, exclude)
        ]
        for filename in filenames:
            path = current / filename
            if _is_excluded(path, root, exclude):
                continue
            files.append(path)
    return files


def git_changed_files(root: Path, base: str | None) -> list[Path] | None:
    if not base:
        return None
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMRTUXB", f"{base}...HEAD"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        return None
    files: list[Path] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        path = (root / line).resolve()
        if path.is_file():
            files.append(path)
    return files


def detect_languages(
    root: Path,
    config: QualityConfig,
    files: list[Path] | None = None,
) -> dict[str, list[str]]:
    selected = files if files is not None else iter_project_files(root, config)
    languages: set[str] = set()
    file_kinds: set[str] = set()
    ambiguities: list[str] = []
    for path in selected:
        matched = profiles_for_path(path, root)
        try:
            with path.open(encoding="utf-8", errors="ignore") as handle:
                first_line = handle.readline(512)
        except OSError:
            first_line = ""
        # A shebang is authoritative, even when a misleading suffix is present.
        shebang = profiles_for_shebang(first_line)
        if shebang:
            matched = shebang
        elif path.suffix.lower() == ".h":
            try:
                ambiguous_path = path.relative_to(root).as_posix()
            except ValueError:
                ambiguous_path = str(path)
            ambiguities.append(f"{ambiguous_path}: c or cpp")
        for profile in matched:
            if profile.kind == "language":
                languages.add(profile.id)
            else:
                file_kinds.add(profile.id)

    allowed = config.language_filter()
    if allowed is not None:
        languages = {item for item in languages if item in allowed}

    ordered = [profile.id for profile in LANGUAGE_PROFILES if profile.id in languages]
    toolchains = []
    for language in ordered:
        toolchain = TOOLCHAIN_BY_LANGUAGE[language]
        if toolchain not in toolchains:
            toolchains.append(toolchain)
    gate_languages: list[str] = []
    for language in ordered:
        mapped = gate_language(language)
        if mapped not in gate_languages:
            gate_languages.append(mapped)
    ordered_kinds = [
        profile.id
        for profile in PROFILES.values()
        if profile.kind == "file" and profile.id in file_kinds
    ]
    capabilities: list[str] = []
    for profile_id in [*ordered, *ordered_kinds]:
        for capability in PROFILES[profile_id].capabilities:
            if capability not in capabilities:
                capabilities.append(capability)
    return {
        "languages": ordered,
        "toolchains": toolchains,
        "gate_languages": gate_languages,
        "file_kinds": ordered_kinds,
        "capabilities": capabilities,
        "ambiguities": sorted(ambiguities),
    }


@dataclass(frozen=True)
class Workspace:
    name: str
    path: str
    manifest: str
    language: str


def discover_workspaces(root: Path) -> list[Workspace]:
    """Discover root and nested packages / workspace boundaries."""
    workspaces: list[Workspace] = []
    manifest_types = [
        ("package.json", "javascript"),
        ("pyproject.toml", "python"),
        ("Cargo.toml", "rust"),
        ("go.mod", "go"),
        ("pom.xml", "java"),
        ("mix.exs", "elixir"),
        ("Gemfile", "ruby"),
        ("composer.json", "php"),
    ]
    for manifest, lang in manifest_types:
        if (root / manifest).is_file():
            workspaces.append(
                Workspace(name=root.name, path=".", manifest=manifest, language=lang)
            )

    try:
        children = sorted(root.iterdir())
    except OSError:
        children = []

    for child in children:
        if (
            not child.is_dir()
            or child.name in ALWAYS_SKIP_DIRS
            or child.name.startswith(".")
        ):
            continue
        rel = child.relative_to(root).as_posix()
        for manifest, lang in manifest_types:
            if (child / manifest).is_file():
                workspaces.append(
                    Workspace(
                        name=child.name, path=rel, manifest=manifest, language=lang
                    )
                )
    return workspaces


def filter_workspaces_for_changes(
    workspaces: list[Workspace], changed_paths: list[str]
) -> list[Workspace]:
    """Isolate package changes so an edit in one package avoids unrelated package jobs."""
    if not changed_paths:
        return workspaces
    matched: list[Workspace] = []
    has_shared_change = any(
        not any(p.startswith(ws.path + "/") for ws in workspaces if ws.path != ".")
        for p in changed_paths
    )
    for ws in workspaces:
        if ws.path == ".":
            if has_shared_change:
                matched.append(ws)
            continue
        if any(p == ws.path or p.startswith(ws.path + "/") for p in changed_paths):
            matched.append(ws)
    return matched or workspaces
