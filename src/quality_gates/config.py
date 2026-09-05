from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from quality_gates import ALL_LANGUAGES
from quality_gates.registry import canonical_name

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
    ".mypy_cache",
    "tests/fixtures",
    "tooling/js/node_modules",
    ".coverage",
    "htmlcov",
    ".zvec-grep",
    ".cursor",
    ".idea",
]


def _as_list(value: Any, fallback: list[str]) -> list[str]:
    if value is None:
        return list(fallback)
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(item) for item in value]
    return list(fallback)


def _as_dict(value: Any, fallback: dict[str, str]) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        return dict(fallback)
    return {str(key): str(val) for key, val in value.items()}


def _as_bool(value: Any, fallback: bool = False) -> bool:
    if value is None:
        return fallback
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _as_float(value: Any, fallback: float) -> float:
    if value is None:
        return fallback
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _as_ints(value: Any, fallback: list[int]) -> list[int]:
    if value is None:
        return list(fallback)
    if isinstance(value, list):
        out: list[int] = []
        for item in value:
            try:
                out.append(int(item))
            except (TypeError, ValueError):
                continue
        return out
    return list(fallback)


DEFAULT_FAIL_ON = [
    "format",
    "lint",
    "dry",
    "security",
    "compile",
    "impact",
    "coverage",
    "audit",
    "ui",
    "version",
]
DEFAULT_GITHUB_GATES = ["format", "lint", "impact", "audit", "version", "review"]
POLICIES = ("observe", "adopt", "enforce")
TRUST_POLICIES = ("trusted", "prompt", "untrusted")
CONFIG_VERSION = 1
QUALITY_KEYS = frozenset(
    {
        "config_version",
        "languages",
        "fail_on",
        "ai_review",
        "auto_install",
        "trust",
        "offline",
        "jobs",
        "cache",
        "required_tools",
        "ci",
        "compile",
        "coverage",
        "audit",
        "ui",
        "impact",
        "version",
        "detect",
        "format",
        "lint",
        "dry",
        "sql",
        "review",
        "policy",
        "baseline",
        "comment_on_pr",
    }
)


@dataclass
class QualityConfig:
    config_version: int = CONFIG_VERSION
    languages: list[str] = field(default_factory=lambda: ["auto"])
    fail_on: list[str] = field(default_factory=lambda: list(DEFAULT_FAIL_ON))
    ai_review: str = "pr-only"
    auto_install: bool = False
    trust: str = "trusted"
    offline: bool = False
    jobs: int = max(1, min(32, os.cpu_count() or 1))
    cache_enabled: bool = True
    required_tools: list[str] = field(default_factory=list)
    ci_mode: str = "local"
    ci_github_gates: list[str] = field(
        default_factory=lambda: list(DEFAULT_GITHUB_GATES)
    )
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
    review_mode: str = "auto"
    review_passes: int = 3
    review_tool_rounds: int = 4
    review_rules_dir: str = ".quality/rules"
    review_related_files: int = 8
    review_related_bytes: int = 24_000
    review_validate: bool = True
    review_inline: bool = True
    review_check_run: bool = True
    review_verify_tests: bool = False
    review_symbol_neighbors: bool = True
    ui_select: str = "changed"
    ui_framework: str = "auto"
    ui_spec_dirs: list[str] = field(default_factory=list)
    ui_path_aliases: dict[str, str] = field(default_factory=lambda: {"@/": "src/"})
    ui_coverage_map: str = ".quality-reports/ui-coverage.json"
    ui_on_github: bool = False
    impact_depth: int = 4
    impact_require_downstream: bool = True
    impact_require_own_tests: bool = False
    coverage_enabled: bool = True
    coverage_line: float = 80.0
    coverage_branch: float = 0.0
    coverage_tool: str = "auto"
    audit_enabled: bool = True
    audit_fail_on_priority: list[str] = field(default_factory=lambda: ["P0"])
    audit_min_confidence: str = "HIGH"
    audit_skip_ids: list[int] = field(default_factory=list)
    policy: str = "adopt"
    policy_baseline: str = ".quality-baseline.json"
    policy_comment: bool = True
    raw: dict[str, Any] = field(default_factory=dict)

    def language_filter(self) -> list[str] | None:
        if not self.languages or self.languages == ["auto"]:
            return None
        resolved = [canonical_name(item) for item in self.languages]
        unknown = [
            item
            for item, canonical in zip(self.languages, resolved, strict=True)
            if canonical not in ALL_LANGUAGES
        ]
        if unknown:
            raise ValueError(f"Unknown languages in quality.toml: {unknown}")
        return list(dict.fromkeys(item for item in resolved if item is not None))

    def should_auto_install(self) -> bool:
        if os.environ.get("QUALITY_GATES_AUTO_INSTALL") == "1":
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
    unknown = sorted(set(quality) - QUALITY_KEYS)
    if unknown:
        raise ValueError(f"Unknown top-level quality key(s): {', '.join(unknown)}")
    config_version = quality.get("config_version", CONFIG_VERSION)
    if not isinstance(config_version, int) or isinstance(config_version, bool):
        raise ValueError("quality.config_version must be an integer")
    if config_version != CONFIG_VERSION:
        raise ValueError(
            f"Unsupported quality.config_version {config_version}; expected {CONFIG_VERSION}"
        )
    default_trust = "untrusted" if is_pr_event() else "trusted"
    trust = str(quality.get("trust", default_trust)).lower()
    if trust not in TRUST_POLICIES:
        raise ValueError("quality.trust must be one of: " + ", ".join(TRUST_POLICIES))
    detect = _section(data, "quality", "detect")
    fmt = _section(data, "quality", "format")
    dry = _section(data, "quality", "dry")
    sql = _section(data, "quality", "sql")
    review = _section(data, "quality", "review")
    ci = _section(data, "quality", "ci")
    compile_cfg = _section(data, "quality", "compile")
    version_cfg = _section(data, "quality", "version")
    ui_cfg = _section(data, "quality", "ui")
    impact_cfg = _section(data, "quality", "impact")
    coverage_cfg = _section(data, "quality", "coverage")
    audit_cfg = _section(data, "quality", "audit")
    cache_cfg = _section(data, "quality", "cache")

    auto_install = quality.get("auto_install", False)
    if isinstance(auto_install, str):
        auto_install = auto_install.lower() in {"1", "true", "yes"}

    ui_select = str(ui_cfg.get("select", "changed")).lower()
    if ui_select in {"touched", "narrow"}:
        ui_select = "changed"
    if ui_select not in {"changed", "all"}:
        ui_select = "changed"
    ui_framework = str(ui_cfg.get("framework", "auto")).lower()
    if ui_framework not in {"auto", "playwright", "cypress"}:
        ui_framework = "auto"
    aliases = ui_cfg.get("path_aliases")
    if not isinstance(aliases, dict):
        aliases = _section(data, "quality", "ui", "path_aliases")

    ci_mode = str(ci.get("mode", "local")).lower()
    if ci_mode not in {"local", "github", "both"}:
        ci_mode = "local"

    changelog = str(version_cfg.get("require_changelog", "if-present"))
    if changelog not in {"if-present", "always", "never"}:
        changelog = "if-present"

    coverage_tool = str(coverage_cfg.get("tool", "auto")).lower()
    if coverage_tool not in {"auto", "pytest", "jest", "vitest", "go", "existing"}:
        coverage_tool = "auto"
    audit_conf = str(audit_cfg.get("min_confidence", "HIGH")).upper()
    if audit_conf not in {"HIGH", "MEDIUM", "LOW"}:
        audit_conf = "HIGH"
    fail_prios = [
        item.upper() for item in _as_list(audit_cfg.get("fail_on_priority"), ["P0"])
    ]
    if not fail_prios:
        fail_prios = ["P0"]

    policy = str(quality.get("policy", "adopt")).lower()
    if policy not in POLICIES:
        policy = "adopt"

    return QualityConfig(
        config_version=config_version,
        languages=_as_list(quality.get("languages"), ["auto"]),
        fail_on=_as_list(quality.get("fail_on"), DEFAULT_FAIL_ON),
        ai_review=str(quality.get("ai_review", "pr-only")),
        auto_install=bool(auto_install),
        trust=trust,
        offline=_as_bool(quality.get("offline"), False),
        jobs=max(
            1,
            min(
                32,
                int(
                    os.environ.get("QUALITY_GATES_JOBS")
                    or quality.get("jobs")
                    or (os.cpu_count() or 1)
                ),
            ),
        ),
        cache_enabled=_as_bool(
            os.environ.get("QUALITY_GATES_CACHE_ENABLED") or cache_cfg.get("enabled"),
            True,
        ),
        required_tools=_as_list(quality.get("required_tools"), []),
        ci_mode=ci_mode,
        ci_github_gates=_as_list(ci.get("github_gates"), DEFAULT_GITHUB_GATES),
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
        review_mode=_review_mode(review.get("mode", "auto")),
        review_passes=max(2, min(8, int(review.get("passes", 3) or 3))),
        review_tool_rounds=max(0, min(8, int(review.get("tool_rounds", 4) or 4))),
        review_rules_dir=str(review.get("rules_dir", ".quality/rules")),
        review_related_files=max(0, min(32, int(review.get("related_files", 8) or 8))),
        review_related_bytes=max(
            4000, int(review.get("related_bytes", 24_000) or 24_000)
        ),
        review_validate=_as_bool(review.get("validate"), True),
        review_inline=_as_bool(review.get("inline_comments"), True),
        review_check_run=_as_bool(review.get("check_run"), True),
        review_verify_tests=_as_bool(review.get("verify_tests"), False),
        review_symbol_neighbors=_as_bool(review.get("symbol_neighbors"), True),
        ui_select=ui_select,
        ui_framework=ui_framework,
        ui_spec_dirs=_as_list(ui_cfg.get("spec_dirs"), []),
        ui_path_aliases=_as_dict(aliases, {"@/": "src/"}),
        ui_coverage_map=str(
            ui_cfg.get("coverage_map", ".quality-reports/ui-coverage.json")
        ),
        ui_on_github=_as_bool(ui_cfg.get("on_github"), False),
        impact_depth=int(impact_cfg.get("depth", 4)),
        impact_require_downstream=_as_bool(
            impact_cfg.get("require_downstream", True), True
        ),
        impact_require_own_tests=_as_bool(
            impact_cfg.get("require_own_tests", False), False
        ),
        coverage_enabled=_as_bool(coverage_cfg.get("enabled"), True),
        coverage_line=_as_float(coverage_cfg.get("line"), 80.0),
        coverage_branch=_as_float(coverage_cfg.get("branch"), 0.0),
        coverage_tool=coverage_tool,
        audit_enabled=_as_bool(audit_cfg.get("enabled"), True),
        audit_fail_on_priority=fail_prios,
        audit_min_confidence=audit_conf,
        audit_skip_ids=_as_ints(audit_cfg.get("skip", audit_cfg.get("skip_ids")), []),
        policy=policy,
        policy_baseline=str(quality.get("baseline") or ".quality-baseline.json"),
        policy_comment=_as_bool(quality.get("comment_on_pr"), True),
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


def _review_mode(value: Any) -> str:
    mode = str(value or "auto").strip().lower()
    if mode not in {"auto", "agentic", "ensemble", "single", "heuristic"}:
        return "auto"
    return mode
