"""Persistent finding states; absence from one review is not proof of repair."""

from __future__ import annotations

import json
from pathlib import Path

from quality_gates.models import Finding
from quality_gates.review.parse import fingerprint


def update_ledger(root: Path, findings: list[Finding]) -> dict[str, object]:
    path = root / ".quality-reports" / "finding-ledger.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {"findings": {}}
    entries = data.setdefault("findings", {})
    current = {fingerprint(item, bucket=1): item for item in findings}
    for key, row in entries.items():
        if key not in current and row.get("state") == "open":
            row["state"] = "not-rechecked"
    for key, item in current.items():
        entries[key] = {
            "state": "open",
            "gate": item.gate,
            "rule": item.rule,
            "path": item.path,
            "line": item.line,
            "message": item.message,
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def mark_verified_fixed(root: Path, finding: Finding) -> None:
    """A finding becomes fixed only after a fresh verification run says so."""
    path = root / ".quality-reports" / "finding-ledger.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {"findings": {}}
    entries = data.setdefault("findings", {})
    key = fingerprint(finding, bucket=1)
    row = entries.setdefault(key, {})
    row["state"] = "verified-fixed"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def mark_suppressed(root: Path, finding: Finding, reason: str) -> None:
    """A finding can be suppressed only with explicit reason and tracked state."""
    path = root / ".quality-reports" / "finding-ledger.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {"findings": {}}
    entries = data.setdefault("findings", {})
    key = fingerprint(finding, bucket=1)
    row = entries.setdefault(key, {})
    row["state"] = "suppressed"
    row["suppression_reason"] = reason
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
