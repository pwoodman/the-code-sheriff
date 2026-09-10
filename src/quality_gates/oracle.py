"""Agent oracle: remaining blockers until quality run is green."""

from __future__ import annotations

import json
from contextlib import suppress
from pathlib import Path
from typing import Any

from quality_gates.certificate import build_certificate, write_certificate
from quality_gates.decision import evaluate
from quality_gates.models import Finding, GateResult
from quality_gates.playbook import autofix_command, build_playbook
from quality_gates.report import load_results
from quality_gates.review.contract import agent_prompt, finding_payload, verify_command


def remaining_from_results(
    results: list[GateResult], required: list[str] | None = None
) -> dict[str, Any]:
    blocking: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for result in results:
        for item in result.findings:
            row = finding_payload(item)
            row["status"] = result.status
            command = autofix_command(row)
            if command:
                row["autofix"] = command
            if item.severity == "error" and result.status == "fail":
                blocking.append(row)
            elif item.severity in {"error", "warning"}:
                warnings.append(row)
    decision = evaluate(results, required or [item.name for item in results])
    for item in decision.blocking:
        name, state = item.split(": ", 1)
        if not any(row.get("gate") == name for row in blocking):
            blocking.append({"gate": name, "message": f"required gate {state}"})
    for name in decision.missing:
        blocking.append({"gate": name, "message": "required result is missing"})
    green = decision.approved and not blocking
    payload = {
        "green": green,
        "blocking": blocking,
        "warnings": warnings[:50],
        "gates": [
            {"name": item.name, "status": item.status, "errors": item.error_count()}
            for item in results
        ],
        "missing_required": decision.missing,
    }
    payload["playbook"] = build_playbook(payload)
    payload["certificate"] = build_certificate(payload)
    nxt = payload["playbook"]["next"]
    if green:
        payload["next"] = (
            "All blocking gates are green. Merge certificate is ready — "
            "auto-merge is safe if The Code Sheriff is a required check."
        )
    else:
        instruction = nxt.get("instruction") or "Fix the blocking findings"
        payload["next"] = f"{instruction} Then run `quality oracle --run` again."
    return payload


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
    _attach_pr_comments(root, payload)
    if not results and not payload.get("review") and not payload.get("comments"):
        payload["green"] = False
        payload["next"] = "no .quality-reports — run `quality oracle --run` first"
    payload["playbook"] = build_playbook(payload)
    payload["certificate"] = build_certificate(payload, root=root)
    if payload.get("green") and payload["certificate"].get("ready"):
        payload["next"] = (
            "All blocking gates are green. Merge certificate is ready — "
            "auto-merge is safe if The Code Sheriff is a required check."
        )
    elif not payload.get("green"):
        instruction = (payload["playbook"].get("next") or {}).get("instruction")
        if instruction and "oracle --run" not in str(payload.get("next") or ""):
            payload["next"] = f"{instruction} Then run `quality oracle --run` again."
    with suppress(OSError):
        write_certificate(root, payload)
    return payload


def finding_from_reports(root: Path, finding_id: str | None = None) -> dict[str, Any]:
    payload = remaining_from_reports(root)
    pool = list(payload.get("blocking") or []) + list(payload.get("warnings") or [])
    review = payload.get("review") or {}
    for item in review.get("findings") or []:
        if isinstance(item, dict):
            pool.append(item)
    for item in payload.get("comments") or []:
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


def _attach_pr_comments(root: Path, payload: dict[str, Any]) -> None:
    try:
        from quality_gates.config import load_config
        from quality_gates.pr_comments import (
            load_comment_findings,
            save_comments_report,
            unresolved_findings,
        )
        from quality_gates.review.contract import finding_payload

        config = load_config(root)
        if not getattr(config, "comments_in_oracle", True):
            return
        findings = unresolved_findings()
        if findings:
            save_comments_report(root, findings)
        rows = [finding_payload(item) for item in findings] or load_comment_findings(
            root
        )
        if not rows:
            return
        payload["comments"] = rows
        blocking = payload.setdefault("blocking", [])
        for row in rows:
            row = dict(row)
            row.setdefault("gate", "comments")
            row.setdefault("rule", "unresolved-review")
            if not any(
                item.get("path") == row.get("path")
                and item.get("message") == row.get("message")
                for item in blocking
            ):
                blocking.append(row)
        payload["green"] = False
        payload["next"] = (
            "Fix blocking gates and unresolved PR review comments, "
            "then run `quality oracle --run` again."
        )
    except (OSError, ValueError, json.JSONDecodeError, TypeError, KeyError):
        return


def render_prompt(payload: dict[str, Any]) -> str:
    review_errors = [
        item
        for item in (payload.get("review") or {}).get("findings") or []
        if isinstance(item, dict) and item.get("severity") == "error"
    ]
    if (
        payload.get("green")
        and not review_errors
        and not payload.get("comments")
        and (payload.get("certificate") or {}).get("ready", True)
    ):
        return (
            "Quality gates are green. Merge certificate is ready. "
            "Do not change code for gate failures. Auto-merge is safe if "
            "The Code Sheriff is a required check."
        )
    playbook = payload.get("playbook") or {}
    nxt = playbook.get("next") or {}
    lines = [
        "You are fixing a repository until `quality oracle --run` reports green.",
        "Do the next action only. Re-run the oracle after that batch. Do not nibble style.",
    ]
    if nxt.get("instruction"):
        lines.append(f"Next action: {nxt['instruction']}")
        if nxt.get("command"):
            lines.append(f"Command: `{nxt['command']}`")
    autofix_first = playbook.get("autofix_first") or []
    if autofix_first:
        lines.append("Auto-fix first (safe, no design change):")
        for step in autofix_first:
            lines.append(f"- `{step.get('command')}` ({step.get('gate')})")
    lines.append("Blocking findings:")
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
    comment_findings = payload.get("comments") or []
    if comment_findings:
        lines.append("Unresolved PR review comments:")
        for item in comment_findings[:20]:
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
    if item.get("autofix"):
        bits.append(f"  autofix: `{item['autofix']}`")
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
