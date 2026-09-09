"""Surface unresolved GitHub review comments without failing merge by default."""

from __future__ import annotations

from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.gates.common import fail_or_pass, skip_result
from quality_gates.models import GateResult
from quality_gates.pr_comments import (
    dismissed_fingerprints,
    list_threads,
    save_comments_report,
    save_dismissed,
    unresolved_findings,
)


def run_comments(
    root: Path,
    config: QualityConfig,
    *,
    fail: bool | None = None,
) -> GateResult:
    if not getattr(config, "comments_in_oracle", True) and not getattr(
        config, "comments_fail", False
    ):
        return skip_result("comments", "quality.comments disabled")
    threads = list_threads()
    if not threads:
        from quality_gates.github_comment import _creds

        if _creds() is None:
            return skip_result(
                "comments",
                "no GitHub PR credentials (GITHUB_TOKEN + GITHUB_REPOSITORY + PR)",
            )
    dismissed = dismissed_fingerprints(threads)
    if dismissed:
        save_dismissed(root, dismissed)
    findings = unresolved_findings(threads)
    save_comments_report(root, findings)
    notes = [
        f"{len(findings)} unresolved review thread(s)",
        "wrote .quality-reports/comments.json",
    ]
    if dismissed:
        notes.append(f"recorded {len(dismissed)} dismissed fingerprint(s)")
    blocking = getattr(config, "comments_fail", False) if fail is None else fail
    if not blocking:
        for item in findings:
            item.severity = "warning"
        result = fail_or_pass("comments", findings, notes)
        if result.status == "fail":
            result.status = "pass"
        return result
    return fail_or_pass("comments", findings, notes)
