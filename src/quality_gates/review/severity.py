"""Critical / High / Medium / Low / Info taxonomy and merge mapping."""

from __future__ import annotations

from quality_gates.models import Finding

LEVELS = ("critical", "high", "medium", "low", "info")
_FROM_FINDING = {
    "error": "high",
    "warning": "medium",
    "info": "info",
}
_FROM_PRIORITY = {
    "p0": "critical",
    "p1": "high",
    "p2": "medium",
    "p3": "low",
}
_TO_FINDING = {
    "critical": "error",
    "high": "error",
    "medium": "warning",
    "low": "info",
    "info": "info",
}


def normalize_level(value: str | None) -> str:
    text = (value or "").strip().lower()
    if text in LEVELS:
        return text
    if text in _FROM_FINDING:
        return _FROM_FINDING[text]
    if text in _FROM_PRIORITY:
        return _FROM_PRIORITY[text]
    return "medium"


def taxonomy_level(finding: Finding) -> str:
    if finding.rule and finding.rule.lower() in {
        "hardcoded-secret",
        "gitleaks",
        "secret",
    }:
        return "critical"
    if (finding.owasp or "") and finding.severity == "error":
        return "high"
    if finding.confidence == "LOW" and finding.severity != "error":
        return "low"
    return _FROM_FINDING.get(finding.severity, "medium")


def apply_taxonomy(finding: Finding) -> Finding:
    finding.confidence = finding.confidence or "HIGH"
    level = taxonomy_level(finding)
    if finding.severity in {"error", "warning", "info"}:
        finding.severity = _TO_FINDING.get(level, finding.severity)
    return finding


def blocks_merge(level: str, fail_on: list[str] | None) -> bool:
    allowed = {normalize_level(item) for item in (fail_on or [])}
    if not allowed:
        return False
    rank = {name: index for index, name in enumerate(LEVELS)}
    threshold = min(rank[item] for item in allowed if item in rank)
    return rank.get(normalize_level(level), 4) <= threshold
