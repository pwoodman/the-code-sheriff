from __future__ import annotations

import json
import os
from pathlib import Path

from quality_gates.change_manifest import ChangeManifest
from quality_gates.ci_plan import on_github_actions, ui_allowed_on_github
from quality_gates.config import QualityConfig
from quality_gates.gates.common import fail_or_pass, findings_from_text, skip_result
from quality_gates.gitutil import git_base_ref, git_changed_names
from quality_gates.impact_graph import expand_downstream
from quality_gates.models import Finding, GateResult
from quality_gates.tools import run, which
from quality_gates.ui_select import (
    Selection,
    detect_ui_project,
    select_specs,
    spec_kind,
)

UI_TIMEOUT = 1800


def run_ui(
    root: Path,
    config: QualityConfig,
    *,
    base: str | None = None,
    compile_result: GateResult | None = None,
    force_all: bool = False,
    list_only: bool = False,
    manifest: ChangeManifest | None = None,
) -> GateResult:
    if manifest is not None and manifest.state == "unknown":
        return GateResult(
            name="ui",
            status="blocked",
            exit_state="blocked",
            notes=[manifest.reason or "change discovery failed"],
        )
    if on_github_actions() and not ui_allowed_on_github(config):
        return skip_result(
            "ui",
            "UI tests stay off GitHub Actions by default (browser install). "
            "Set [quality.ui] on_github = true or QUALITY_UI_ON_GITHUB=1",
        )

    if compile_result is not None and compile_result.status == "fail":
        return skip_result(
            "ui",
            "skipped: compile failed — fix the build before running UI tests",
        )

    project = detect_ui_project(root, config.ui_framework)
    if project is None:
        return skip_result(
            "ui",
            "no Playwright or Cypress project (playwright.config.*, cypress.config.*, "
            "or those packages in package.json)",
        )

    force_all = force_all or os.environ.get("QUALITY_UI_ALL", "").lower() in {
        "1",
        "true",
        "yes",
    }
    changed = (
        manifest.paths
        if manifest is not None
        else git_changed_names(root, git_base_ref(base))
    )
    original = list(changed or [])
    if changed:
        changed = expand_downstream(root, config, changed)
    selection = select_specs(root, config, project, changed, force_all=force_all)
    _write_selection(root, project.framework, selection)

    if not selection.specs:
        reason = selection.notes[0] if selection.notes else "no matching UI specs"
        return skip_result("ui", reason)

    notes = list(selection.notes)
    if changed and original and len(changed) > len(set(original)):
        notes.insert(
            0,
            f"impact: {len(changed) - len(set(original))} downstream file(s) added to UI selection",
        )
    if selection.run_all:
        notes.insert(0, f"running all specs: {selection.run_all_reason}")
    for spec in selection.specs:
        why = selection.reasons.get(str(spec)) or []
        rel = _rel_to(root, spec)
        if why:
            notes.append(f"{rel}: {'; '.join(why)}")
        else:
            notes.append(rel)

    if list_only:
        return GateResult(name="ui", status="pass", notes=notes)

    pw_specs = [path for path in selection.specs if spec_kind(path) != "cypress"]
    cy_specs = [path for path in selection.specs if spec_kind(path) == "cypress"]
    if project.framework == "playwright":
        pw_specs = list(selection.specs)
        cy_specs = []
    elif project.framework == "cypress":
        cy_specs = list(selection.specs)
        pw_specs = []

    parts: list[GateResult] = []
    if pw_specs:
        parts.append(_run_playwright(root, project.root, pw_specs, notes))
    if cy_specs:
        parts.append(_run_cypress(root, project.root, cy_specs, notes))
    if not parts:
        return skip_result("ui", "selected specs but no runner matched")

    findings: list[Finding] = []
    merged_notes = list(notes)
    skipped: list[str] = []
    saw_fail = False
    saw_pass = False
    for part in parts:
        findings.extend(part.findings)
        for note in part.notes:
            if note not in merged_notes:
                merged_notes.append(note)
        skipped.extend(part.skipped_tools)
        if part.status == "fail":
            saw_fail = True
        elif part.status == "pass":
            saw_pass = True
        elif part.status == "skip" and not saw_fail and not saw_pass:
            pass
    if saw_fail:
        status = "fail"
    elif saw_pass:
        status = "pass"
    else:
        return skip_result(
            "ui", merged_notes[0] if merged_notes else "UI runner skipped"
        )
    return GateResult(
        name="ui",
        status=status,
        findings=findings,
        notes=merged_notes,
        skipped_tools=skipped,
    )


def _run_playwright(
    root: Path, cwd: Path, specs: list[Path], notes: list[str]
) -> GateResult:
    argv = _playwright_argv(root, cwd, specs)
    if argv is None:
        return skip_result(
            "ui",
            "Playwright is not installed — npm i -D @playwright/test && npx playwright install",
            tool="playwright",
        )
    result = run(argv, cwd=cwd, timeout=UI_TIMEOUT)
    extra = [f"ran: {' '.join(argv)}"]
    if result.skipped:
        return skip_result(
            "ui", result.skip_reason or "playwright skipped", tool="playwright"
        )
    findings = findings_from_text(
        "ui",
        result,
        language="javascript",
        default_message="Playwright tests failed",
    )
    if result.returncode != 0:
        findings = [item for item in findings if not _noise(item.message)] or findings
        for item in findings:
            item.severity = "error"
    else:
        findings = []
    return fail_or_pass("ui", findings, notes + extra)


def _run_cypress(
    root: Path, cwd: Path, specs: list[Path], notes: list[str]
) -> GateResult:
    argv = _cypress_argv(root, cwd, specs)
    if argv is None:
        return skip_result(
            "ui",
            "Cypress is not installed — npm i -D cypress",
            tool="cypress",
        )
    result = run(argv, cwd=cwd, timeout=UI_TIMEOUT)
    extra = [f"ran: {' '.join(argv)}"]
    if result.skipped:
        return skip_result(
            "ui", result.skip_reason or "cypress skipped", tool="cypress"
        )
    findings = findings_from_text(
        "ui",
        result,
        language="javascript",
        default_message="Cypress tests failed",
    )
    if result.returncode != 0:
        findings = [item for item in findings if not _noise(item.message)] or findings
        for item in findings:
            item.severity = "error"
    else:
        findings = []
    return fail_or_pass("ui", findings, notes + extra)


def _playwright_argv(root: Path, cwd: Path, specs: list[Path]) -> list[str] | None:
    rels = [_rel_to(cwd, path) for path in specs]
    binary = which("playwright", project=root) or which("playwright", project=cwd)
    if binary:
        return [binary, "test", "--reporter=list", *rels]
    npx = which("npx", project=root) or which("npx", project=cwd)
    if not npx:
        return None
    return [npx, "playwright", "test", "--reporter=list", *rels]


def _cypress_argv(root: Path, cwd: Path, specs: list[Path]) -> list[str] | None:
    rels = [_rel_to(cwd, path) for path in specs]
    binary = which("cypress", project=root) or which("cypress", project=cwd)
    spec_arg = ",".join(rels)
    if binary:
        return [binary, "run", "--spec", spec_arg]
    npx = which("npx", project=root) or which("npx", project=cwd)
    if not npx:
        return None
    return [npx, "cypress", "run", "--spec", spec_arg]


def _write_selection(root: Path, framework: str, selection: Selection) -> None:
    out_dir = root / ".quality-reports"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "framework": framework,
            "run_all": selection.run_all,
            "run_all_reason": selection.run_all_reason,
            "specs": [_rel_to(root, path) for path in selection.specs],
            "notes": selection.notes,
        }
        (out_dir / "ui-selection.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
    except OSError:
        return


def _rel_to(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _noise(message: str) -> bool:
    lower = message.lower()
    if lower.startswith("running ") or lower.startswith("ok "):
        return True
    if "slow test" in lower:
        return True
    return "passed" in lower and "failed" not in lower
