"""Carry last-run findings so disappearing from one scan is not a silent pass."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quality_gates.models import Finding, GateResult
from quality_gates.review.parse import fingerprint

ARTIFACT = "findings-last.json"


def persist_last_findings(root: Path, results: list[GateResult]) -> dict[str, Any]:
    report = root / ".quality-reports"
    report.mkdir(parents=True, exist_ok=True)
    ran = {result.name for result in results}
    items = [
        row for row in load_last_findings(root) if str(row.get("gate") or "") not in ran
    ]
    for result in results:
        for item in result.findings:
            if item.severity not in {"error", "warning"} or item.rule == "languages":
                continue
            items.append(
                {
                    "fingerprint": fingerprint(item, bucket=1),
                    "gate": item.gate,
                    "rule": item.rule,
                    "path": item.path,
                    "line": item.line,
                    "message": item.message,
                    "severity": item.severity,
                    "snippet": item.snippet or _read_snippet(root, item),
                }
            )
    payload = {"schema_version": "1.0.0", "findings": items}
    (report / ARTIFACT).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def rotate_and_persist(root: Path, results: list[GateResult]) -> dict[str, Any]:
    report = root / ".quality-reports"
    report.mkdir(parents=True, exist_ok=True)
    current = report / ARTIFACT
    previous = report / "findings-previous.json"
    if current.is_file():
        previous.write_text(current.read_text(encoding="utf-8"), encoding="utf-8")
    return persist_last_findings(root, results)


def load_last_findings(root: Path) -> list[dict[str, Any]]:
    path = root / ".quality-reports" / ARTIFACT
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = data.get("findings") if isinstance(data, dict) else None
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    return []


def reconcile_last_findings(root: Path, results: list[GateResult]) -> list[Finding]:
    """Re-open last errors whose snippet is still in the tree."""
    previous = load_last_findings(root)
    if not previous:
        return []
    ran = {result.name: result for result in results}
    current = {
        fingerprint(item, bucket=1)
        for result in results
        for item in result.findings
        if item.rule != "languages"
    }
    leftover: list[Finding] = []
    for row in previous:
        if str(row.get("severity") or "") != "error":
            continue
        gate_name = str(row.get("gate") or "")
        if gate_name not in ran:
            continue
        key = str(row.get("fingerprint") or "")
        if key in current:
            continue
        path = str(row.get("path") or "")
        snippet = str(row.get("snippet") or "").strip()
        if not path or not snippet:
            continue
        if not _snippet_present(root, path, snippet):
            continue
        leftover.append(
            Finding(
                gate=gate_name or "review",
                rule=str(row.get("rule") or "unresolved-prior"),
                path=path,
                line=row.get("line") if isinstance(row.get("line"), int) else None,
                severity="error",
                message=f"[still present] {row.get('message')}",
                snippet=snippet,
                suggestion=(
                    f"quality ignore add --rule {row.get('rule') or '*'} "
                    f"--path {path} --reason 'accepted leftover'"
                ),
            )
        )
    by_gate: dict[str, list[Finding]] = {}
    for item in leftover:
        by_gate.setdefault(item.gate, []).append(item)
    for gate_name, items in by_gate.items():
        target = ran.get(gate_name)
        if target is None:
            continue
        target.findings.extend(items)
        if any(item.severity == "error" for item in items) and target.status != "skip":
            target.status = "fail"
        target.notes.append(
            f"{len(items)} prior finding(s) still in the tree "
            "(see .quality-reports/findings-last.json)"
        )
    return leftover


def _read_snippet(root: Path, item: Finding) -> str | None:
    if not item.path or not item.line:
        return None
    path = root / item.path
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    if item.line < 1 or item.line > len(lines):
        return None
    return lines[item.line - 1].strip()[:240] or None


def _snippet_present(root: Path, rel: str, snippet: str) -> bool:
    path = root / rel
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    needle = snippet.strip()
    return bool(needle) and needle in text
