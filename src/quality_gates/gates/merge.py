"""Dry-merge preview: textual conflicts, optional sibling PRs, optional verify."""

from __future__ import annotations

import json
from pathlib import Path

from quality_gates.ci_plan import github_runs_full_suite, on_github_actions
from quality_gates.config import QualityConfig
from quality_gates.gates.common import fail_or_pass, skip_result
from quality_gates.merge_tree import (
    current_branch,
    materialize_tree,
    preview,
    remove_worktree,
    resolve_ours,
    resolve_theirs,
    same_commit,
    untracked_names,
)
from quality_gates.models import Finding, GateResult

REPORT = "merge.json"


def run_merge(
    root: Path,
    config: QualityConfig,
    *,
    base: str | None = None,
    verify: bool | None = None,
    siblings: bool | None = None,
) -> GateResult:
    if not getattr(config, "merge_enabled", True):
        return skip_result("merge", "quality.merge.enabled = false")
    theirs = resolve_theirs(root, base, getattr(config, "merge_base", "") or "")
    if not theirs:
        return skip_result(
            "merge",
            "no merge base (fetch origin/main, or pass --base)",
        )
    ours, used_stash = resolve_ours(root)
    if not ours:
        return skip_result("merge", "HEAD is unavailable")
    if same_commit(root, ours, theirs):
        return skip_result("merge", f"{ours[:12]} is already {theirs}")

    notes: list[str] = []
    findings: list[Finding] = []
    report: dict[str, object] = {
        "schema_version": "1.0.0",
        "ours": ours,
        "theirs": theirs,
        "using_working_tree_commit": used_stash,
    }
    if used_stash:
        notes.append(
            "preview includes staged/unstaged tracked files via git stash create"
        )
    extra = untracked_names(root)
    if extra:
        notes.append(f"{len(extra)} untracked file(s) are not in the merge preview")

    primary = preview(root, ours, theirs)
    primary.using_stash_commit = used_stash
    if primary.error:
        return GateResult(
            name="merge",
            status="fail",
            findings=[
                Finding(
                    gate="merge",
                    rule="merge-tree-failed",
                    message=primary.error,
                    severity="error",
                    verify=f"git fetch --prune && git merge-tree --write-tree HEAD {theirs}",
                )
            ],
            notes=notes,
        )
    report["tree"] = primary.tree
    report["clean"] = primary.clean
    report["files"] = primary.files
    report["messages"] = primary.messages
    if not primary.clean:
        findings.extend(_conflict_findings(primary, theirs, sibling=None))
        notes.append(f"textual conflict vs {theirs}: " + ", ".join(primary.files[:8]))
    else:
        notes.append(f"clean textual merge vs {theirs}")

    do_siblings = (
        getattr(config, "merge_siblings", False) if siblings is None else siblings
    )
    sibling_rows: list[dict[str, object]] = []
    if do_siblings:
        for head, label in _sibling_heads(root, ours):
            other = preview(root, ours, head)
            row = {
                "ref": head,
                "label": label,
                "clean": other.clean,
                "files": other.files,
                "error": other.error,
            }
            sibling_rows.append(row)
            if other.error:
                notes.append(f"sibling {label}: {other.error}")
                continue
            if not other.clean:
                findings.extend(_conflict_findings(other, head, sibling=label))
        notes.append(f"checked {len(sibling_rows)} open sibling PR(s)")
    report["siblings"] = sibling_rows

    do_verify = _should_verify(config, verify)
    report["verified"] = False
    if primary.clean and do_verify and primary.tree:
        verify_findings, verify_notes, verified = _verify_merged(
            root, config, primary.tree, ours, theirs
        )
        findings.extend(verify_findings)
        notes.extend(verify_notes)
        report["verified"] = verified
    elif primary.clean and not do_verify:
        notes.append("verify skipped (textual merge only)")

    _write_report(root, report)
    notes.append("wrote .quality-reports/merge.json")
    return fail_or_pass("merge", findings, notes)


def _should_verify(config: QualityConfig, override: bool | None) -> bool:
    if override is not None:
        return override
    mode = str(getattr(config, "merge_verify", "auto") or "auto").lower()
    if mode in {"always", "true", "yes", "on"}:
        return True
    if mode in {"never", "false", "no", "off"}:
        return False
    return not on_github_actions() or github_runs_full_suite(config)


def _conflict_findings(
    preview_result, theirs: str, *, sibling: str | None
) -> list[Finding]:
    findings: list[Finding] = []
    target = sibling or theirs
    rebase = f"git fetch --prune && git rebase {theirs}"
    if sibling:
        rebase = (
            f"git fetch --prune && git rebase {theirs}  "
            f"# also conflicts with open PR {sibling}"
        )
    paths = preview_result.files or ["(unknown path)"]
    for path in paths:
        kind = preview_result.kinds.get(path) or "content"
        message = (
            f"merge conflict ({kind}) vs {target}"
            if not sibling
            else f"would conflict with open PR {sibling} ({kind})"
        )
        findings.append(
            Finding(
                gate="merge",
                rule="sibling-conflict" if sibling else "textual-conflict",
                path=path if path != "(unknown path)" else None,
                message=message,
                severity="error",
                verify=rebase,
                suggestion=f"Rebase onto {theirs} and resolve {path}, then re-run quality oracle.",
            )
        )
    if not paths:
        findings.append(
            Finding(
                gate="merge",
                rule="textual-conflict",
                message=f"merge conflict vs {target}",
                severity="error",
                verify=rebase,
            )
        )
    return findings


def _verify_merged(
    root: Path,
    config: QualityConfig,
    tree: str,
    ours: str,
    theirs: str,
) -> tuple[list[Finding], list[str], bool]:
    dest = root / ".quality-gates" / "merge-preview"
    notes: list[str] = []
    findings: list[Finding] = []
    sha = materialize_tree(root, tree, ours, theirs, dest)
    if not sha:
        notes.append("could not materialize merge tree for compile/impact verify")
        return findings, notes, False
    notes.append(f"verified merge commit {sha[:12]} in .quality-gates/merge-preview")
    try:
        from quality_gates.detect import detect_languages
        from quality_gates.gates.compile import run_compile
        from quality_gates.gates.impact import run_impact
        from quality_gates.models import GateResult as GR

        languages = detect_languages(dest, config).get("languages") or []
        security = GR(name="security", status="pass")
        compile_result = run_compile(dest, config, languages, security=security)
        if compile_result.status == "fail":
            findings.append(
                Finding(
                    gate="merge",
                    rule="semantic-conflict",
                    message=(
                        f"clean Git merge vs {theirs}, but compile fails on the "
                        "merged tree — overlapping edits likely broke the build"
                    ),
                    severity="error",
                    verify=f"git fetch --prune && git rebase {theirs} && quality compile",
                )
            )
            findings.extend(
                [item for item in compile_result.findings if item.severity == "error"][
                    :8
                ]
            )
        impact_result = run_impact(dest, config, base=theirs)
        if impact_result.status == "fail":
            extra = untracked_names(root)
            hint = (
                f" {len(extra)} untracked file(s) are missing from the merge "
                "preview — `git add` new modules so merge-tree can import them."
                if extra
                else ""
            )
            findings.append(
                Finding(
                    gate="merge",
                    rule="semantic-conflict",
                    message=(
                        f"clean Git merge vs {theirs}, but impact fails on the "
                        "merged tree (broken imports or unvalidated consumers)."
                        f"{hint}"
                    ),
                    severity="error",
                    verify=f"git fetch --prune && git rebase {theirs} && quality impact",
                    suggestion=(
                        "Stage new modules with `git add`, then re-run `quality merge`."
                        if extra
                        else "Update or test every consumer the impact graph named."
                    ),
                )
            )
        if getattr(config, "merge_verify_tests", False):
            from quality_gates.gates.test import run_tests

            test_result = run_tests(dest, config)
            if test_result.status == "fail":
                findings.append(
                    Finding(
                        gate="merge",
                        rule="semantic-conflict",
                        message=f"clean Git merge vs {theirs}, but tests fail on the merged tree",
                        severity="error",
                        verify=f"git fetch --prune && git rebase {theirs} && quality test",
                    )
                )
        notes.append(f"verify compile: {compile_result.status}")
        notes.append(f"verify impact: {impact_result.status}")
    finally:
        remove_worktree(root, dest)
    return findings, notes, True


def _sibling_heads(root: Path, ours: str) -> list[tuple[str, str]]:
    from quality_gates.pr_comments import list_open_pr_heads

    return list_open_pr_heads(ours_sha=ours, branch=current_branch(root))


def _write_report(root: Path, payload: dict[str, object]) -> None:
    dest = root / ".quality-reports"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / REPORT).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
