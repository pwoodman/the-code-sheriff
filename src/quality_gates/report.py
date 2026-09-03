from __future__ import annotations

import html
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from quality_gates.models import Finding, GateResult

INDUSTRY_COVERAGE = 80.0


@dataclass
class Recommendation:
    priority: str
    title: str
    detail: str
    command: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "priority": self.priority,
            "title": self.title,
            "detail": self.detail,
        }
        if self.command:
            payload["command"] = self.command
        return payload


@dataclass
class PerformanceSnapshot:
    coverage_line: float | None = None
    coverage_branch: float | None = None
    coverage_floor: float | None = None
    duplication_percent: float | None = None
    impact_upstream: int | None = None
    impact_downstream: int | None = None
    audit_confirmed: int | None = None
    audit_surfaces: list[str] = field(default_factory=list)
    gate_ms: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "coverage_line": self.coverage_line,
            "coverage_branch": self.coverage_branch,
            "coverage_floor": self.coverage_floor,
            "industry_coverage_floor": INDUSTRY_COVERAGE,
            "duplication_percent": self.duplication_percent,
            "impact_upstream": self.impact_upstream,
            "impact_downstream": self.impact_downstream,
            "audit_confirmed": self.audit_confirmed,
            "audit_surfaces": self.audit_surfaces,
            "gate_ms": self.gate_ms,
        }


@dataclass
class QualityDigest:
    policy: str
    results: list[GateResult]
    performance: PerformanceSnapshot
    recommendations: list[Recommendation]
    report_dir: Path | None = None

    @property
    def errors(self) -> int:
        return sum(item.error_count() for item in self.results)

    @property
    def warnings(self) -> int:
        return sum(item.warning_count() for item in self.results)

    @property
    def failed(self) -> list[str]:
        return [item.name for item in self.results if item.status == "fail"]

    @property
    def verdict(self) -> str:
        return "fail" if self.failed else "pass"

    def issues(self) -> list[Finding]:
        items = [finding for result in self.results for finding in result.findings]
        rank = {"error": 0, "warning": 1, "info": 2}
        return sorted(items, key=lambda item: (rank.get(item.severity, 9), item.gate))

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "verdict": self.verdict,
            "failed": self.failed,
            "errors": self.errors,
            "warnings": self.warnings,
            "performance": self.performance.to_dict(),
            "recommendations": [item.to_dict() for item in self.recommendations],
            "results": [item.to_dict() for item in self.results],
        }


def emit_annotations(results: list[GateResult]) -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    for result in results:
        for finding in result.findings:
            _emit(finding)


def _emit(finding: Finding) -> None:
    level = "error" if finding.severity == "error" else "warning"
    bits = [f"::{level}"]
    args: list[str] = []
    if finding.path:
        args.append(f"file={_escape_anno(finding.path)}")
    if finding.line:
        args.append(f"line={finding.line}")
    if finding.column:
        args.append(f"col={finding.column}")
    if finding.rule:
        args.append(f"title={_escape_anno(finding.rule)}")
    if args:
        bits.append(" " + ",".join(args))
    bits.append(f"::{_escape_anno(finding.message)}")
    print("".join(bits))


def _escape_anno(value: str) -> str:
    return (
        value.replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
        .replace(",", "%2C")
        .replace(":", "%3A")
    )


def build_digest(
    results: list[GateResult],
    *,
    policy: str = "enforce",
    report_dir: Path | None = None,
) -> QualityDigest:
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
    return path


def load_results(report_dir: Path) -> tuple[list[GateResult], str]:
    path = report_dir / "quality-report.json"
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
            )
        )
    return out, policy


def render_markdown(results: list[GateResult] | QualityDigest) -> str:
    digest = _as_digest(results)
    perf = digest.performance
    lines = [
        "# Quality report",
        "",
        f"**Verdict:** {digest.verdict.upper()} · **policy:** `{digest.policy}` · "
        f"**errors:** {digest.errors} · **warnings:** {digest.warnings}",
        "",
        "## Scorecard",
        "",
        "| Gate | Status | Errors | Warnings | Time |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for result in digest.results:
        timing = _fmt_ms(result.duration_ms) if result.duration_ms is not None else "—"
        lines.append(
            f"| {result.name} | {result.status.upper()} | {result.error_count()} | "
            f"{result.warning_count()} | {timing} |"
        )
    lines += ["", "## Performance", ""]
    lines.extend(performance_bullets(perf, digest.results))
    lines += ["", "## Issues", ""]
    issues = digest.issues()
    if not issues:
        lines.append("No findings.")
    else:
        for finding in issues[:80]:
            lines.append(f"- {_issue_line(finding)}")
        leftover = len(issues) - 80
        if leftover > 0:
            lines.append(f"- … {leftover} more")
    lines += ["", "## Recommendations", ""]
    if not digest.recommendations:
        lines.append("No further action. Keep hooks installed so this stays green.")
    else:
        for item in digest.recommendations:
            cmd = f" `{item.command}`" if item.command else ""
            lines.append(f"- **{item.priority} — {item.title}.** {item.detail}{cmd}")
    lines.append("")
    for result in digest.results:
        lines.append(f"## {result.name}")
        lines.append("")
        for note in result.notes:
            lines.append(f"- {note}")
        for skipped in result.skipped_tools:
            lines.append(f"- skipped `{skipped}`")
        if result.findings:
            lines.append("")
            for finding in result.findings[:50]:
                lines.append(f"- {_issue_line(finding)}")
            remaining = len(result.findings) - 50
            if remaining > 0:
                lines.append(f"- … {remaining} more")
        elif not result.notes and not result.skipped_tools:
            lines.append("No findings.")
        lines.append("")
    return "\n".join(lines) + "\n"


def render_console(results: list[GateResult] | QualityDigest) -> str:
    digest = _as_digest(results)
    width = max((len(item.name) for item in digest.results), default=8)
    rows = [
        f"Quality report · policy={digest.policy} · {digest.verdict.upper()}"
        f" ({digest.errors} error(s), {digest.warnings} warning(s))",
        "",
        "Scorecard",
    ]
    for result in digest.results:
        suffix = ""
        if result.duration_ms is not None:
            suffix = f"  {_fmt_ms(result.duration_ms)}"
        if result.status == "skip":
            extra = result.notes[0] if result.notes else "skipped"
            rows.append(
                f"  {result.name:<{width}}  {result.status.upper():<6}{suffix}  {extra}"
            )
        elif result.findings:
            rows.append(
                f"  {result.name:<{width}}  {result.status.upper():<6}{suffix}  "
                f"{result.error_count()} error(s), {result.warning_count()} warning(s)"
            )
        else:
            rows.append(f"  {result.name:<{width}}  {result.status.upper():<6}{suffix}")
    rows += ["", "Performance"]
    for bullet in performance_bullets(digest.performance, digest.results):
        rows.append("  " + bullet.lstrip("- ").replace("**", ""))
    rows += ["", "Issues"]
    issues = digest.issues()
    if not issues:
        rows.append("  none")
    else:
        for finding in issues[:20]:
            rows.append(f"  {_issue_line(finding)}")
        leftover = len(issues) - 20
        if leftover > 0:
            rows.append(f"  … {leftover} more (see quality-report.md)")
    rows += ["", "Recommendations"]
    if not digest.recommendations:
        rows.append("  none — keep hooks installed so this stays green")
    else:
        for item in digest.recommendations[:12]:
            rows.append(f"  {item.priority}  {item.title}")
            rows.append(f"         {item.detail}")
            if item.command:
                rows.append(f"         {item.command}")
    if digest.report_dir:
        rows += [
            "",
            f"Wrote {digest.report_dir.as_posix()}/quality-report.md",
            f"      {digest.report_dir.as_posix()}/quality-report.html",
        ]
    return "\n".join(rows)


def render_html(results: list[GateResult] | QualityDigest) -> str:
    digest = _as_digest(results)
    perf_items = "".join(
        f"<li>{html.escape(bullet.lstrip('- ').replace('**', ''))}</li>"
        for bullet in performance_bullets(digest.performance, digest.results)
    )
    issue_items = (
        "".join(
            f"<li class='{html.escape(finding.severity)}'>{html.escape(_issue_line(finding))}</li>"
            for finding in digest.issues()[:80]
        )
        or "<li>No findings.</li>"
    )
    rec_items = ""
    if digest.recommendations:
        for item in digest.recommendations:
            cmd = f"<code>{html.escape(item.command)}</code>" if item.command else ""
            rec_items += (
                f"<li><strong>{html.escape(item.priority)} — {html.escape(item.title)}.</strong> "
                f"{html.escape(item.detail)} {cmd}</li>"
            )
    else:
        rec_items = (
            "<li>No further action. Keep hooks installed so this stays green.</li>"
        )
    score_rows = ""
    for result in digest.results:
        timing = _fmt_ms(result.duration_ms) if result.duration_ms is not None else "—"
        score_rows += (
            f"<tr class='{html.escape(result.status)}'><td>{html.escape(result.name)}</td>"
            f"<td>{html.escape(result.status.upper())}</td>"
            f"<td>{result.error_count()}</td><td>{result.warning_count()}</td>"
            f"<td>{html.escape(timing)}</td></tr>"
        )
    gate_sections = []
    for result in digest.results:
        notes = "".join(f"<li>{html.escape(note)}</li>" for note in result.notes)
        notes += "".join(
            f"<li>skipped <code>{html.escape(name)}</code></li>"
            for name in result.skipped_tools
        )
        findings = "".join(
            f"<li>{html.escape(_issue_line(item))}</li>"
            for item in result.findings[:50]
        )
        body = notes + findings or "<li>No findings.</li>"
        gate_sections.append(
            f"<section><h2>{html.escape(result.name)}</h2><ul>{body}</ul></section>"
        )
    verdict = digest.verdict.upper()
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Quality report — {html.escape(verdict)}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 15px/1.45 system-ui, sans-serif; margin: 2rem auto; max-width: 880px;
         padding: 0 1.25rem; color: CanvasText; background: Canvas; }}
  h1 {{ font-size: 1.6rem; margin-bottom: 0.25rem; }}
  .meta {{ color: gray; margin-bottom: 1.5rem; }}
  table {{ border-collapse: collapse; width: 100%; margin: 0.75rem 0 1.5rem; }}
  th, td {{ border-bottom: 1px solid color-mix(in srgb, CanvasText 18%, transparent);
            padding: 0.4rem 0.5rem; text-align: left; }}
  td:nth-child(3), td:nth-child(4), td:nth-child(5), th:nth-child(3), th:nth-child(4), th:nth-child(5)
    {{ text-align: right; }}
  tr.fail td:nth-child(2) {{ font-weight: 700; }}
  ul {{ padding-left: 1.2rem; }}
  li.error {{ font-weight: 600; }}
  code {{ font-size: 0.92em; }}
  @media print {{
    body {{ margin: 0; max-width: none; }}
    a {{ color: inherit; text-decoration: none; }}
  }}
</style>
</head>
<body>
<h1>Quality report</h1>
<p class="meta">Verdict: <strong>{html.escape(verdict)}</strong> · policy {html.escape(digest.policy)}
 · {digest.errors} error(s) · {digest.warnings} warning(s)</p>
<h2>Scorecard</h2>
<table>
<thead><tr><th>Gate</th><th>Status</th><th>Errors</th><th>Warnings</th><th>Time</th></tr></thead>
<tbody>{score_rows}</tbody>
</table>
<h2>Performance</h2>
<ul>{perf_items}</ul>
<h2>Issues</h2>
<ul>{issue_items}</ul>
<h2>Recommendations</h2>
<ul>{rec_items}</ul>
{"".join(gate_sections)}
</body>
</html>
"""


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


def performance_bullets(
    perf: PerformanceSnapshot, results: list[GateResult]
) -> list[str]:
    bullets: list[str] = []
    if perf.coverage_line is not None:
        floor = (
            f"{perf.coverage_floor:.0f}%" if perf.coverage_floor is not None else "—"
        )
        branch = (
            f", branch {perf.coverage_branch:.1f}%"
            if perf.coverage_branch is not None
            else ""
        )
        bullets.append(
            f"- **Line coverage:** {perf.coverage_line:.1f}% (repo floor {floor}, "
            f"industry {INDUSTRY_COVERAGE:.0f}%){branch}"
        )
    elif any(item.name == "coverage" and item.status == "skip" for item in results):
        coverage = next(item for item in results if item.name == "coverage")
        why = coverage.notes[0] if coverage.notes else "skipped"
        bullets.append(f"- **Line coverage:** skipped — {why}")
    if perf.duplication_percent is not None:
        bullets.append(f"- **Duplication:** {perf.duplication_percent}% of tokens")
    if perf.impact_upstream is not None or perf.impact_downstream is not None:
        bullets.append(
            f"- **Impact:** {perf.impact_upstream or 0} upstream, "
            f"{perf.impact_downstream or 0} downstream"
        )
    elif any(item.name == "impact" and item.status == "skip" for item in results):
        impact = next(item for item in results if item.name == "impact")
        why = impact.notes[0] if impact.notes else "skipped"
        bullets.append(f"- **Impact:** skipped — {why}")
    if perf.audit_confirmed is not None or perf.audit_surfaces:
        surfaces = ", ".join(perf.audit_surfaces) or "none"
        confirmed = perf.audit_confirmed if perf.audit_confirmed is not None else 0
        bullets.append(
            f"- **Audit:** {confirmed} confirmed finding(s) · surfaces: {surfaces}"
        )
    if perf.gate_ms:
        total = sum(perf.gate_ms.values())
        slowest = max(perf.gate_ms, key=perf.gate_ms.get)
        bullets.append(
            f"- **Run time:** {_fmt_ms(total)} total · slowest `{slowest}` "
            f"({_fmt_ms(perf.gate_ms[slowest])})"
        )
    if not bullets:
        bullets.append("- No performance metrics in this run (run `quality run`).")
    return bullets


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
                "quality format --write",
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

    security = by_name.get("security")
    if security and security.status == "skip":
        add(
            "P1",
            "Install security scanners",
            "Compile stays blocked until gitleaks, osv-scanner, and/or semgrep can run.",
            "quality doctor --install",
        )
    elif security and security.skipped_tools:
        add(
            "P2",
            "Fill in skipped security tools",
            "Skipped: " + ", ".join(security.skipped_tools) + ".",
            "quality doctor --install",
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


def _issue_line(finding: Finding) -> str:
    loc = finding.path or ""
    if finding.line:
        loc = f"{loc}:{finding.line}"
    rule = f" `{finding.rule}`" if finding.rule else ""
    where = f"`{loc}` — " if loc else ""
    return f"[{finding.severity}] {where}{finding.message}{rule}"


def _fmt_ms(value: int) -> str:
    if value < 1000:
        return f"{value}ms"
    return f"{value / 1000:.1f}s"
