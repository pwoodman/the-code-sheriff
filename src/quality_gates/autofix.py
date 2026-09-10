"""Safe automatic remediations: format, ruff --fix, and finding patches."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from quality_gates.config import QualityConfig, load_config
from quality_gates.detect import detect_languages
from quality_gates.gates.format import run_format
from quality_gates.models import Finding
from quality_gates.review.apply import apply_finding
from quality_gates.tools import which


def run_autofix(
    root: Path,
    config: QualityConfig | None = None,
    *,
    apply_patches: bool = True,
) -> dict[str, Any]:
    """Apply only remediations that cannot change program meaning unexpectedly."""
    config = config or load_config(root)
    languages = detect_languages(root, config).get("languages") or []
    applied: list[str] = []
    format_result = run_format(root, config, list(languages), check=False)
    applied.append(
        f"format:{format_result.status}:{len(format_result.findings)} remaining"
    )
    ruff_note = _ruff_fix(root, config)
    if ruff_note:
        applied.append(ruff_note)
    patch_notes: list[str] = []
    if apply_patches:
        patch_notes = _apply_report_patches(root)
        applied.extend(patch_notes)
    return {
        "applied": applied,
        "format_status": format_result.status,
        "patches": patch_notes,
        "next": "quality oracle --run",
    }


def _ruff_fix(root: Path, config: QualityConfig) -> str | None:
    ruff = which("ruff", project=root, prefer_project=config.prefer_project_tools)
    if not ruff:
        return None
    from quality_gates.tools import run

    result = run([ruff, "check", "--fix", "--quiet", "."], cwd=root, timeout=120)
    if result.returncode not in {0, 1}:
        return f"ruff-fix:exit {result.returncode}"
    return "ruff-fix:applied"


def _apply_report_patches(root: Path) -> list[str]:
    from quality_gates.oracle import remaining_from_reports

    payload = remaining_from_reports(root)
    notes: list[str] = []
    seen: set[str] = set()
    for row in list(payload.get("blocking") or []) + list(
        payload.get("warnings") or []
    ):
        if not isinstance(row, dict):
            continue
        key = str(row.get("id") or row.get("path") or "")
        if key in seen:
            continue
        seen.add(key)
        if not (row.get("patch") or row.get("suggestion")):
            continue
        finding = Finding(
            gate=str(row.get("gate") or "review"),
            message=str(row.get("message") or ""),
            path=row.get("path"),
            line=row.get("line") if isinstance(row.get("line"), int) else None,
            rule=row.get("rule"),
            patch=row.get("patch"),
            suggestion=row.get("suggestion"),
        )
        status = apply_finding(root, finding)
        notes.append(f"{key}:{status}")
    return notes
