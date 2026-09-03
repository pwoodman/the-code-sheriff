"""Write audit.json and audit.md in the required finding format."""

from __future__ import annotations

import json
from pathlib import Path

from quality_gates.audit.model import AuditFinding, CheckOutcome
from quality_gates.audit.walk import RepoContext

CONF_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}


def write_audit_reports(
    report_dir: Path,
    outcomes: list[CheckOutcome],
    ctx: RepoContext,
    *,
    min_confidence: str,
) -> tuple[Path, Path, list[AuditFinding]]:
    report_dir.mkdir(parents=True, exist_ok=True)
    confirmed: list[AuditFinding] = []
    potential: list[AuditFinding] = []
    counts = {
        "finding": 0,
        "pass": 0,
        "not_applicable": 0,
        "not_statically_provable": 0,
        "skipped": 0,
    }
    for outcome in outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
        for item in outcome.findings:
            if item.confidence == "LOW":
                continue
            if CONF_RANK.get(item.confidence, 0) >= CONF_RANK.get(min_confidence, 3):
                confirmed.append(item)
            else:
                potential.append(item)

    payload = {
        "schema_version": "1.0.0",
        "surfaces": sorted(ctx.surfaces),
        "counts": counts,
        "min_confidence": min_confidence,
        "checks": [
            {
                "id": row.check_id,
                "title": row.title,
                "status": row.status,
                "finding_count": len(row.findings),
            }
            for row in outcomes
        ],
        "findings": [item.to_dict() for item in confirmed],
        "potential_risks": [item.to_dict() for item in potential],
    }
    json_path = report_dir / "audit.json"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    md_path = report_dir / "audit.md"
    md_path.write_text(
        _markdown(outcomes, confirmed, potential, ctx, counts), encoding="utf-8"
    )
    return json_path, md_path, confirmed


def _markdown(
    outcomes: list[CheckOutcome],
    confirmed: list[AuditFinding],
    potential: list[AuditFinding],
    ctx: RepoContext,
    counts: dict[str, int],
) -> str:
    lines = [
        "# 120-point repository audit",
        "",
        f"Surfaces detected: {', '.join(sorted(ctx.surfaces)) or '(none)'}",
        "",
        "| Status | Count |",
        "| --- | ---: |",
        f"| Confirmed findings (grouped) | {len(confirmed)} |",
        f"| Checks with findings | {counts.get('finding', 0)} |",
        f"| Pass (scanned, no evidence) | {counts.get('pass', 0)} |",
        f"| Not applicable | {counts.get('not_applicable', 0)} |",
        f"| Not statically provable | {counts.get('not_statically_provable', 0)} |",
        f"| Skipped | {counts.get('skipped', 0)} |",
        "",
        "Only HIGH-confidence evidence is treated as a defect. Runtime UX, LCP, and",
        "exploit attempts are out of scope for this static gate.",
        "",
    ]
    if not confirmed:
        lines += ["No confirmed defects.", ""]
    else:
        lines.append("## Confirmed findings")
        lines.append("")
        for item in confirmed:
            lines.append("```text")
            lines.append(item.format_text())
            lines.append("```")
            lines.append("")
    if potential:
        lines.append("## Potential risks (below confidence floor)")
        lines.append("")
        for item in potential:
            lines.append(f"- Check {item.check_id} {item.title}: {item.evidence}")
        lines.append("")
    lines.append("## Check index")
    lines.append("")
    lines.append("| ID | Status | Title |")
    lines.append("| ---: | --- | --- |")
    for row in outcomes:
        lines.append(f"| {row.check_id} | {row.status} | {row.title} |")
    lines.append("")
    return "\n".join(lines)
