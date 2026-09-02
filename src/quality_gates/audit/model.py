"""Audit finding model — matches the required inspection format."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class AuditFinding:
    check_id: int
    title: str
    severity: str
    priority: str
    category: str
    confidence: str
    finding: str
    why: str
    evidence: str
    scenario: str
    fix: str
    path: str | None = None
    line: int | None = None
    end_line: int | None = None
    component: str | None = None
    endpoint: str | None = None
    method: str | None = None
    effort: str = "S"
    can_auto_fix: str = "No"
    regression_test: str = "Yes"
    suggested_test: str = ""
    references: str = ""
    occurrences: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value for key, value in asdict(self).items() if value not in (None, "")
        }

    def format_text(self) -> str:
        lines = [
            f"ID: {self.check_id}",
            f"Title: {self.title}",
            f"Severity: {self.severity}",
            f"Priority: {self.priority}",
            f"Category: {self.category}",
            f"Confidence: {self.confidence}",
            "",
            f"File: {self.path or '—'}",
            f"Lines: {_lines(self.line, self.end_line)}",
            f"Component: {self.component or '—'}",
            f"Endpoint: {self.endpoint or '—'}",
            f"Method: {self.method or '—'}",
            "",
            f"Finding: {self.finding}",
            "",
            f"Why It Matters: {self.why}",
            "",
            f"Evidence: {self.evidence}",
            "",
            f"Failure / Exploit Scenario: {self.scenario}",
            "",
            f"Recommended Fix: {self.fix}",
            "",
            f"Estimated Effort: {self.effort}",
            "",
            f"Can Auto-Fix: {self.can_auto_fix}",
            "",
            f"Regression Test Required: {self.regression_test}",
            "",
            f"Suggested Test: {self.suggested_test or 'Add a regression test that fails on the evidence path.'}",
            "",
            f"References: {self.references or '—'}",
        ]
        if self.occurrences > 1:
            lines.append(f"Occurrences grouped: {self.occurrences}")
        return "\n".join(lines)


@dataclass
class CheckOutcome:
    check_id: int
    title: str
    status: str  # finding | pass | not_applicable | not_statically_provable | skipped
    findings: list[AuditFinding] = field(default_factory=list)


def _lines(start: int | None, end: int | None) -> str:
    if start is None:
        return "—"
    if end and end != start:
        return f"{start}-{end}"
    return str(start)
