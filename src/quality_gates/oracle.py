"""Agent oracle: remaining blockers until quality run is green."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quality_gates.models import Finding, GateResult
from quality_gates.report import load_results


def remaining_from_results(results: list[GateResult]) -> dict[str, Any]:
    blocking: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for result in results:
        for item in result.findings:
            row = _row(item, result.name, result.status)
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


def render_prompt(payload: dict[str, Any]) -> str:
    if payload.get("green"):
        return "Quality gates are green. Do not change code for gate failures."
    lines = [
        "You are fixing a repository until `quality oracle --run` reports green.",
        "Do not nibble formatter/linter style beyond what the gates already failed.",
        "Blocking findings:",
    ]
    for item in payload.get("blocking") or []:
        loc = item.get("path") or "repo"
        if item.get("line"):
            loc = f"{loc}:{item['line']}"
        lines.append(
            f"- [{item.get('gate')}/{item.get('rule')}] {loc} {item.get('message')}"
        )
    lines.append("Re-run `quality oracle --run` after each fix batch.")
    return "\n".join(lines)


def _row(item: Finding, gate: str, status: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "gate": gate,
        "status": status,
        "severity": item.severity,
        "rule": item.rule,
        "message": item.message,
        "path": item.path,
        "line": item.line,
    }
    return {key: value for key, value in row.items() if value is not None}
