"""Resolution rate: which previous review findings disappeared."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quality_gates.models import Finding
from quality_gates.review.parse import fingerprint


def rotate_previous(report_dir: Path) -> dict[str, Any] | None:
    current = report_dir / "review.json"
    previous_path = report_dir / "review-previous.json"
    payload = _load(current)
    if payload:
        previous_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    elif previous_path.is_file():
        payload = _load(previous_path)
    return payload


def resolution_stats(
    previous: dict[str, Any] | None, findings: list[Finding]
) -> dict[str, Any]:
    prev_items = _findings(previous)
    prev_fps = {fingerprint(item, bucket=1) for item in prev_items}
    curr_fps = {
        fingerprint(item, bucket=1) for item in findings if item.rule != "languages"
    }
    if not prev_fps:
        return {
            "previous": 0,
            "resolved": 0,
            "remaining": len(curr_fps),
            "new": len(curr_fps),
            "rate": None,
        }
    resolved = prev_fps - curr_fps
    remaining = prev_fps & curr_fps
    new = curr_fps - prev_fps
    return {
        "previous": len(prev_fps),
        "resolved": len(resolved),
        "remaining": len(remaining),
        "new": len(new),
        "rate": round(len(resolved) / len(prev_fps), 4),
    }


def _load(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _findings(payload: dict[str, Any] | None) -> list[Finding]:
    if not payload:
        return []
    raw = payload.get("findings") or []
    if not isinstance(raw, list):
        return []
    out: list[Finding] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append(
            Finding(
                gate="review",
                severity=str(item.get("severity") or "warning"),
                path=str(item.get("path") or "") or None,
                line=item.get("line") if isinstance(item.get("line"), int) else None,
                rule=str(item.get("rule") or "logic"),
                message=str(item.get("message") or ""),
            )
        )
    return out
