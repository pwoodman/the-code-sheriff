"""Audit adapter for clean-code craft findings (check 48)."""

from __future__ import annotations

from quality_gates.audit.catalog import CHECK_BY_ID
from quality_gates.audit.model import AuditFinding
from quality_gates.audit.walk import FileHit, RepoContext
from quality_gates.models import Finding
from quality_gates.review.craft import python_ast_findings


def scan_craft(ctx: RepoContext) -> dict[int, list[AuditFinding]]:
    """Audit check 48: extract nested conditionals that hide a named decision."""
    grouped: dict[int, list[AuditFinding]] = {}
    check = CHECK_BY_ID[48]
    for hit in ctx.files:
        if hit.is_test or not hit.is_source or hit.path.suffix.lower() != ".py":
            continue
        for finding in python_ast_findings(hit.relative, hit.text):
            if finding.rule != "deep-nesting":
                continue
            grouped.setdefault(48, []).append(_audit_finding(check, hit, finding))
    return grouped


def _audit_finding(check, hit: FileHit, finding: Finding) -> AuditFinding:
    snippet = ""
    line = finding.line or 1
    if 1 <= line <= len(hit.lines):
        snippet = hit.lines[line - 1].strip()[:180]
    return AuditFinding(
        check_id=check.id,
        title=check.title,
        severity=check.severity,
        priority=check.priority,
        category=check.category,
        confidence="HIGH",
        finding=finding.message,
        why=finding.reason or check.why,
        evidence=f"{hit.relative}:{line}: {snippet}".rstrip(),
        scenario="A later change touches the wrong branch of a nest nobody can explain.",
        fix=finding.suggestion or check.fix,
        path=hit.relative,
        line=line,
        component=hit.relative,
        suggested_test=f"Add a unit test around {hit.relative}:{line}.",
        references=f"audit check {check.id}",
        can_auto_fix="No",
        regression_test="Yes",
        effort="S",
    )
