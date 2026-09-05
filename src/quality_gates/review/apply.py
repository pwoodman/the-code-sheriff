"""Apply a finding patch and confirm the fingerprint disappeared."""

from __future__ import annotations

from pathlib import Path

from quality_gates.models import Finding
from quality_gates.review.context import safe_repo_path
from quality_gates.review.parse import fingerprint


def apply_finding(root: Path, finding: Finding) -> str:
    """Apply `finding.patch` to the working tree. Returns a status string."""
    patch = (finding.patch or "").strip()
    if not patch:
        return "no patch on this finding"
    if "```suggestion" in patch or not _looks_unified(patch):
        return _apply_line_replacement(root, finding, patch)
    return _apply_unified(root, patch)


def apply_and_check(
    root: Path,
    finding: Finding,
    remaining: list[Finding],
) -> dict[str, object]:
    status = apply_finding(root, finding)
    gone = fingerprint(finding, bucket=1) not in {
        fingerprint(item, bucket=1) for item in remaining
    }
    return {
        "status": status,
        "fingerprint": fingerprint(finding, bucket=1),
        "resolved": gone and status.startswith("applied"),
        "verify": finding.verify or f"quality {finding.gate}",
        "next": (
            f"Re-run `{finding.verify or 'quality ' + finding.gate}` to confirm."
            if status.startswith("applied")
            else status
        ),
    }


def _looks_unified(patch: str) -> bool:
    return patch.startswith(("diff ", "--- ", "@@")) or "\n@@" in patch


def _replacement_body(patch: str) -> str:
    if "```suggestion" in patch:
        rest = patch.split("```suggestion", 1)[-1]
        rest = rest.lstrip("\n")
        end = rest.find("```")
        return rest[:end] if end >= 0 else rest
    if _looks_unified(patch):
        added = [
            line[1:]
            for line in patch.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        ]
        return "\n".join(added)
    return patch


def _apply_line_replacement(root: Path, finding: Finding, patch: str) -> str:
    if not finding.path or not finding.line:
        return "patch needs path and line"
    path = safe_repo_path(root, finding.path)
    if path is None:
        return f"path not in repo: {finding.path}"
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    index = finding.line - 1
    if index < 0 or index >= len(lines):
        return "line out of range"
    body = _replacement_body(patch)
    replacement = body.splitlines()
    ending = "\n" if lines[index].endswith("\n") else ""
    if not replacement:
        lines.pop(index)
    else:
        lines[index] = replacement[0] + (
            ending if not replacement[0].endswith("\n") else ""
        )
        extra = replacement[1:]
        for offset, row in enumerate(extra, start=1):
            lines.insert(index + offset, row + ("" if row.endswith("\n") else "\n"))
    path.write_text("".join(lines), encoding="utf-8")
    return f"applied line replacement at {finding.path}:{finding.line}"


def _apply_unified(root: Path, patch: str) -> str:
    current: str | None = None
    old: list[str] = []
    new: list[str] = []
    applied = 0
    for raw in patch.splitlines():
        if raw.startswith("+++ b/"):
            if current and (old or new):
                applied += _write_hunk(root, current, old, new)
            current = raw[6:].strip()
            old, new = [], []
            continue
        if raw.startswith("@@"):
            if current and (old or new):
                applied += _write_hunk(root, current, old, new)
            old, new = [], []
            continue
        if current is None:
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            new.append(raw[1:])
        elif raw.startswith("-") and not raw.startswith("---"):
            old.append(raw[1:])
        elif raw.startswith(" "):
            old.append(raw[1:])
            new.append(raw[1:])
    if current and (old or new):
        applied += _write_hunk(root, current, old, new)
    if applied:
        return f"applied unified diff ({applied} file(s))"
    return "unified diff did not match"


def _write_hunk(root: Path, rel: str, old: list[str], new: list[str]) -> int:
    path = safe_repo_path(root, rel)
    if path is None:
        return 0
    text = path.read_text(encoding="utf-8")
    old_block = "\n".join(old)
    new_block = "\n".join(new)
    if old_block and old_block not in text.replace("\r\n", "\n"):
        return 0
    updated = text.replace("\r\n", "\n")
    if old_block:
        updated = updated.replace(old_block, new_block, 1)
    elif new_block and new_block not in updated:
        updated = new_block + "\n" + updated
    path.write_text(updated, encoding="utf-8")
    return 1
