"""Merge certificate: the signal that auto-merge is safe."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quality_gates import __version__
from quality_gates.playbook import build_playbook


def build_certificate(
    payload: dict[str, Any], *, root: Path | None = None
) -> dict[str, Any]:
    """Machine-readable merge readiness. Ready only when the oracle is green."""
    playbook = payload.get("playbook") or build_playbook(payload)
    green = bool(payload.get("green"))
    review_errors = [
        item
        for item in (payload.get("review") or {}).get("findings") or []
        if isinstance(item, dict) and item.get("severity") == "error"
    ]
    comments = list(payload.get("comments") or [])
    remaining = int(playbook.get("remaining") or 0)
    ready = green and remaining == 0 and not review_errors and not comments
    snapshot = ""
    if root is not None:
        try:
            from quality_gates.evidence import snapshot_digest

            snapshot = snapshot_digest(root)
        except (OSError, ValueError, RuntimeError):
            snapshot = ""
    return {
        "ready": ready,
        "auto_merge": "ready" if ready else "blocked",
        "reason": (
            "All required gates passed, review errors are clear, and no "
            "unresolved PR threads remain."
            if ready
            else "Blocking findings, missing required results, or unresolved "
            "review threads remain."
        ),
        "version": __version__,
        "issued_at": datetime.now(UTC).isoformat(),
        "snapshot": snapshot or None,
        "blocking": [item.get("gate") for item in playbook.get("steps") or []],
        "missing_required": list(payload.get("missing_required") or []),
        "next": (playbook.get("next") or {}).get("command"),
    }


def write_certificate(root: Path, payload: dict[str, Any]) -> Path:
    certificate = payload.get("certificate")
    if not isinstance(certificate, dict):
        certificate = build_certificate(payload, root=root)
        payload["certificate"] = certificate
    directory = root / ".quality-reports"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "certificate.json"
    path.write_text(json.dumps(certificate, indent=2) + "\n", encoding="utf-8")
    (directory / "certificate.md").write_text(
        render_certificate(certificate), encoding="utf-8"
    )
    return path


def render_certificate(certificate: dict[str, Any]) -> str:
    status = "READY" if certificate.get("ready") else "BLOCKED"
    lines = [
        f"# Merge certificate: {status}",
        "",
        f"- auto_merge: `{certificate.get('auto_merge')}`",
        f"- reason: {certificate.get('reason')}",
        f"- sheriff: {certificate.get('version')}",
        f"- issued: {certificate.get('issued_at')}",
    ]
    if certificate.get("snapshot"):
        lines.append(f"- snapshot: `{certificate['snapshot']}`")
    blocking = certificate.get("blocking") or []
    if blocking:
        lines.append("- remaining gates: " + ", ".join(str(item) for item in blocking))
    if certificate.get("next") and not certificate.get("ready"):
        lines.append(f"- next: `{certificate['next']}`")
    lines.append("")
    if certificate.get("ready"):
        lines.append(
            "GitHub: enable auto-merge on the pull request. If **The Code Sheriff** "
            "is a required check, the PR can land without a human re-review of the diff."
        )
    else:
        lines.append("Do not auto-merge. Run `quality oracle --run --prompt` and fix.")
    lines.append("")
    return "\n".join(lines)
