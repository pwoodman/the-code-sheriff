from __future__ import annotations

import html
import xml.etree.ElementTree as ET
from typing import Any

from quality_gates.diagnostics import detail_lines, pointer
from quality_gates.models import Finding
from quality_gates.report_model import (
    INDUSTRY_COVERAGE,
    PerformanceSnapshot,
    QualityDigest,
    _fmt_ms,
    _issue_line,
    _issues_by_gate,
    performance_bullets,
)


def render_sarif(digest: QualityDigest) -> dict[str, Any]:
    rules: dict[str, dict[str, Any]] = {}
    sarif_results: list[dict[str, Any]] = []
    for finding in digest.issues():
        rule_id = finding.rule or f"quality/{finding.gate}"
        rules.setdefault(
            rule_id,
            {
                "id": rule_id,
                "shortDescription": {"text": f"{finding.gate} finding"},
                **(
                    {"helpUri": finding.documentation_url}
                    if finding.documentation_url
                    else {}
                ),
            },
        )
        entry: dict[str, Any] = {
            "ruleId": rule_id,
            "level": "error"
            if finding.severity == "error"
            else "warning"
            if finding.severity == "warning"
            else "note",
            "message": {"text": finding.message},
            "properties": {
                key: value
                for key, value in {
                    "tool": finding.tool,
                    "reason": finding.reason,
                    "suggestion": finding.suggestion,
                    "snippet": finding.snippet,
                }.items()
                if value
            },
        }
        if finding.path:
            region: dict[str, Any] = {}
            if finding.line:
                region["startLine"] = finding.line
            if finding.column:
                region["startColumn"] = finding.column
            if finding.snippet:
                region["snippet"] = {"text": finding.snippet}
            location: dict[str, Any] = {
                "physicalLocation": {
                    "artifactLocation": {"uri": finding.path.replace("\\", "/")}
                }
            }
            if region:
                location["physicalLocation"]["region"] = region
            entry["locations"] = [location]
        sarif_results.append(entry)
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "quality-gates",
                        "informationUri": "https://github.com/pwoodman/poly-check",
                        "rules": [rules[key] for key in sorted(rules)],
                    }
                },
                "results": sarif_results,
            }
        ],
    }


def render_junit(digest: QualityDigest) -> str:
    suite = ET.Element(
        "testsuite",
        {
            "name": "quality-gates",
            "tests": str(len(digest.results)),
            "failures": str(sum(item.status == "fail" for item in digest.results)),
            "errors": str(sum(item.status == "tool-error" for item in digest.results)),
            "skipped": str(
                sum(
                    item.status in {"skip", "not-applicable", "unsupported"}
                    for item in digest.results
                )
            ),
        },
    )
    for result in digest.results:
        case = ET.SubElement(
            suite,
            "testcase",
            {"classname": "quality-gates", "name": result.name},
        )
        execution = []
        if result.command:
            execution.append("command: " + " ".join(result.command))
        if result.working_directory:
            execution.append("working directory: " + result.working_directory)
        if result.return_code is not None:
            execution.append(f"return code: {result.return_code}")
        if result.output_excerpt:
            execution.append("output:\n" + result.output_excerpt)
        text = "\n".join(
            [
                *result.notes,
                *execution,
                *(_issue_line(item, markdown=False) for item in result.findings),
            ]
        )
        if result.status == "fail":
            ET.SubElement(
                case, "failure", {"message": "quality gate failed"}
            ).text = text
        elif result.status == "tool-error":
            ET.SubElement(case, "error", {"message": "quality tool error"}).text = text
        elif result.status in {"skip", "not-applicable", "unsupported"}:
            ET.SubElement(case, "skipped", {"message": result.status}).text = text
        elif text:
            ET.SubElement(case, "system-out").text = text
    ET.indent(suite)
    return ET.tostring(suite, encoding="unicode", xml_declaration=True) + "\n"


def render_markdown(digest: QualityDigest) -> str:
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
    lines.append("## Gates")
    lines.append("")
    for result in digest.results:
        timing = _fmt_ms(result.duration_ms) if result.duration_ms is not None else ""
        extra = f" · {timing}" if timing else ""
        lines.append(f"<details{' open' if result.status == 'fail' else ''}>")
        lines.append(
            f"<summary><strong>{result.name}</strong> — {result.status.upper()} "
            f"({result.error_count()} errors, {result.warning_count()} warnings{extra})</summary>"
        )
        lines.append("")
        if result.status == "skip" and result.notes:
            lines.append(f"> Skip reason: {result.notes[0]}")
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
        lines.append("</details>")
        lines.append("")
    return "\n".join(lines) + "\n"


def render_console(digest: QualityDigest) -> str:
    width = max((len(item.name) for item in digest.results), default=8)
    passed = sum(1 for item in digest.results if item.status == "pass")
    skipped = sum(1 for item in digest.results if item.status == "skip")
    failed = len(digest.failed)
    rows = [
        f"Quality report · policy={digest.policy} · {digest.verdict.upper()}"
        f" ({digest.errors} error(s), {digest.warnings} warning(s))",
        f"  {passed} passed · {failed} failed · {skipped} skipped (skip ≠ fail)",
        "",
        "Scorecard",
    ]
    for result in digest.results:
        suffix = ""
        if result.duration_ms is not None:
            suffix = f"  {_fmt_ms(result.duration_ms)}"
        if result.status == "skip":
            rows.append(f"  {result.name:<{width}}  SKIP  {suffix}".rstrip())
            reason = result.notes[0] if result.notes else "skipped"
            rows.append(f"  {'':<{width}}    reason: {reason}")
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
    grouped = _issues_by_gate(digest)
    if not grouped:
        rows.append("  none")
    else:
        shown = 0
        for gate, findings in grouped.items():
            rows.append(f"  {gate} ({len(findings)})")
            for finding in findings:
                if shown >= 24:
                    break
                loc = pointer(finding) if finding.path or finding.rule else gate
                label = f" [{finding.rule}]" if finding.rule else ""
                tool = f" via {finding.tool}" if finding.tool else ""
                rows.append(
                    f"    {finding.severity}: {loc}{label}{tool}: {finding.message}"
                )
                for line in detail_lines(finding):
                    rows.append(f"      {line}")
                shown += 1
            if shown >= 24:
                leftover = sum(len(items) for items in grouped.values()) - shown
                if leftover > 0:
                    rows.append(f"    … {leftover} more (see quality-report.html)")
                break
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


def render_html(digest: QualityDigest) -> str:
    verdict = digest.verdict.upper()
    passed = sum(1 for item in digest.results if item.status == "pass")
    skipped = sum(1 for item in digest.results if item.status == "skip")
    failed = len(digest.failed)
    return (
        "<!DOCTYPE html>\n<html lang='en'><head><meta charset='utf-8'/>"
        f"<meta name='viewport' content='width=device-width, initial-scale=1'/>"
        f"<title>Quality report — {html.escape(verdict)}</title>"
        f"<style>{_HTML_CSS}</style></head><body>"
        f"<header class='hero {html.escape(digest.verdict)}'>"
        f"<p class='kicker'>Quality gates</p>"
        f"<h1>{html.escape(verdict)}</h1>"
        f"<p class='meta'>policy <code>{html.escape(digest.policy)}</code>"
        f" · {digest.errors} errors · {digest.warnings} warnings"
        f" · {passed} passed · {failed} failed · {skipped} skipped"
        f"<span class='hint'> (skip means not applicable, not a failure)</span></p>"
        f"</header>"
        f"<main>"
        f"{_html_scorecard(digest)}"
        f"{_html_performance(digest)}"
        f"{_html_issues(digest)}"
        f"{_html_recommendations(digest)}"
        f"{_html_gates(digest)}"
        f"</main></body></html>\n"
    )


def _html_scorecard(digest: QualityDigest) -> str:
    max_ms = (
        max((item.duration_ms or 0) for item in digest.results) if digest.results else 0
    ) or 1
    rows = []
    for result in digest.results:
        timing = _fmt_ms(result.duration_ms) if result.duration_ms is not None else "—"
        pct = 100.0 * (result.duration_ms or 0) / max_ms
        why = ""
        if result.status == "skip" and result.notes:
            why = f"<p class='why'>{html.escape(result.notes[0])}</p>"
        rows.append(
            "<tr class='"
            + html.escape(result.status)
            + "'><td><strong>"
            + html.escape(result.name)
            + "</strong>"
            + why
            + "</td><td><span class='pill "
            + html.escape(result.status)
            + "'>"
            + html.escape(result.status.upper())
            + "</span></td>"
            f"<td>{result.error_count()}</td><td>{result.warning_count()}</td>"
            "<td><div class='time'><span>"
            + html.escape(timing)
            + f"</span><span class='mini'><span style='width:{pct:.1f}%'></span>"
            "</span></div></td></tr>"
        )
    return (
        "<section class='card'><h2>Scorecard</h2>"
        "<table class='score'><thead><tr>"
        "<th>Gate</th><th>Status</th><th>Errors</th><th>Warnings</th><th>Time</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></section>"
    )


def _html_performance(digest: QualityDigest) -> str:
    perf = digest.performance
    blocks = [_coverage_meter(perf)]
    if perf.duplication_percent is not None:
        blocks.append(
            "<div class='stat'><span>Duplication</span>"
            f"<strong>{html.escape(str(perf.duplication_percent))}%</strong>"
            "<p>of tokens (jscpd)</p></div>"
        )
    if perf.impact_upstream is not None or perf.impact_downstream is not None:
        blocks.append(
            "<div class='stat'><span>Impact</span>"
            f"<strong>{perf.impact_upstream or 0} up / {perf.impact_downstream or 0} down</strong>"
            "<p>import graph around this diff</p></div>"
        )
    if perf.audit_confirmed is not None or perf.audit_surfaces:
        surfaces = ", ".join(perf.audit_surfaces) or "none"
        confirmed = perf.audit_confirmed if perf.audit_confirmed is not None else 0
        blocks.append(
            "<div class='stat'><span>Audit</span>"
            f"<strong>{confirmed} finding(s)</strong>"
            f"<p>surfaces: {html.escape(surfaces)}</p></div>"
        )
    if perf.gate_ms:
        total = sum(perf.gate_ms.values())
        slowest = max(perf.gate_ms, key=perf.gate_ms.get)  # type: ignore[arg-type]
        blocks.append(
            "<div class='stat'><span>Run time</span>"
            f"<strong>{html.escape(_fmt_ms(total))}</strong>"
            f"<p>slowest {html.escape(slowest)} "
            f"({html.escape(_fmt_ms(perf.gate_ms[slowest]))})</p></div>"
        )
    extra = "".join(
        f"<li>{html.escape(bullet.lstrip('- ').replace('**', ''))}</li>"
        for bullet in performance_bullets(perf, digest.results)
    )
    return (
        "<section class='card'><h2>Performance</h2>"
        f"<div class='stats'>{''.join(blocks)}</div>"
        f"<ul class='quiet'>{extra}</ul></section>"
    )


def _coverage_meter(perf: PerformanceSnapshot) -> str:
    if perf.coverage_line is None:
        return (
            "<div class='stat'><span>Line coverage</span>"
            "<strong>n/a</strong><p>not measured in this run</p></div>"
        )
    pct = max(0.0, min(100.0, perf.coverage_line))
    floor = (
        perf.coverage_floor if perf.coverage_floor is not None else INDUSTRY_COVERAGE
    )
    branch = (
        f" · branch {perf.coverage_branch:.1f}%"
        if perf.coverage_branch is not None
        else ""
    )
    return (
        "<div class='metric'><div class='metric-head'><span>Line coverage</span>"
        f"<strong>{pct:.1f}%</strong></div>"
        f"<div class='bar' role='img' aria-label='line coverage {pct:.1f} percent'>"
        f"<span class='fill' style='width:{pct:.1f}%'></span>"
        f"<span class='tick' style='left:{max(0.0, min(100.0, floor)):.1f}%' "
        "title='repo floor'></span>"
        f"<span class='tick industry' style='left:{INDUSTRY_COVERAGE:.1f}%' "
        "title='industry 80%'></span></div>"
        f"<p class='hint'>repo floor {floor:.0f}% · industry {INDUSTRY_COVERAGE:.0f}%"
        f"{html.escape(branch)}</p></div>"
    )


def _html_issues(digest: QualityDigest) -> str:
    grouped = _issues_by_gate(digest)
    if not grouped:
        return (
            "<section class='card'><h2>Issues</h2>"
            "<p class='empty'>No findings.</p></section>"
        )
    parts = ["<section class='card'><h2>Issues</h2>"]
    for gate, findings in grouped.items():
        open_attr = (
            " open" if any(item.severity == "error" for item in findings) else ""
        )
        items = "".join(
            "<li class='"
            + html.escape(item.severity)
            + "'>"
            + _html_finding(item)
            + "</li>"
            for item in findings[:40]
        )
        parts.append(
            f"<details class='nest'{open_attr}><summary><strong>"
            f"{html.escape(gate)}</strong> · {len(findings)}</summary>"
            f"<ul class='issues'>{items}</ul></details>"
        )
    parts.append("</section>")
    return "".join(parts)


def _html_recommendations(digest: QualityDigest) -> str:
    if not digest.recommendations:
        return (
            "<section class='card'><h2>Recommendations</h2>"
            "<p class='empty'>No further action. Keep hooks installed so this stays green.</p>"
            "</section>"
        )
    cards = []
    for item in digest.recommendations:
        cmd = (
            f"<pre><code>{html.escape(item.command)}</code></pre>"
            if item.command
            else ""
        )
        cards.append(
            "<article class='rec "
            + html.escape(item.priority.lower())
            + "'><span class='pill'>"
            + html.escape(item.priority)
            + "</span><h3>"
            + html.escape(item.title)
            + "</h3><p>"
            + html.escape(item.detail)
            + f"</p>{cmd}</article>"
        )
    return (
        "<section class='card'><h2>Recommendations</h2>"
        f"<div class='recs'>{''.join(cards)}</div></section>"
    )


def _html_gates(digest: QualityDigest) -> str:
    parts = ["<section class='card'><h2>Gate details</h2>"]
    for result in digest.results:
        open_attr = " open" if result.status == "fail" else ""
        timing = _fmt_ms(result.duration_ms) if result.duration_ms is not None else ""
        skip = ""
        if result.status == "skip" and result.notes:
            skip = (
                "<p class='why'><strong>Why skipped.</strong> "
                + html.escape(result.notes[0])
                + " Skip is not a failure.</p>"
            )
        notes = "".join(f"<li>{html.escape(note)}</li>" for note in result.notes)
        notes += "".join(
            f"<li>skipped tool <code>{html.escape(name)}</code></li>"
            for name in result.skipped_tools
        )
        findings = "".join(
            "<li class='"
            + html.escape(item.severity)
            + "'>"
            + _html_finding(item)
            + "</li>"
            for item in result.findings[:50]
        )
        body = notes + findings
        if not body:
            body = "<li>No findings.</li>"
        parts.append(
            f"<details class='nest {html.escape(result.status)}'{open_attr}>"
            f"<summary><span class='pill {html.escape(result.status)}'>"
            f"{html.escape(result.status.upper())}</span> "
            f"<strong>{html.escape(result.name)}</strong>"
            f"<span class='dim'> {html.escape(timing)} · "
            f"{result.error_count()} errors · {result.warning_count()} warnings"
            f"</span></summary>{skip}<ul>{body}</ul></details>"
        )
    parts.append("</section>")
    return "".join(parts)


_HTML_CSS = """
:root {
  --bg: #f4f1ea; --card: #fffaf3; --ink: #1c1916; --muted: #6b645c;
  --line: #e6ddd0; --pass: #1f7a4d; --fail: #b42318; --skip: #8a5a12;
  --p0: #b42318; --p1: #b54708; --p2: #175cd3; --fill: #1f7a4d;
  --hero-fail: #fbeaea; --hero-pass: #eaf6ef;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #161411; --card: #1f1b17; --ink: #f4efe7; --muted: #b0a79c;
    --line: #3a342c; --pass: #6dcc97; --fail: #ff8d80; --skip: #e2b340;
    --fill: #3d9a68; --hero-fail: #2a1614; --hero-pass: #14241b;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.5 "Segoe UI", system-ui, sans-serif;
}
.hero { padding: 2.2rem 1.5rem 1.6rem; border-bottom: 1px solid var(--line); }
.hero.pass { background: var(--hero-pass); }
.hero.fail { background: var(--hero-fail); }
.kicker { text-transform: uppercase; letter-spacing: .12em; font-size: .72rem;
  color: var(--muted); margin: 0 0 .35rem; }
h1 { font-size: 2.1rem; margin: 0 0 .35rem; letter-spacing: -.03em; }
.meta { margin: 0; color: var(--muted); }
.hint { color: var(--muted); }
main { max-width: 920px; margin: 0 auto; padding: 1.25rem 1rem 3rem; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 14px;
  padding: 1.1rem 1.2rem 1.2rem; margin: 1rem 0; box-shadow: 0 1px 0 rgba(0,0,0,.03); }
h2 { font-size: 1.05rem; margin: 0 0 .85rem; }
table.score { width: 100%; border-collapse: collapse; }
.score th, .score td { text-align: left; padding: .55rem .4rem; border-bottom: 1px solid var(--line);
  vertical-align: top; }
.score th:nth-child(n+3), .score td:nth-child(n+3) { text-align: right; }
.pill { display: inline-block; font-size: .72rem; font-weight: 700; letter-spacing: .04em;
  padding: .15rem .5rem; border-radius: 999px; background: var(--line); }
.pill.pass { color: var(--pass); background: color-mix(in srgb, var(--pass) 16%, transparent); }
.pill.fail { color: var(--fail); background: color-mix(in srgb, var(--fail) 16%, transparent); }
.pill.skip { color: var(--skip); background: color-mix(in srgb, var(--skip) 16%, transparent); }
.why, .fix, .docs { margin: .25rem 0 0; color: var(--muted); font-size: .88rem; }
.snippet { margin: .4rem 0 .2rem; padding: .4rem .65rem; background: var(--bg);
  border-radius: 8px; overflow-x: auto; font-size: .82rem; }
.time { display: flex; flex-direction: column; align-items: flex-end; gap: .25rem; }
.mini { display: block; width: 88px; height: 5px; background: var(--line); border-radius: 99px; overflow: hidden; }
.mini > span { display: block; height: 100%; background: var(--fill); }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: .75rem; }
.stat, .metric { background: color-mix(in srgb, var(--bg) 70%, var(--card));
  border: 1px solid var(--line); border-radius: 12px; padding: .8rem .9rem; }
.stat span, .metric-head span { color: var(--muted); font-size: .78rem; text-transform: uppercase;
  letter-spacing: .06em; }
.stat strong, .metric-head strong { display: block; font-size: 1.25rem; margin: .15rem 0; }
.stat p, .hint, .empty { margin: .15rem 0 0; color: var(--muted); font-size: .88rem; }
.metric-head { display: flex; justify-content: space-between; align-items: baseline; }
.bar { position: relative; height: 10px; background: var(--line); border-radius: 99px;
  margin: .55rem 0 .35rem; overflow: hidden; }
.bar .fill { display: block; height: 100%; background: var(--fill); }
.bar .tick { position: absolute; top: -3px; width: 2px; height: 16px; background: var(--ink); opacity: .45; }
.bar .tick.industry { background: var(--fail); opacity: .7; }
ul.quiet { margin: .8rem 0 0; padding-left: 1.1rem; color: var(--muted); }
.recs { display: grid; gap: .7rem; }
.rec { border: 1px solid var(--line); border-radius: 12px; padding: .85rem 1rem; }
.rec h3 { margin: .35rem 0 .25rem; font-size: 1rem; }
.rec p { margin: 0; color: var(--muted); }
.rec pre { margin: .6rem 0 0; padding: .55rem .7rem; background: var(--bg); border-radius: 8px;
  overflow: auto; }
.rec.p0 { border-color: color-mix(in srgb, var(--p0) 45%, var(--line)); }
.rec.p1 { border-color: color-mix(in srgb, var(--p1) 45%, var(--line)); }
.rec.p2 { border-color: color-mix(in srgb, var(--p2) 45%, var(--line)); }
details.nest { border: 1px solid var(--line); border-radius: 10px; padding: .2rem .8rem .4rem;
  margin: .45rem 0; }
details.nest summary { cursor: pointer; padding: .55rem 0; display: flex; gap: .55rem; align-items: baseline; flex-wrap: wrap; }
.dim { color: var(--muted); font-size: .88rem; }
ul.issues, details.nest ul { margin: 0 0 .5rem; padding-left: 1.15rem; }
li.error { color: var(--fail); font-weight: 650; }
li.warning { color: var(--skip); }
code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: .9em; }
@media print {
  body { background: #fff; color: #111; }
  .hero, .card { box-shadow: none; break-inside: avoid; }
  details.nest { border: 0; padding: 0; }
  details.nest summary { display: block; }
  details.nest > *:not(summary) { display: block !important; }
}
"""


def _html_finding(finding: Finding) -> str:
    loc = pointer(finding)
    parts = [
        f"<strong>{html.escape(finding.severity)}</strong> ",
        f"<code>{html.escape(loc)}</code> ",
        html.escape(finding.message),
    ]
    if finding.rule:
        parts.append(f" <span class='dim'>[{html.escape(finding.rule)}]</span>")
    if finding.tool:
        parts.append(f" <span class='dim'>via {html.escape(finding.tool)}</span>")
    if finding.snippet:
        parts.append(
            "<pre class='snippet'><code>"
            + html.escape(finding.snippet)
            + "</code></pre>"
        )
    if finding.reason:
        parts.append(
            "<p class='why'><strong>Why.</strong> "
            + html.escape(finding.reason)
            + "</p>"
        )
    if finding.suggestion:
        parts.append(
            "<p class='fix'><strong>Fix.</strong> "
            + html.escape(finding.suggestion)
            + "</p>"
        )
    if finding.documentation_url:
        parts.append(
            "<p class='docs'><a href='"
            + html.escape(finding.documentation_url)
            + "'>Docs</a></p>"
        )
    return "<div class='finding'>" + "".join(parts) + "</div>"
