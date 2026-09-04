from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from quality_gates.diagnostics import detail_lines, pointer
from quality_gates.report_model import (
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
