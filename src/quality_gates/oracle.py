"""Agent oracle: remaining blockers until quality run is green."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quality_gates.models import Finding, GateResult
from quality_gates.report import load_results
from quality_gates.review.contract import agent_prompt, finding_payload, verify_command


def remaining_from_results(results: list[GateResult]) -> dict[str, Any]:
    blocking: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for result in results:
        for item in result.findings:
            row = finding_payload(item)
            row["status"] = result.status
            if item.severity == "error" and result.status == "fail":
                blocking.append(row)
            elif item.severity in {"error", "warning"}:
                warnings.append(row)
    green = not blocking
    return {
        "green": green,
        "blocking": blocking,
        "warnings": warnings[:50],
        "gates": [
            {"name": item.name, "status": item.status, "errors": item.error_count()}
            for item in results
        ],
        "next": (
            "All blocking gates are green."
            if green
            else "Fix the blocking findings, then run `quality oracle --run` again."
        ),
    }


def remaining_from_reports(root: Path) -> dict[str, Any]:
    report_dir = root / ".quality-reports"
    results, _policy = load_results(report_dir)
    review_path = report_dir / "review.json"
    payload = remaining_from_results(results)
    if review_path.is_file():
        try:
            review = json.loads(review_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            review = None
        if isinstance(review, dict):
            payload["review"] = {
                "provider": review.get("provider"),
                "resolution": review.get("resolution"),
                "findings": review.get("findings") or [],
            }
    if not results and not payload.get("review"):
        payload["green"] = False
        payload["next"] = "no .quality-reports — run `quality oracle --run` first"
    return payload


def finding_from_reports(root: Path, finding_id: str | None = None) -> dict[str, Any]:
    payload = remaining_from_reports(root)
    pool = list(payload.get("blocking") or []) + list(payload.get("warnings") or [])
    review = payload.get("review") or {}
    for item in review.get("findings") or []:
        if isinstance(item, dict):
            pool.append(item)
    if not pool:
        return {"error": "no findings", "next": "run `quality oracle --run` first"}
    if finding_id:
        for item in pool:
            if str(item.get("id") or "") == finding_id:
                return {"finding": item, "prompt": _prompt_from_row(item)}
        return {"error": f"no finding id {finding_id}"}
    first = pool[0]
    return {"finding": first, "prompt": _prompt_from_row(first)}


def render_prompt(payload: dict[str, Any]) -> str:
    if payload.get("green") and not (payload.get("review") or {}).get("findings"):
        return "Quality gates are green. Do not change code for gate failures."
    lines = [
        "You are fixing a repository until `quality oracle --run` reports green.",
        "Do not nibble formatter/linter style beyond what the gates already failed.",
        "Blocking findings:",
    ]
    blockers = payload.get("blocking") or []
    if not blockers:
        lines.append("(no mechanical blockers)")
    for item in blockers:
        lines.append(_bullet(item))
    review_findings = (payload.get("review") or {}).get("findings") or []
    if review_findings:
        lines.append("Review findings:")
        for item in review_findings[:20]:
            if isinstance(item, dict):
                lines.append(_bullet(item))
    lines.append("Re-run `quality oracle --run` after each fix batch.")
    return "\n".join(lines)


def _bullet(item: dict[str, Any]) -> str:
    loc = item.get("location") or item.get("path") or "repo"
    if item.get("line") and ":" not in str(loc):
        loc = f"{loc}:{item['line']}"
    bits = [f"- [{item.get('gate')}/{item.get('rule')}] {loc} {item.get('message')}"]
    if item.get("snippet"):
        bits.append(f"  where: {item['snippet']}")
    if item.get("reason"):
        bits.append(f"  why: {item['reason']}")
    if item.get("suggestion"):
        bits.append(f"  fix: {item['suggestion']}")
    if item.get("verify"):
        bits.append(f"  verify: `{item['verify']}`")
    if item.get("documentation_url"):
        bits.append(f"  docs: {item['documentation_url']}")
    return "\n".join(bits)


def _prompt_from_row(item: dict[str, Any]) -> str:
    finding = Finding(
        gate=str(item.get("gate") or "review"),
        message=str(item.get("message") or ""),
        severity=str(item.get("severity") or "warning"),
        path=item.get("path"),
        line=item.get("line") if isinstance(item.get("line"), int) else None,
        rule=item.get("rule"),
        reason=item.get("reason"),
        suggestion=item.get("suggestion"),
        documentation_url=item.get("documentation_url"),
        snippet=item.get("snippet"),
        patch=item.get("patch"),
        verify=item.get("verify"),
    )
    if not finding.verify:
        finding.verify = verify_command(finding)
    return agent_prompt(finding)
