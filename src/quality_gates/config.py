from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from quality_gates import ALL_LANGUAGES

DEFAULT_EXCLUDE = [
    ".git",
    ".quality-gates",
    ".quality-reports",
    "node_modules",
    "dist",
    "build",
    "target",
    "vendor",
    ".venv",
    "venv",
    "__pycache__",
    ".ruff_cache",
    ".pytest_cache",
    "tests/fixtures",
    "tooling/js/node_modules",
]


def _as_list(value: Any, fallback: list[str]) -> list[str]:
    if value is None:
        return list(fallback)
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(item) for item in value]
    return list(fallback)


@dataclass
class QualityConfig:
    languages: list[str] = field(default_factory=lambda: ["auto"])
    fail_on: list[str] = field(
        default_factory=lambda: [
            "format",
            "lint",
            "dry",
            "security",
            "compile",
            "version",
        ]
    )
    ai_review: str = "pr-only"
    auto_install: bool = False
    ci_mode: str = "local"
    ci_github_gates: list[str] = field(default_factory=lambda: ["version", "review"])
    require_changelog: str = "if-present"
    compile_require_security: bool = True
    detect_exclude: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDE))
    prefer_project_tools: bool = True
    dry_min_lines: int = 6
    dry_min_tokens: int = 50
    dry_threshold: int = 0
    dry_ignore: list[str] = field(
        default_factory=lambda: [
            "**/node_modules/**",
            "**/dist/**",
            "**/build/**",
            "**/target/**",
            "**/vendor/**",
            "**/.git/**",
            "**/tests/fixtures/**",
        ]
    )
    sql_dialect: str = "ansi"
    review_provider: str = "auto"
    review_model: str = ""
    max_diff_bytes: int = 120_000
    raw: dict[str, Any] = field(default_factory=dict)

    def language_filter(self) -> list[str] | None:
        if not self.languages or self.languages == ["auto"]:
            return None
        unknown = [item for item in self.languages if item not in ALL_LANGUAGES]
        if unknown:
            raise ValueError(f"Unknown languages in quality.toml: {unknown}")
        return list(self.languages)

    def should_auto_install(self) -> bool:
        if os.environ.get("QUALITY_GATES_AUTO_INSTALL") == "1":
            return True
        if os.environ.get("GITHUB_ACTIONS") == "true":
            return True
        return self.auto_install


def _section(data: dict[str, Any], *names: str) -> dict[str, Any]:
    cursor: Any = data
    for name in names:
        if not isinstance(cursor, dict) or name not in cursor:
            return {}
        cursor = cursor[name]
    return cursor if isinstance(cursor, dict) else {}


def load_config(project: Path) -> QualityConfig:
    path = project / "quality.toml"
    data: dict[str, Any] = {}
    if path.is_file():
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    quality = _section(data, "quality")
    detect = _section(data, "quality", "detect")
    fmt = _section(data, "quality", "format")
    dry = _section(data, "quality", "dry")
    sql = _section(data, "quality", "sql")
    review = _section(data, "quality", "review")
    ci = _section(data, "quality", "ci")
    compile_cfg = _section(data, "quality", "compile")
    version_cfg = _section(data, "quality", "version")

    auto_install = quality.get("auto_install", False)
    if isinstance(auto_install, str):
        auto_install = auto_install.lower() in {"1", "true", "yes"}

    ci_mode = str(ci.get("mode", "local")).lower()
    if ci_mode not in {"local", "github", "both"}:
        ci_mode = "local"

    changelog = str(version_cfg.get("require_changelog", "if-present"))
    if changelog not in {"if-present", "always", "never"}:
        changelog = "if-present"

    return QualityConfig(
        languages=_as_list(quality.get("languages"), ["auto"]),
        fail_on=_as_list(
            quality.get("fail_on"),
            ["format", "lint", "dry", "security", "compile", "version"],
        ),
        ai_review=str(quality.get("ai_review", "pr-only")),
        auto_install=bool(auto_install),
        ci_mode=ci_mode,
        ci_github_gates=_as_list(ci.get("github_gates"), ["version", "review"]),
        require_changelog=changelog,
        compile_require_security=bool(compile_cfg.get("require_security", True)),
        detect_exclude=_as_list(detect.get("exclude"), DEFAULT_EXCLUDE),
        prefer_project_tools=bool(fmt.get("prefer_project_tools", True)),
        dry_min_lines=int(dry.get("min_lines", 6)),
        dry_min_tokens=int(dry.get("min_tokens", 50)),
        dry_threshold=int(dry.get("threshold", 0)),
        dry_ignore=_as_list(dry.get("ignore"), QualityConfig().dry_ignore),
        sql_dialect=str(sql.get("dialect", "ansi")),
        review_provider=str(review.get("provider", "auto")),
        review_model=str(review.get("model", "")),
        max_diff_bytes=int(review.get("max_diff_bytes", 120_000)),
        raw=data,
    )


def find_project_config(project: Path, names: list[str]) -> Path | None:
    for name in names:
        path = project / name
        if path.exists():
            return path
    return None


def is_pr_event() -> bool:
    if os.environ.get("GITHUB_EVENT_NAME") == "pull_request":
        return True
    ref = os.environ.get("GITHUB_REF", "")
    return bool(re.match(r"refs/pull/\d+", ref))
