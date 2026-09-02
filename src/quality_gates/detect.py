from __future__ import annotations

import subprocess
from collections.abc import Iterable
from pathlib import Path

from quality_gates.config import QualityConfig

LANGUAGE_BY_SUFFIX = {
    ".cs": "csharp",
    ".csproj": "csharp",
    ".sln": "csharp",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "react",
    ".ts": "typescript",
    ".cts": "typescript",
    ".mts": "typescript",
    ".tsx": "react",
    ".rs": "rust",
    ".go": "go",
    ".py": "python",
    ".pyi": "python",
    ".java": "java",
    ".sql": "sql",
}

SPECIAL_FILES = {
    "cargo.toml": "rust",
    "go.mod": "go",
    "package.json": "javascript",
    "tsconfig.json": "typescript",
    "pyproject.toml": "python",
    "requirements.txt": "python",
    "pom.xml": "java",
    "build.gradle": "java",
    "build.gradle.kts": "java",
}

TOOLCHAIN_BY_LANGUAGE = {
    "csharp": "csharp",
    "javascript": "node",
    "typescript": "node",
    "react": "node",
    "rust": "rust",
    "go": "go",
    "python": "python",
    "java": "java",
    "sql": "sql",
}

REACT_SUFFIXES = {".jsx", ".tsx"}


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


def iter_project_files(root: Path, config: QualityConfig) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if _is_excluded(path, root, config.detect_exclude):
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
    for path in selected:
        suffix = path.suffix.lower()
        name = path.name.lower()
        if name in SPECIAL_FILES:
            languages.add(SPECIAL_FILES[name])
        if suffix in LANGUAGE_BY_SUFFIX:
            languages.add(LANGUAGE_BY_SUFFIX[suffix])
        if suffix in REACT_SUFFIXES:
            languages.add("javascript")
            if suffix == ".tsx":
                languages.add("typescript")

    allowed = config.language_filter()
    if allowed is not None:
        languages = {item for item in languages if item in allowed}

    ordered = [item for item in TOOLCHAIN_BY_LANGUAGE if item in languages]
    toolchains = []
    for language in ordered:
        toolchain = TOOLCHAIN_BY_LANGUAGE[language]
        if toolchain not in toolchains:
            toolchains.append(toolchain)
    gate_languages: list[str] = []
    for language in ordered:
        mapped = "javascript" if language in {"typescript", "react"} else language
        if mapped not in gate_languages:
            gate_languages.append(mapped)
    return {
        "languages": ordered,
        "toolchains": toolchains,
        "gate_languages": gate_languages,
    }
