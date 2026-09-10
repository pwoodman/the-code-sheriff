"""Ordered fix plan so agents do the cheapest safe step first."""

from __future__ import annotations

from typing import Any

# Cheapest, safest remediations first. Format/version are machine-fixable.
_GATE_ORDER = (
    "format",
    "version",
    "lint",
    "regex",
    "packages",
    "compile",
    "test",
    "coverage",
    "security",
    "dry",
    "impact",
    "audit",
    "contract",
    "ui",
    "merge",
    "review",
    "comments",
    "migration",
    "authorization",
    "resilience",
    "mutation",
    "performance",
)

_AUTOFIX_COMMAND = {
    "format": "quality format --write",
    "version": "quality bump auto",
}

_GATE_INSTRUCTION = {
    "format": "Run `quality fix` (or `quality format --write`) — this is automatic.",
    "version": "Run `quality bump auto` and mention the version in CHANGELOG.md.",
    "lint": "Apply the suggested fix at each path:line, then `quality lint`.",
    "regex": "Remove or rewrite the unsafe API; do not `# quality:ignore` secrets.",
    "packages": "Replace the risky/undeclared import with a declared, maintained package.",
    "compile": "Fix the compile error so the tree type-checks and builds.",
    "test": "Add or fix a unit test that covers the new behavior.",
    "coverage": "Cover the uncovered changed lines until the floor is met.",
    "security": "Remove the secret/CVE/SAST hit. Do not commit credentials.",
    "dry": "Extract one shared helper for the duplicated block.",
    "impact": "Update or test every consumer the impact graph named.",
    "audit": "Fix the evidence-backed audit defect; see audit.md for the scenario.",
    "merge": "Rebase onto the base branch so `quality merge` is clean.",
    "review": "Address the review finding, then `quality review`.",
    "comments": "Apply the suggestion patch or reply and resolve the thread.",
}


def autofix_command(row: dict[str, Any]) -> str | None:
    gate = str(row.get("gate") or "")
    if gate in _AUTOFIX_COMMAND:
        return _AUTOFIX_COMMAND[gate]
    if row.get("patch") or (
        row.get("suggestion") and row.get("path") and row.get("line")
    ):
        finding_id = row.get("id")
        if finding_id:
            return f"quality apply --id {finding_id}"
    return None


def build_playbook(payload: dict[str, Any]) -> dict[str, Any]:
    """Group remaining work into an ordered, agent-executable plan."""
    rows = _blocking_rows(payload)
    steps: list[dict[str, Any]] = []
    by_gate: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_gate.setdefault(str(row.get("gate") or "review"), []).append(row)
    for gate in _GATE_ORDER:
        items = by_gate.pop(gate, [])
        if not items:
            continue
        command = _AUTOFIX_COMMAND.get(gate)
        if command is None and items:
            command = items[0].get("verify") or f"quality {gate}"
        steps.append(
            {
                "gate": gate,
                "count": len(items),
                "autofix": gate in _AUTOFIX_COMMAND,
                "command": ("quality fix" if gate == "format" else command),
                "instruction": _GATE_INSTRUCTION.get(
                    gate, f"Fix {gate} findings, then re-run `quality oracle --run`."
                ),
                "findings": [_brief(item) for item in items[:8]],
            }
        )
    extra_gates = [name for name in by_gate if by_gate[name]]
    for gate in extra_gates:
        items = by_gate[gate]
        steps.append(
            {
                "gate": gate,
                "count": len(items),
                "autofix": False,
                "command": f"quality {gate}",
                "instruction": f"Fix {gate} findings, then re-run `quality oracle --run`.",
                "findings": [_brief(item) for item in items[:8]],
            }
        )
    nxt = (
        steps[0]
        if steps
        else {
            "gate": None,
            "count": 0,
            "autofix": False,
            "command": "quality oracle --run",
            "instruction": "All blocking gates are green.",
            "findings": [],
        }
    )
    return {
        "next": nxt,
        "steps": steps,
        "autofix_first": [step for step in steps if step.get("autofix")],
        "remaining": sum(step["count"] for step in steps),
    }


def _blocking_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in payload.get("blocking") or []:
        if isinstance(item, dict):
            rows.append(item)
    for item in (payload.get("review") or {}).get("findings") or []:
        if isinstance(item, dict) and item.get("severity") == "error":
            rows.append(item)
    for item in payload.get("comments") or []:
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _brief(row: dict[str, Any]) -> dict[str, Any]:
    loc = row.get("location") or row.get("path") or "repo"
    if row.get("line") and ":" not in str(loc):
        loc = f"{loc}:{row['line']}"
    brief = {
        "id": row.get("id"),
        "gate": row.get("gate"),
        "rule": row.get("rule"),
        "location": loc,
        "message": row.get("message"),
    }
    command = autofix_command(row)
    if command:
        brief["autofix"] = command
    if row.get("suggestion"):
        brief["fix"] = row["suggestion"]
    if row.get("verify"):
        brief["verify"] = row["verify"]
    return {key: value for key, value in brief.items() if value is not None}
