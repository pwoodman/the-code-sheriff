from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent


def repo_root() -> Path | None:
    """Return the quality-gates source checkout when running from a git clone."""
    candidate = PACKAGE_DIR.parents[1]
    if (candidate / "pyproject.toml").is_file() and (candidate / "configs").is_dir():
        return candidate
    return None


def bundled_dir() -> Path:
    inside_package = PACKAGE_DIR / "bundled"
    source = repo_root()
    if source is not None:
        return source / "configs"
    return inside_package


def bundled_file(*parts: str) -> Path:
    path = bundled_dir().joinpath(*parts)
    if not path.is_file():
        fallback = PACKAGE_DIR.joinpath("bundled", *parts)
        if fallback.is_file():
            return fallback
    return path


def tooling_js_dir() -> Path:
    source = repo_root()
    if source is not None:
        return source / "tooling" / "js"
    nested = PACKAGE_DIR / "tooling_js"
    if (nested / "package.json").is_file():
        return nested
    return source / "tooling" / "js" if source else nested


def project_root(explicit: str | Path | None = None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    cwd = Path.cwd().resolve()
    for candidate in [cwd, *cwd.parents]:
        if (candidate / "quality.toml").is_file() or (candidate / ".git").exists():
            return candidate
    return cwd


def cache_dir() -> Path:
    override = os.environ.get("QUALITY_GATES_CACHE")
    path = Path(override) if override else Path.home() / ".cache" / "quality-gates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def bin_dir() -> Path:
    path = cache_dir() / "bin"
    path.mkdir(parents=True, exist_ok=True)
    return path
