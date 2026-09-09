"""Review only new hunks on later commits of the same PR."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from quality_gates.gitutil import git_head
from quality_gates.models import Finding
from quality_gates.review.diffscan import iter_added_lines
from quality_gates.review.parse import fingerprint

STATE_NAME = "review-state.json"


def load_state(root: Path) -> dict[str, Any]:
    path = root / ".quality-reports" / STATE_NAME
    if not path.is_file():
        return {"head": None, "hunks": {}, "commented": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"head": None, "hunks": {}, "commented": []}
    return (
        data if isinstance(data, dict) else {"head": None, "hunks": {}, "commented": []}
    )


def save_state(
    root: Path,
    *,
    hunks: dict[str, list[str]],
    commented: list[str],
) -> None:
    path = root / ".quality-reports" / STATE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0.0",
        "head": git_head(root),
        "hunks": hunks,
        "commented": sorted(set(commented)),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def added_hunks(diff: str) -> dict[str, list[str]]:
    """Map path → stable keys for newly added lines."""
    out: dict[str, list[str]] = {}
    for path, new_line, text in iter_added_lines(diff):
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        out.setdefault(path, []).append(f"{new_line}:{digest}")
    return out


def new_hunks(
    current: dict[str, list[str]], previous: dict[str, list[str]]
) -> dict[str, list[str]]:
    fresh: dict[str, list[str]] = {}
    for path, keys in current.items():
        known = set(previous.get(path) or [])
        added = [item for item in keys if item not in known]
        if added:
            fresh[path] = added
    return fresh


def restrict_diff(diff: str, paths: set[str]) -> str:
    from quality_gates.review.context import split_diff_files

    if not paths:
        return ""
    parts: list[str] = []
    for path, body in split_diff_files(diff):
        if path in paths:
            parts.append(body if "diff --git" in body[:40] else f"+++ b/{path}\n{body}")
    return "\n".join(parts)


def unposted_findings(findings: list[Finding], commented: list[str]) -> list[Finding]:
    known = set(commented)
    return [
        item
        for item in findings
        if fingerprint(item, bucket=1) not in known and item.rule != "languages"
    ]
