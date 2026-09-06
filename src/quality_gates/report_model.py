from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from quality_gates.diagnostics import pointer
from quality_gates.models import Finding, GateResult

INDUSTRY_COVERAGE = 80.0
REPORT_SCHEMA_VERSION = "1.0.0"
SUPPORTED_STATUSES = (
    "pass",
    "fail",
    "warning",
    "skip",
    "not-applicable",
    "unsupported",
    "tool-error",
    "blocked",
    "cancelled",
)


@dataclass
class Recommendation:
    priority: str
    title: str
    detail: str
    command: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "priority": self.priority,
            "title": self.title,
            "detail": self.detail,
        }
        if self.command:
            payload["command"] = self.command
        return payload


@dataclass
class PerformanceSnapshot:
    coverage_line: float | None = None
    coverage_branch: float | None = None
    coverage_floor: float | None = None
    duplication_percent: float | None = None
    impact_upstream: int | None = None
    impact_downstream: int | None = None
    audit_confirmed: int | None = None
    audit_surfaces: list[str] = field(default_factory=list)
    gate_ms: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "coverage_line": self.coverage_line,
            "coverage_branch": self.coverage_branch,
            "coverage_floor": self.coverage_floor,
            "industry_coverage_floor": INDUSTRY_COVERAGE,
            "duplication_percent": self.duplication_percent,
            "impact_upstream": self.impact_upstream,
            "impact_downstream": self.impact_downstream,
            "audit_confirmed": self.audit_confirmed,
            "audit_surfaces": self.audit_surfaces,
            "gate_ms": self.gate_ms,
        }


@dataclass
class QualityDigest:
    policy: str
    results: list[GateResult]
    performance: PerformanceSnapshot
    recommendations: list[Recommendation]
    report_dir: Path | None = None

    @property
    def errors(self) -> int:
        return sum(item.error_count() for item in self.results)

    @property
    def warnings(self) -> int:
        return sum(item.warning_count() for item in self.results)

    @property
    def failed(self) -> list[str]:
        return [
            item.name
            for item in self.results
            if item.status
            in {"fail", "tool-error", "blocked", "cancelled", "unsupported"}
            or item.exit_state
            in {"failed", "unsupported", "blocked", "errored", "cancelled"}
        ]

    @property
    def verdict(self) -> str:
        return "fail" if self.failed else "pass"

    def issues(self) -> list[Finding]:
        items = [finding for result in self.results for finding in result.findings]
        rank = {"error": 0, "warning": 1, "info": 2}
        return sorted(items, key=lambda item: (rank.get(item.severity, 9), item.gate))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "policy": self.policy,
            "verdict": self.verdict,
            "failed": self.failed,
            "errors": self.errors,
            "warnings": self.warnings,
            "performance": self.performance.to_dict(),
            "recommendations": [item.to_dict() for item in self.recommendations],
            "results": [item.to_dict() for item in self.results],
            "support": {
                "statuses": list(SUPPORTED_STATUSES),
                "capability_coverage": {
                    item.name: item.status for item in self.results
                },
            },
        }


def _issues_by_gate(digest: QualityDigest) -> dict[str, list[Finding]]:
    grouped: dict[str, list[Finding]] = {}
    for finding in digest.issues():
        grouped.setdefault(finding.gate, []).append(finding)
    return grouped


def performance_bullets(
    perf: PerformanceSnapshot, results: list[GateResult]
) -> list[str]:
    bullets: list[str] = []
    if perf.coverage_line is not None:
        floor = (
            f"{perf.coverage_floor:.0f}%" if perf.coverage_floor is not None else "—"
        )
        branch = (
            f", branch {perf.coverage_branch:.1f}%"
            if perf.coverage_branch is not None
            else ""
        )
        bullets.append(
            f"- **Line coverage:** {perf.coverage_line:.1f}% (repo floor {floor}, "
            f"industry {INDUSTRY_COVERAGE:.0f}%){branch}"
        )
    elif any(item.name == "coverage" and item.status == "skip" for item in results):
        coverage = next(item for item in results if item.name == "coverage")
        why = coverage.notes[0] if coverage.notes else "skipped"
        bullets.append(f"- **Line coverage:** skipped — {why}")
    if perf.duplication_percent is not None:
        bullets.append(f"- **Duplication:** {perf.duplication_percent}% of tokens")
    if perf.impact_upstream is not None or perf.impact_downstream is not None:
        bullets.append(
            f"- **Impact:** {perf.impact_upstream or 0} upstream, "
            f"{perf.impact_downstream or 0} downstream"
        )
    elif any(item.name == "impact" and item.status == "skip" for item in results):
        impact = next(item for item in results if item.name == "impact")
        why = impact.notes[0] if impact.notes else "skipped"
        bullets.append(f"- **Impact:** skipped — {why}")
    if perf.audit_confirmed is not None or perf.audit_surfaces:
        surfaces = ", ".join(perf.audit_surfaces) or "none"
        confirmed = perf.audit_confirmed if perf.audit_confirmed is not None else 0
        bullets.append(
            f"- **Audit:** {confirmed} confirmed finding(s) · surfaces: {surfaces}"
        )
    if perf.gate_ms:
        total = sum(perf.gate_ms.values())
        slowest = max(perf.gate_ms, key=perf.gate_ms.get)
        bullets.append(
            f"- **Run time:** {_fmt_ms(total)} total · slowest `{slowest}` "
            f"({_fmt_ms(perf.gate_ms[slowest])})"
        )
    if not bullets:
        bullets.append("- No performance metrics in this run (run `quality run`).")
    return bullets


def _issue_line(finding: Finding, *, markdown: bool = True) -> str:
    loc = pointer(finding)
    rule = (
        f" `{finding.rule}`"
        if finding.rule and markdown
        else f" [{finding.rule}]"
        if finding.rule
        else ""
    )
    where = f"`{loc}` — " if loc and markdown else f"{loc}: " if loc else ""
    detail = f"[{finding.severity}] {where}{finding.message}{rule}"
    if finding.snippet:
        detail += f" At: {finding.snippet}."
    if finding.reason:
        detail += f" Why: {finding.reason}."
    if finding.suggestion:
        detail += f" Fix: {finding.suggestion}"
    if finding.verify:
        detail += f" Verify: `{finding.verify}`"
    if finding.documentation_url:
        detail += f" Docs: {finding.documentation_url}"
    return detail


def _fmt_ms(value: int) -> str:
    if value < 1000:
        return f"{value}ms"
    return f"{value / 1000:.1f}s"
