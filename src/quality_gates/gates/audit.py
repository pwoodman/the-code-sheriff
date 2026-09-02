"""120-point static inspection gate."""

from __future__ import annotations

from pathlib import Path

from quality_gates.audit.engine import run_audit_engine
from quality_gates.audit.model import AuditFinding
from quality_gates.audit.report import write_audit_reports
from quality_gates.config import QualityConfig
from quality_gates.gates.common import fail_or_pass, skip_result
from quality_gates.models import Finding, GateResult


def run_audit(root: Path, config: QualityConfig) -> GateResult:
    if not config.audit_enabled:
        return skip_result("audit", "audit gate disabled in quality.toml")

    outcomes, ctx = run_audit_engine(root, config)
    _json, _md, confirmed = write_audit_reports(
        root / ".quality-reports",
        outcomes,
        ctx,
        min_confidence=config.audit_min_confidence,
    )

    fail_prios = {item.upper() for item in config.audit_fail_on_priority}
    gate_findings: list[Finding] = []
    errors = 0
    for item in confirmed:
        blocking = item.priority in fail_prios
        if blocking:
            errors += 1
        gate_findings.append(_to_finding(item, blocking))

    notes = [
        f"surfaces: {', '.join(sorted(ctx.surfaces)) or 'none'}",
        f"120 checks · fail on {', '.join(sorted(fail_prios)) or '(none)'} · "
        f"min confidence {config.audit_min_confidence}",
        f"confirmed findings: {len(confirmed)} ({errors} at fail priority)",
        "wrote .quality-reports/audit.json and audit.md",
    ]
    counts = _count_status(outcomes)
    notes.append(
        "status: "
        + ", ".join(f"{name}={count}" for name, count in counts.items() if count)
    )
    return fail_or_pass("audit", gate_findings, notes)


def _to_finding(item: AuditFinding, blocking: bool) -> Finding:
    return Finding(
        gate="audit",
        message=f"[{item.priority} {item.confidence}] {item.check_id} {item.title}: {item.finding}",
        severity="error" if blocking else "warning",
        path=item.path,
        line=item.line,
        rule=f"audit-{item.check_id}",
    )


def _count_status(outcomes) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in outcomes:
        counts[row.status] = counts.get(row.status, 0) + 1
    return counts
