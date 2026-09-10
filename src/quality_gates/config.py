from __future__ import annotations

import os
import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from quality_gates import ALL_LANGUAGES
from quality_gates.registry import canonical_name

DEFAULT_REVIEW_SKIP_GLOBS = [
    "**/package-lock.json",
    "**/pnpm-lock.yaml",
    "**/yarn.lock",
    "**/npm-shrinkwrap.json",
    "**/Cargo.lock",
    "**/go.sum",
    "**/go.work.sum",
    "**/poetry.lock",
    "**/uv.lock",
    "**/composer.lock",
    "**/Gemfile.lock",
    "**/*.min.js",
    "**/*.min.css",
    "**/dist/**",
    "**/build/**",
    "**/vendor/**",
    "**/.venv/**",
    "**/generated/**",
    "**/*_generated.*",
    "**/*.pb.go",
    "**/*.pb.ts",
    "**/CHANGELOG.md",
    "**/changelog.md",
]

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


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


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
    "regex",
    "packages",
    "dry",
    "security",
    "compile",
    "contract",
    "impact",
    "test",
    "coverage",
    "audit",
    "ui",
    "version",
    "merge",
    "migration",
    "authorization",
    "resilience",
    "mutation",
    "performance",
    "plugins",
    "exceptions",
]
DEFAULT_GITHUB_GATES = [
    "format",
    "lint",
    "regex",
    "packages",
    "security",
    "impact",
    "audit",
    "version",
    "merge",
    "review",
    "comments",
]
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
        "execution_environment",
        "jobs",
        "cache",
        "required_tools",
        "ci",
        "compile",
        "contract",
        "coverage",
        "audit",
        "ui",
        "impact",
        "test",
        "version",
        "detect",
        "format",
        "lint",
        "regex",
        "packages",
        "dry",
        "sql",
        "review",
        "merge",
        "comments",
        "migration",
        "authorization",
        "resilience",
        "mutation",
        "performance",
        "plugins",
        "exceptions",
        "license",
        "policy",
        "baseline",
        "comment_on_pr",
        "retention",
        "cost",
        "outcomes",
        "notify",
        "packs",
        "rbac",
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
            "**/.cursor/skills/**",
            "**/.claude/skills/**",
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
    review_ingest_agent_files: bool = True
    review_related_files: int = 8
    review_related_bytes: int = 24_000
    review_validate: bool = True
    review_inline: bool = True
    review_check_run: bool = True
    review_verify_tests: bool = False
    review_symbol_neighbors: bool = True
    review_incremental: bool = True
    review_risk: str = "auto"
    review_cheap_model: str = ""
    review_full_model: str = ""
    review_skip_globs: list[str] = field(
        default_factory=lambda: list(DEFAULT_REVIEW_SKIP_GLOBS)
    )
    review_automatic: bool = True
    review_drafts: bool = False
    review_notify_owners: bool = False
    review_confidence_mode: str = "balanced"
    review_named_mode: str = "standard"
    review_fail_on_severity: list[str] = field(default_factory=list)
    review_disabled_categories: list[str] = field(default_factory=list)
    review_packs: list[str] = field(default_factory=lambda: ["auto"])
    review_base_url: str = ""
    retention_days: int = 0
    cost_monthly_cap: float = 0.0
    cost_per_pr_tokens: int = 0
    outcomes_webhooks: list[str] = field(default_factory=list)
    notify_slack: str = ""
    notify_teams: str = ""
    merge_enabled: bool = True
    merge_verify: str = "auto"
    merge_verify_tests: bool = False
    merge_siblings: bool = False
    merge_base: str = ""
    comments_in_oracle: bool = True
    comments_fail: bool = False
    regex_enabled: bool = True
    regex_include_defaults: bool = True
    regex_rules: list[dict[str, Any]] = field(default_factory=list)
    packages_enabled: bool = True
    packages_include_defaults: bool = True
    packages_require_declared: bool = True
    packages_deny: list[dict[str, Any]] = field(default_factory=list)
    packages_allow: list[str] = field(default_factory=list)
    test_require_for_source: bool = True
    test_timing_enabled: bool = True
    test_timing_regression_pct: float = 15.0
    test_timing_min_delta_ms: float = 50.0
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
    policy_exceptions: list[dict[str, Any]] = field(default_factory=list)
    execution_environment: str = "local"
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
    data = _apply_org_defaults(project, data)
    data = _apply_trusted_merge_policy(project, data)
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
    env_trust = os.environ.get("QUALITY_TRUST", "").strip().lower()
    if env_trust in TRUST_POLICIES:
        trust = env_trust
    else:
        trust = str(quality.get("trust", default_trust)).lower()
    if trust not in TRUST_POLICIES:
        raise ValueError("quality.trust must be one of: " + ", ".join(TRUST_POLICIES))
    detect = _section(data, "quality", "detect")
    fmt = _section(data, "quality", "format")
    dry = _section(data, "quality", "dry")
    sql = _section(data, "quality", "sql")
    review = _section(data, "quality", "review")
    regex_cfg = _section(data, "quality", "regex")
    packages_cfg = _section(data, "quality", "packages")
    test_cfg = _section(data, "quality", "test")
    ci = _section(data, "quality", "ci")
    compile_cfg = _section(data, "quality", "compile")
    version_cfg = _section(data, "quality", "version")
    ui_cfg = _section(data, "quality", "ui")
    impact_cfg = _section(data, "quality", "impact")
    coverage_cfg = _section(data, "quality", "coverage")
    audit_cfg = _section(data, "quality", "audit")
    cache_cfg = _section(data, "quality", "cache")
    merge_cfg = _section(data, "quality", "merge")
    comments_cfg = _section(data, "quality", "comments")

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
        review_ingest_agent_files=_as_bool(review.get("ingest_agent_files"), True),
        review_related_files=max(0, min(32, int(review.get("related_files", 8) or 8))),
        review_related_bytes=max(
            4000, int(review.get("related_bytes", 24_000) or 24_000)
        ),
        review_validate=_as_bool(review.get("validate"), True),
        review_inline=_as_bool(review.get("inline_comments"), True),
        review_check_run=_as_bool(review.get("check_run"), True),
        review_verify_tests=_as_bool(review.get("verify_tests"), False),
        review_symbol_neighbors=_as_bool(review.get("symbol_neighbors"), True),
        review_incremental=_as_bool(review.get("incremental"), True),
        review_risk=_review_risk(review.get("risk", "auto")),
        review_cheap_model=str(review.get("cheap_model") or ""),
        review_full_model=str(review.get("full_model") or ""),
        review_skip_globs=_as_list(review.get("skip_globs"), DEFAULT_REVIEW_SKIP_GLOBS),
        review_automatic=_as_bool(review.get("automatic"), True),
        review_drafts=_as_bool(review.get("drafts"), False),
        review_notify_owners=_as_bool(review.get("notify_owners"), False),
        review_confidence_mode=_confidence_mode(review.get("confidence", "balanced")),
        review_named_mode=_named_mode(review.get("named_mode", "standard")),
        review_fail_on_severity=_as_list(review.get("fail_on_severity"), []),
        review_disabled_categories=_as_list(review.get("disable_categories"), []),
        review_packs=_as_list(review.get("packs"), ["auto"]),
        review_base_url=str(review.get("base_url") or ""),
        retention_days=int(_section(data, "quality", "retention").get("days") or 0),
        cost_monthly_cap=_as_float(
            _section(data, "quality", "cost").get("monthly_cap"), 0.0
        ),
        cost_per_pr_tokens=int(
            _section(data, "quality", "cost").get("per_pr_tokens") or 0
        ),
        outcomes_webhooks=_as_list(
            _section(data, "quality", "outcomes").get("webhooks"), []
        ),
        notify_slack=str(_section(data, "quality", "notify").get("slack") or ""),
        notify_teams=str(_section(data, "quality", "notify").get("teams") or ""),
        merge_enabled=_as_bool(merge_cfg.get("enabled"), True),
        merge_verify=_merge_verify(merge_cfg.get("verify", "auto")),
        merge_verify_tests=_as_bool(merge_cfg.get("verify_tests"), False),
        merge_siblings=_as_bool(merge_cfg.get("siblings"), False),
        merge_base=str(merge_cfg.get("base") or ""),
        comments_in_oracle=_as_bool(comments_cfg.get("in_oracle"), True),
        comments_fail=_as_bool(comments_cfg.get("fail"), False),
        regex_enabled=_as_bool(regex_cfg.get("enabled"), True),
        regex_include_defaults=_as_bool(regex_cfg.get("include_defaults"), True),
        regex_rules=_as_dict_list(regex_cfg.get("rules")),
        packages_enabled=_as_bool(packages_cfg.get("enabled"), True),
        packages_include_defaults=_as_bool(packages_cfg.get("include_defaults"), True),
        packages_require_declared=_as_bool(packages_cfg.get("require_declared"), True),
        packages_deny=_as_dict_list(packages_cfg.get("deny")),
        packages_allow=_as_list(packages_cfg.get("allow"), []),
        test_require_for_source=_as_bool(test_cfg.get("require_for_source"), True),
        test_timing_enabled=_as_bool(test_cfg.get("timing"), True),
        test_timing_regression_pct=_as_float(
            test_cfg.get("timing_regression_pct"), 15.0
        ),
        test_timing_min_delta_ms=_as_float(test_cfg.get("timing_min_delta_ms"), 50.0),
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
            impact_cfg.get("require_own_tests"),
            _as_bool(test_cfg.get("require_for_source"), True),
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
        policy_exceptions=[
            item
            for item in _as_list(quality.get("exceptions"), [])
            if isinstance(item, dict)
        ],
        execution_environment=str(
            quality.get("execution_environment", "local")
        ).lower(),
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


def _apply_trusted_merge_policy(project: Path, data: dict[str, Any]) -> dict[str, Any]:
    """Keep a PR from lowering the policy that decides that PR.

    Hosted callers may pass an explicit immutable base through
    ``QUALITY_TRUSTED_BASE``.  On GitHub we otherwise use the checked-out base
    ref when available.  Local work deliberately retains its editable policy.
    """
    base = os.environ.get("QUALITY_TRUSTED_BASE")
    if not base and is_pr_event():
        base = os.environ.get("GITHUB_BASE_REF")
        if base and not base.startswith("origin/"):
            base = f"origin/{base}"
    if not base:
        return data
    try:
        verify = subprocess.run(
            ["git", "rev-parse", "--verify", base],
            cwd=project,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=3,
        )
        if verify.returncode != 0:
            return data
        raw = subprocess.run(
            ["git", "show", f"{base}:quality.toml"],
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return data
    if raw.returncode:
        return data
    try:
        trusted = tomllib.loads(raw.stdout)
    except tomllib.TOMLDecodeError:
        return data
    candidate = data.get("quality")
    control = trusted.get("quality")
    if not isinstance(candidate, dict) or not isinstance(control, dict):
        return data
    # These values authorise execution or decide merge, so only a trusted base
    # (or organisational control plane) may define them for a pull request.
    protected = {
        "fail_on",
        "trust",
        "policy",
        "baseline",
        "exceptions",
        "required_tools",
        "ci",
        "merge",
    }
    merged = dict(candidate)
    for key in protected:
        if key in control:
            merged[key] = control[key]
    out = dict(data)
    out["quality"] = merged
    return out


def _merge_verify(value: Any) -> str:
    mode = str(value or "auto").strip().lower()
    if mode in {"auto", "always", "never"}:
        return mode
    if mode in {"true", "yes", "on"}:
        return "always"
    if mode in {"false", "no", "off"}:
        return "never"
    return "auto"


def _review_risk(value: Any) -> str:
    risk = str(value or "auto").strip().lower()
    if risk not in {"auto", "skip", "cheap", "full", "heuristic"}:
        return "auto"
    return risk


def _review_mode(value: Any) -> str:
    mode = str(value or "auto").strip().lower()
    if mode not in {"auto", "agentic", "ensemble", "single", "heuristic"}:
        return "auto"
    return mode


def _confidence_mode(value: Any) -> str:
    mode = str(value or "balanced").strip().lower()
    if mode not in {"conservative", "balanced", "exploratory"}:
        return "balanced"
    return mode


def _named_mode(value: Any) -> str:
    mode = str(value or "standard").strip().lower()
    allowed = {
        "fast",
        "standard",
        "deep",
        "security",
        "tests",
        "migration",
        "architecture",
    }
    return mode if mode in allowed else "standard"


def _apply_org_defaults(project: Path, data: dict[str, Any]) -> dict[str, Any]:
    org_path = project / ".github" / "quality.org.toml"
    if not org_path.is_file():
        return data
    try:
        org = tomllib.loads(org_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return data
    org_quality = org.get("quality")
    repo_quality = data.get("quality")
    if not isinstance(org_quality, dict):
        return data
    merged = dict(org_quality)
    if isinstance(repo_quality, dict):
        merged.update(repo_quality)
        for key, value in repo_quality.items():
            if isinstance(value, dict) and isinstance(org_quality.get(key), dict):
                nested = dict(org_quality[key])
                nested.update(value)
                merged[key] = nested
    out = dict(data)
    out["quality"] = merged
    return out
