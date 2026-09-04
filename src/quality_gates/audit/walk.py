"""Walk the repo once and classify which audit surfaces exist."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.detect import iter_project_files

TEXT_SUFFIXES = {
    ".py",
    ".pyi",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".vue",
    ".svelte",
    ".go",
    ".rs",
    ".java",
    ".cs",
    ".c",
    ".h",
    ".cc",
    ".cpp",
    ".cxx",
    ".hh",
    ".hpp",
    ".hxx",
    ".swift",
    ".kt",
    ".dart",
    ".scala",
    ".sc",
    ".lua",
    ".r",
    ".rmd",
    ".m",
    ".sql",
    ".yml",
    ".yaml",
    ".toml",
    ".json",
    ".env",
    ".ini",
    ".cfg",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".ps1",
    ".psm1",
    ".psd1",
    ".xml",
    ".gradle",
    ".kts",
    ".rb",
    ".php",
    ".html",
    ".htm",
    ".css",
    ".md",
    ".dockerfile",
}

HTTP_NEEDLES = (
    "fastapi",
    "from flask",
    "import flask",
    "django.urls",
    "django.http",
    "starlette",
    "aiohttp.web",
    "from tornado",
    "express()",
    "from 'express'",
    'from "express"',
    "require('express')",
    'require("express")',
    "gin.default",
    "gin.New",
    "echo.New",
    "axum::",
    "actix_web",
    "org.springframework.web",
    "@restcontroller",
    "@controller",
    "chi.NewRouter",
    "http.Handle",
    "http.ListenAndServe",
    "@app.route",
    "@router.",
    "APIRouter(",
    "FastAPI(",
    "Flask(",
)

AUTH_NEEDLES = (
    "jwt",
    "oauth",
    "bcrypt",
    "argon2",
    "login_required",
    "HTTPBearer",
    "passport",
    "next-auth",
)

SQL_NEEDLES = (
    "select *",
    "select distinct",
    "sqlalchemy",
    "django.db",
    "prisma.",
    "sequelize",
    "typeorm",
    "psycopg",
    "sqlite3",
    "mongodb",
    "mongoose",
    "jdbc",
    "gorm.",
)

UPLOAD_NEEDLES = (
    "multipart",
    "file_upload",
    "upload_file",
    "multer",
    "formidable",
    "werkzeug.datastructures.FileStorage",
    "request.files",
    "shutil.unpack_archive",
)

SKIP_DIR_PARTS = {
    "node_modules",
    ".git",
    "dist",
    "build",
    "target",
    "vendor",
    ".venv",
    "venv",
    "__pycache__",
    ".quality-reports",
    ".quality-gates",
    "coverage",
    "htmlcov",
    ".ruff_cache",
    ".pytest_cache",
    ".mypy_cache",
    ".zvec-grep",
    ".cursor",
    ".idea",
}


@dataclass
class FileHit:
    path: Path
    relative: str
    text: str
    lines: list[str]
    is_test: bool
    is_source: bool


@dataclass
class RepoContext:
    root: Path
    files: list[FileHit] = field(default_factory=list)
    surfaces: set[str] = field(default_factory=set)
    has_package_json: bool = False
    has_lockfile: bool = False
    has_go_mod: bool = False
    has_go_sum: bool = False
    has_cargo: bool = False
    has_cargo_lock: bool = False
    workflow_files: list[FileHit] = field(default_factory=list)


def load_context(root: Path, config: QualityConfig) -> RepoContext:
    ctx = RepoContext(root=root)
    ctx.has_package_json = (root / "package.json").is_file()
    ctx.has_lockfile = any(
        (root / name).is_file()
        for name in (
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
            "bun.lock",
            "bun.lockb",
            "npm-shrinkwrap.json",
        )
    )
    ctx.has_go_mod = (root / "go.mod").is_file()
    ctx.has_go_sum = (root / "go.sum").is_file()
    ctx.has_cargo = (root / "Cargo.toml").is_file()
    ctx.has_cargo_lock = (root / "Cargo.lock").is_file()

    for path in iter_project_files(root, config):
        if any(part in SKIP_DIR_PARTS for part in path.parts):
            continue
        name = path.name.lower()
        suffix = path.suffix.lower()
        known = suffix in TEXT_SUFFIXES or name in {
            "dockerfile",
            ".env",
            ".env.example",
            ".env.local",
        }
        if not known and suffix not in {".yml", ".yaml"} and "dockerfile" not in name:
            continue
        try:
            if path.stat().st_size > 750_000:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = _rel(root, path)
        hit = FileHit(
            path=path,
            relative=rel,
            text=text,
            lines=text.splitlines(),
            is_test=_is_test(rel),
            is_source=_is_source(path, rel),
        )
        ctx.files.append(hit)
        if ".github/workflows/" in rel.replace("\\", "/"):
            ctx.workflow_files.append(hit)

    ctx.surfaces = _surfaces(ctx)
    return ctx


def _surfaces(ctx: RepoContext) -> set[str]:
    found: set[str] = set()
    sources = [
        item for item in ctx.files if item.is_source and not _is_auditor_source(item)
    ]
    blob = "\n".join(item.text[:8000] for item in sources).lower()
    names = " ".join(item.relative.lower() for item in ctx.files)
    if any(_contains(item.text.lower(), HTTP_NEEDLES) for item in sources):
        found.add("http")
    if (
        any(
            item.path.suffix.lower() in {".tsx", ".jsx", ".vue", ".svelte", ".html"}
            for item in ctx.files
        )
        or "next.config" in names
        or "vite.config" in names
    ):
        found.add("frontend")
    if _contains(blob, AUTH_NEEDLES):
        found.add("auth")
    if _contains(blob, SQL_NEEDLES) or any(
        item.path.suffix.lower() == ".sql" for item in ctx.files
    ):
        found.add("sql")
        found.add("db")
    if _contains(blob, UPLOAD_NEEDLES):
        found.add("upload")
    if ctx.workflow_files or (ctx.root / ".github").is_dir():
        found.add("ci")
    if (
        ctx.has_package_json
        or (ctx.root / "pyproject.toml").is_file()
        or ctx.has_go_mod
        or ctx.has_cargo
    ):
        found.add("deps")
    return found


def _is_auditor_source(hit: FileHit) -> bool:
    """Scanner catalogs and detector source are not the product surface."""
    posix = hit.relative.replace("\\", "/")
    if posix.startswith("src/quality_gates/audit/") or posix.startswith(
        "quality_gates/audit/"
    ):
        return True
    return posix.endswith(
        ("gates/security.py", "gates/review.py", "review/heuristic.py")
    )


def _contains(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def _is_test(relative: str) -> bool:
    posix = relative.replace("\\", "/").lower()
    name = Path(posix).name
    if (
        name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith("_test.go")
    ):
        return True
    if ".spec." in name or ".test." in name or ".cy." in name:
        return True
    parts = posix.split("/")
    return any(part in {"tests", "test", "__tests__", "fixtures"} for part in parts)


def _is_source(path: Path, relative: str) -> bool:
    if _is_test(relative):
        return False
    return path.suffix.lower() in TEXT_SUFFIXES - {
        ".sql",
        ".yml",
        ".yaml",
        ".toml",
        ".json",
        ".env",
        ".ini",
        ".cfg",
        ".xml",
        ".gradle",
        ".html",
        ".htm",
        ".css",
        ".md",
        ".dockerfile",
    }


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)
