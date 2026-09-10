"""Structured PR summary: intent, risk, impact, merge signal."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from quality_gates.models import Finding, GateResult
from quality_gates.review.severity import taxonomy_level

INTENTS = (
    "feature",
    "bugfix",
    "refactor",
    "dependency",
    "migration",
    "docs",
    "test",
    "config",
)
RISK_LEVELS = ("low", "medium", "high", "critical")

_INTENT_MARKERS: dict[str, tuple[str, ...]] = {
    "docs": (".md", "docs/", "readme"),
    "test": ("test", "spec", "__tests__"),
    "dependency": (
        "package.json",
        "package-lock",
        "pnpm-lock",
        "yarn.lock",
        "uv.lock",
        "requirements",
        "go.mod",
        "cargo.toml",
        "pom.xml",
    ),
    "migration": ("migration", "alembic", "prisma/schema"),
    "config": (".yml", ".yaml", ".toml", ".json", "dockerfile", ".tf"),
    "bugfix": ("fix", "bug", "hotfix"),
    "refactor": ("refactor", "cleanup"),
}


def classify_intent(
    paths: list[str],
    *,
    title: str = "",
    commits: list[str] | None = None,
) -> str:
    hay = "\n".join([title, *(commits or []), *paths]).lower()
    scores: Counter[str] = Counter()
    for intent, markers in _INTENT_MARKERS.items():
        scores[intent] = sum(1 for marker in markers if marker in hay)
    if scores and scores.most_common(1)[0][1] > 0:
        return scores.most_common(1)[0][0]
    return "feature"


def score_risk(
    paths: list[str],
    findings: list[Finding],
    *,
    diff_added: int = 0,
    coverage_delta: float | None = None,
    auth_touched: bool = False,
    deps_touched: bool = False,
) -> str:
    sensitive = any(
        any(part in path.lower() for part in ("auth", "payment", "infra", "secret"))
        for path in paths
    )
    critical = any(taxonomy_level(item) == "critical" for item in findings)
    high = any(taxonomy_level(item) == "high" for item in findings)
    if critical or (auth_touched and high):
        return "critical"
    if high or sensitive or (deps_touched and high):
        return "high"
    if (
        auth_touched
        or deps_touched
        or diff_added >= 400
        or (coverage_delta is not None and coverage_delta < 0)
    ):
        return "medium"
    return "low"


def merge_signal(
    findings: list[Finding],
    *,
    risk: str,
    fail_on_review: bool = False,
    incomplete: bool = False,
) -> str:
    blocking = [item for item in findings if item.severity == "error"]
    if incomplete:
        return "needs work"
    if fail_on_review and blocking:
        return "needs work"
    if risk in {"critical", "high"} and blocking:
        return "needs work"
    if blocking:
        return "needs work"
    return "safe to merge"


def impact_map(
    paths: list[str],
    *,
    packages: list[str] | None = None,
    owners: list[str] | None = None,
) -> dict[str, list[str]]:
    modules = sorted({path.split("/")[0] for path in paths if "/" in path})
    apis = [
        path
        for path in paths
        if any(part in path for part in ("api", "route", "graphql", "proto"))
    ]
    stores = [
        path
        for path in paths
        if any(part in path for part in ("model", "schema", "migration"))
    ]
    return {
        "modules": modules or ["(root)"],
        "packages": list(packages or []),
        "apis": apis,
        "data_stores": stores,
        "owners": list(owners or []),
        "paths": paths[:40],
    }


def render_structured_summary(
    *,
    intent: str,
    risk: str,
    signal: str,
    findings: list[Finding],
    paths: list[str],
    languages: list[str],
    coverage_note: str = "",
    impact: dict[str, list[str]] | None = None,
    incomplete: list[str] | None = None,
    llm_summary: str = "",
    issue_text: str = "",
) -> str:
    counts = Counter(taxonomy_level(item) for item in findings)
    top = findings[:8]
    lines = [
        f"Intent: **{intent}**",
        f"Risk: **{risk}**",
        f"Signal: **{signal}**",
        f"Languages: `{', '.join(languages) or 'unknown'}`",
        f"Files: {len(paths)}",
        "",
    ]
    if issue_text:
        lines.extend(["Linked issue:", issue_text.strip()[:800], ""])
    if llm_summary:
        lines.extend([llm_summary.strip(), ""])
    lines.append(
        "Findings by severity: "
        + ", ".join(
            f"{name}={counts[name]}"
            for name in ("critical", "high", "medium", "low", "info")
            if counts[name]
        )
    )
    if not findings:
        lines.append("No high-confidence findings.")
    else:
        lines.append("")
        lines.append("Top findings:")
        for item in top:
            loc = (
                f"{item.path}:{item.line}"
                if item.path and item.line
                else (item.path or "repo")
            )
            lines.append(f"- [{taxonomy_level(item)}] `{loc}` {item.message}")
    if coverage_note:
        lines.extend(["", f"Tests: {coverage_note}"])
    if impact:
        lines.extend(["", "Change impact:"])
        for key in ("modules", "packages", "apis", "data_stores", "owners"):
            values = impact.get(key) or []
            if values:
                lines.append(f"- {key}: {', '.join(values[:8])}")
    if incomplete:
        lines.extend(
            ["", "Not deeply analyzed:", *[f"- {item}" for item in incomplete]]
        )
    return "\n".join(lines).strip() + "\n"


def coverage_note_from_prior(prior: list[GateResult]) -> str:
    for result in prior:
        if result.name == "coverage":
            if result.status == "pass":
                return "coverage gate passed"
            if result.status == "fail":
                return "coverage gate failed or dropped"
            return f"coverage {result.status}"
        if result.name == "test" and result.status == "fail":
            return "tests failed"
    return "no coverage delta recorded"


def summary_payload(
    *,
    intent: str,
    risk: str,
    signal: str,
    findings: list[Finding],
    paths: list[str],
) -> dict[str, Any]:
    return {
        "intent": intent,
        "risk": risk,
        "signal": signal,
        "files": len(paths),
        "findings": len(findings),
        "by_severity": dict(Counter(taxonomy_level(item) for item in findings)),
    }


def write_summary(root: Path, payload: dict[str, Any]) -> Path:
    reports = root / ".quality-reports"
    reports.mkdir(parents=True, exist_ok=True)
    path = reports / "review-summary.json"
    import json

    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
