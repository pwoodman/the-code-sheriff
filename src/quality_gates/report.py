from __future__ import annotations

import json
import os
from pathlib import Path

from quality_gates.models import Finding, GateResult


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
        args.append(f"file={_escape(finding.path)}")
    if finding.line:
        args.append(f"line={finding.line}")
    if finding.column:
        args.append(f"col={finding.column}")
    if finding.rule:
        args.append(f"title={_escape(finding.rule)}")
    if args:
        bits.append(" " + ",".join(args))
    bits.append(f"::{_escape(finding.message)}")
    print("".join(bits))


def _escape(value: str) -> str:
    return (
        value.replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
        .replace(",", "%2C")
        .replace(":", "%3A")
    )


def write_reports(results: list[GateResult], directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "results": [item.to_dict() for item in results],
        "failed": [item.name for item in results if item.status == "fail"],
    }
    path = directory / "quality-report.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    markdown = directory / "quality-report.md"
    markdown.write_text(render_markdown(results), encoding="utf-8")
    return path


def render_markdown(results: list[GateResult]) -> str:
    lines = ["# Quality gates", ""]
    lines.append("| Gate | Status | Errors | Warnings |")
    lines.append("| --- | --- | ---: | ---: |")
    for result in results:
        lines.append(
            f"| {result.name} | {result.status.upper()} | "
            f"{result.error_count()} | {result.warning_count()} |"
        )
    lines.append("")
    for result in results:
        lines.append(f"## {result.name}")
        lines.append("")
        for note in result.notes:
            lines.append(f"- {note}")
        for skipped in result.skipped_tools:
            lines.append(f"- skipped `{skipped}`")
        if result.findings:
            lines.append("")
            for finding in result.findings[:50]:
                loc = finding.path or ""
                if finding.line:
                    loc = f"{loc}:{finding.line}"
                rule = f" `{finding.rule}`" if finding.rule else ""
                where = f"`{loc}` — " if loc else ""
                lines.append(f"- [{finding.severity}] {where}{finding.message}{rule}")
            remaining = len(result.findings) - 50
            if remaining > 0:
                lines.append(f"- … {remaining} more")
        elif not result.notes and not result.skipped_tools:
            lines.append("No findings.")
        lines.append("")
    return "\n".join(lines) + "\n"


def render_console(results: list[GateResult]) -> str:
    rows = []
    width = max((len(item.name) for item in results), default=8)
    for result in results:
        suffix = ""
        if result.status == "skip":
            suffix = "  " + (result.notes[0] if result.notes else "skipped")
        elif result.findings:
            suffix = f"  {result.error_count()} error(s), {result.warning_count()} warning(s)"
        rows.append(f"  {result.name:<{width}}  {result.status.upper():<6}{suffix}")
        for finding in result.findings[:12]:
            loc = finding.path or finding.rule or result.name
            if finding.line:
                loc = f"{loc}:{finding.line}"
            rows.append(f"      {finding.severity}: {loc}: {finding.message}")
        leftover = len(result.findings) - 12
        if leftover > 0:
            rows.append(f"      … {leftover} more")
    return "\n".join(rows)
