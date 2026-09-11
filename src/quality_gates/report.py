from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quality_gates import report_html, report_render
from quality_gates.diagnostics import enrich_findings
from quality_gates.models import Finding, GateResult
from quality_gates.report_model import (
    INDUSTRY_COVERAGE,
    REPORT_SCHEMA_VERSION,
    SUPPORTED_STATUSES,
    PerformanceSnapshot,
    QualityDigest,
    Recommendation,
    performance_bullets,
)

__all__ = [
    "INDUSTRY_COVERAGE",
    "REPORT_SCHEMA_VERSION",
    "SUPPORTED_STATUSES",
    "PerformanceSnapshot",
    "QualityDigest",
    "Recommendation",
    "build_digest",
    "emit_annotations",
    "filter_new_findings",
    "load_history",
    "load_results",
    "performance_bullets",
    "render_console",
    "render_html",
    "render_junit",
    "render_markdown",
    "render_sarif",
    "write_diagnostics",
    "write_reports",
]


def emit_annotations(results: list[GateResult]) -> None:
    from quality_gates.github_annotate import (
        emit_result_annotations,
        summary_from_results,
        write_github_summary,
    )

    emit_result_annotations(results)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        write_github_summary(summary_from_results(results))


def build_digest(
    results: list[GateResult],
    *,
    policy: str = "enforce",
    report_dir: Path | None = None,
    root: Path | None = None,
) -> QualityDigest:
    if root is not None:
        for result in results:
            enrich_findings(result.findings, root)
    performance = _performance(results, report_dir)
    recs = _recommendations(results, performance, policy)
    return QualityDigest(
        policy=policy,
        results=results,
        performance=performance,
        recommendations=recs,
        report_dir=report_dir,
    )


def write_reports(
    results: list[GateResult] | QualityDigest,
    directory: Path,
    *,
    policy: str = "enforce",
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    current = directory / "quality-report.json"
    previous = directory / "quality-report.prev.json"
    if current.is_file():
        previous.write_text(current.read_text(encoding="utf-8"), encoding="utf-8")
    digest = (
        results
        if isinstance(results, QualityDigest)
        else build_digest(results, policy=policy, report_dir=directory)
    )
    path = directory / "quality-report.json"
    path.write_text(json.dumps(digest.to_dict(), indent=2) + "\n", encoding="utf-8")
    (directory / "quality-report.md").write_text(
        render_markdown(digest), encoding="utf-8"
    )
    (directory / "quality-report.html").write_text(
        render_html(digest), encoding="utf-8"
    )
    (directory / "quality-report.sarif").write_text(
        json.dumps(render_sarif(digest), indent=2) + "\n", encoding="utf-8"
    )
    (directory / "quality-report.junit.xml").write_text(
        render_junit(digest), encoding="utf-8"
    )
    _append_history(directory, digest)
    write_diagnostics(digest, directory)
    return path


def write_diagnostics(digest: QualityDigest, directory: Path) -> Path:
    """Editor-friendly problem list for VS Code / problem matchers."""
    directory.mkdir(parents=True, exist_ok=True)
    items = [
        {
            "source": f"quality.{finding.gate}",
            "severity": finding.severity,
            "path": finding.path,
            "line": finding.line or 1,
            "column": finding.column or 1,
            "message": (
                finding.message
                + (f" — {finding.suggestion}" if finding.suggestion else "")
            ),
            "rule": finding.rule,
            "reason": finding.reason,
            "suggestion": finding.suggestion,
            "verify": finding.verify,
        }
        for finding in digest.issues()
        if finding.path
    ]
    path = directory / "diagnostics.json"
    path.write_text(json.dumps({"version": 1, "diagnostics": items}, indent=2) + "\n")
    return path


def _append_history(directory: Path, digest: QualityDigest) -> None:
    path = directory / "history.json"
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
        entries = existing if isinstance(existing, list) else []
    except (OSError, json.JSONDecodeError):
        entries = []
    entries.append(
        {
            "ts": datetime.now(UTC).isoformat(),
            "verdict": digest.verdict,
            "errors": digest.errors,
            "warnings": digest.warnings,
            "coverage": digest.performance.coverage_line,
            "gate_ms": digest.performance.gate_ms,
            "failed": digest.failed,
        }
    )
    path.write_text(json.dumps(entries[-20:], indent=2) + "\n", encoding="utf-8")


def finding_key(finding: Finding) -> tuple[str, str, str, str]:
    return (
        finding.gate,
        str(finding.rule or ""),
        str(finding.path or ""),
        finding.message,
    )


def filter_new_findings(
    current: list[Finding], previous: list[Finding]
) -> list[Finding]:
    seen = {finding_key(item) for item in previous}
    return [item for item in current if finding_key(item) not in seen]


def load_history(directory: Path) -> list[dict[str, Any]]:
    path = directory / "history.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def render_sarif(results: list[GateResult] | QualityDigest) -> dict[str, Any]:
    return report_render.render_sarif(_as_digest(results))


def render_junit(results: list[GateResult] | QualityDigest) -> str:
    return report_render.render_junit(_as_digest(results))


def render_markdown(results: list[GateResult] | QualityDigest) -> str:
    return report_render.render_markdown(_as_digest(results))


def render_console(results: list[GateResult] | QualityDigest) -> str:
    return report_render.render_console(_as_digest(results))


def render_html(results: list[GateResult] | QualityDigest) -> str:
    return report_html.render_html(_as_digest(results))


def load_results(
    report_dir: Path, filename: str = "quality-report.json"
) -> tuple[list[GateResult], str]:
    path = report_dir / filename
    if not path.is_file():
        return [], "enforce"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], "enforce"
    policy = str(data.get("policy") or "enforce")
    out: list[GateResult] = []
    for row in data.get("results") or []:
        findings = [
            Finding(
                gate=str(item.get("gate") or row.get("name") or ""),
                message=str(item.get("message") or ""),
                severity=str(item.get("severity") or "error"),
                path=item.get("path"),
                line=item.get("line"),
                column=item.get("column"),
                rule=item.get("rule"),
                language=item.get("language"),
                tool=item.get("tool"),
                tool_version=item.get("tool_version"),
                raw_artifact=item.get("raw_artifact"),
                safety=item.get("safety"),
                reason=item.get("reason"),
                suggestion=item.get("suggestion"),
                documentation_url=item.get("documentation_url"),
                snippet=item.get("snippet"),
                patch=item.get("patch"),
                verify=item.get("verify"),
                confidence=item.get("confidence"),
            )
            for item in row.get("findings") or []
        ]
        duration = row.get("duration_ms")
        out.append(
            GateResult(
                name=str(row.get("name") or ""),
                status=str(row.get("status") or "pass"),
                findings=findings,
                notes=list(row.get("notes") or []),
                skipped_tools=list(row.get("skipped_tools") or []),
                duration_ms=int(duration) if isinstance(duration, int) else None,
                tool=row.get("tool"),
                tool_version=row.get("tool_version"),
                raw_artifacts=list(row.get("raw_artifacts") or []),
                safety=row.get("safety"),
                exit_state=row.get("exit_state"),
                tool_errors=list(row.get("tool_errors") or []),
                command=list(row.get("command") or []),
                working_directory=row.get("working_directory"),
                return_code=row.get("return_code"),
                output_excerpt=row.get("output_excerpt"),
                evidence=dict(row.get("evidence") or {}),
            )
        )
    return out, policy


def _as_digest(results: list[GateResult] | QualityDigest) -> QualityDigest:
    if isinstance(results, QualityDigest):
        return results
    return build_digest(results)


def _performance(
    results: list[GateResult], report_dir: Path | None
) -> PerformanceSnapshot:
    snap = PerformanceSnapshot()
    for result in results:
        if result.duration_ms is not None:
            snap.gate_ms[result.name] = result.duration_ms
        joined = "\n".join(result.notes)
        if result.name == "dry":
            match = re.search(r"duplication:\s*([0-9.]+)%", joined)
            if match:
                snap.duplication_percent = float(match.group(1))
        if result.name == "impact":
            match = re.search(
                r"([0-9]+) upstream dep\(s\), ([0-9]+) downstream", joined
            )
            if match:
                snap.impact_upstream = int(match.group(1))
                snap.impact_downstream = int(match.group(2))
        if result.name == "audit":
            match = re.search(r"confirmed findings:\s*([0-9]+)", joined)
            if match:
                snap.audit_confirmed = int(match.group(1))
            surf = re.search(r"surfaces:\s*(.+)", joined)
            if surf:
                raw = surf.group(1).strip()
                if raw and raw != "none":
                    snap.audit_surfaces = [part.strip() for part in raw.split(",")]
        if result.name == "coverage":
            match = re.search(
                r"line coverage\s+([0-9.]+)% \(floor ([0-9.]+)%\)", joined
            )
            if match:
                snap.coverage_line = float(match.group(1))
                snap.coverage_floor = float(match.group(2))
            branch = re.search(r"branch\s+([0-9.]+)%", joined)
            if branch:
                snap.coverage_branch = float(branch.group(1))
    if report_dir is not None:
        _merge_sidecars(snap, report_dir)
    return snap


def _merge_sidecars(snap: PerformanceSnapshot, report_dir: Path) -> None:
    coverage = _read_json(report_dir / "coverage.json")
    if coverage:
        if coverage.get("line_percent") is not None:
            snap.coverage_line = float(coverage["line_percent"])
        if coverage.get("branch_percent") is not None:
            snap.coverage_branch = float(coverage["branch_percent"])
        if coverage.get("line_floor") is not None:
            snap.coverage_floor = float(coverage["line_floor"])
    audit = _read_json(report_dir / "audit.json")
    if audit:
        if isinstance(audit.get("surfaces"), list):
            snap.audit_surfaces = [str(item) for item in audit["surfaces"]]
        findings = audit.get("findings")
        if isinstance(findings, list):
            snap.audit_confirmed = len(findings)
    impact = _read_json(report_dir / "impact.json")
    if impact:
        up = impact.get("upstream") or {}
        down = impact.get("downstream") or {}
        if isinstance(up, dict):
            snap.impact_upstream = sum(
                len(value) for value in up.values() if isinstance(value, list)
            )
        if isinstance(down, dict):
            snap.impact_downstream = sum(
                len(value) for value in down.values() if isinstance(value, list)
            )


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _recommendations(
    results: list[GateResult],
    perf: PerformanceSnapshot,
    policy: str,
) -> list[Recommendation]:
    recs: list[Recommendation] = []
    by_name = {item.name: item for item in results}

    def add(priority: str, title: str, detail: str, command: str | None = None) -> None:
        recs.append(
            Recommendation(
                priority=priority, title=title, detail=detail, command=command
            )
        )

    for result in results:
        if result.status != "fail":
            continue
        if result.name == "format":
            add(
                "P0",
                "Reformat the tree",
                "Format findings fail the job until the files match the project style.",
                "quality fix",
            )
        elif result.name == "lint":
            add(
                "P0",
                "Fix lint errors",
                "Lint findings are blocking. Auto-fix what you can, then resolve the rest.",
                "quality lint",
            )
        elif result.name == "dry":
            add(
                "P0",
                "Remove copy-pasted code",
                "Extract a shared helper for the duplicated blocks jscpd reported.",
                "quality dry",
            )
        elif result.name == "security":
            add(
                "P0",
                "Clear security findings before compile",
                "Secrets, CVEs, or SAST hits block compile until they are gone.",
                "quality security",
            )
        elif result.name == "compile":
            add(
                "P0",
                "Unblock compile",
                result.notes[0] if result.notes else "The compile gate failed.",
                "quality compile",
            )
        elif result.name == "impact":
            add(
                "P0",
                "Cover downstream callers",
                "Update or test every consumer of the changed files.",
                "quality impact",
            )
        elif result.name == "coverage":
            add(
                "P0",
                "Raise test coverage to the repo floor",
                result.findings[0].message
                if result.findings
                else "Coverage is below the configured floor.",
                "quality coverage",
            )
        elif result.name == "audit":
            add(
                "P0",
                "Fix HIGH-confidence audit defects",
                "P0 audit evidence fails the job. See audit.md for scenario and fix text.",
                "quality audit",
            )
        elif result.name == "ui":
            add(
                "P0",
                "Fix failing UI specs",
                "Selected Playwright/Cypress specs failed on this diff.",
                "quality ui",
            )
        elif result.name == "version":
            add(
                "P0",
                "Bump the version",
                "Source changed without a matching semver/changelog bump.",
                "quality bump auto",
            )
        else:
            add(
                "P0",
                f"Resolve {result.name} failures",
                result.findings[0].message
                if result.findings
                else f"{result.name} failed.",
                f"quality {result.name}",
            )

    for result in results:
        if result.status not in {"skip", "unsupported"}:
            continue
        if result.name == "security":
            continue
        command = (
            "quality doctor"
            if result.skipped_tools
            else f"quality {result.name}"
            if result.name in {"format", "lint", "coverage", "test"}
            else None
        )
        add(
            "P2",
            f"{result.name} skipped",
            (result.notes[0] if result.notes else f"{result.name} did not run.")
            + (
                " Next: install "
                + ", ".join(result.skipped_tools)
                + " or run quality doctor."
                if result.skipped_tools
                else " Skip means not applicable, not a pass."
            ),
            command,
        )

    security = by_name.get("security")
    if security and security.status == "skip":
        add(
            "P1",
            "Install security scanners",
            "No security scanner ran. Use doctor to see verified installation options.",
            "quality doctor",
        )
    elif security and security.skipped_tools:
        add(
            "P2",
            "Review optional security tools",
            "Skipped: "
            + ", ".join(security.skipped_tools)
            + ". Doctor reports whether verified auto-install is available.",
            "quality doctor",
        )

    if (
        perf.coverage_line is not None
        and perf.coverage_line + 0.05 < INDUSTRY_COVERAGE
        and by_name.get("coverage")
        and by_name["coverage"].status != "fail"
    ):
        add(
            "P2",
            "Move coverage toward the 80% industry floor",
            f"This repo is at {perf.coverage_line:.1f}% line coverage "
            f"(industry baseline {INDUSTRY_COVERAGE:.0f}%). Add tests for the hottest gaps.",
            "quality coverage",
        )

    coverage = by_name.get("coverage")
    if coverage and coverage.status == "skip":
        add(
            "P2",
            "Start measuring coverage",
            coverage.notes[0] if coverage.notes else "No coverage report was produced.",
            "quality coverage",
        )

    if policy == "observe":
        add(
            "P2",
            "Switch from observe to adopt when ready",
            "Observe never blocks. Commit a baseline so new issues fail.",
            'quality baseline && set policy = "adopt"',
        )

    if not recs and not any(item.status == "fail" for item in results):
        add(
            "P2",
            "Keep the suite green",
            "No blocking issues in this run. Leave pre-commit/pre-push hooks on.",
            "quality run --skip review",
        )
    return recs
