"""Dead-code detection using Vulture when available."""

from __future__ import annotations

import re
from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.gates.common import fail_or_pass, skip_result, tool_or_skip
from quality_gates.models import Finding, GateResult
from quality_gates.tools import run


def run_dead(root: Path, config: QualityConfig, languages: list[str]) -> GateResult:
    if not languages:
        return skip_result("dead", "no supported languages detected")
    vulture = tool_or_skip(
        "vulture", root, config.prefer_project_tools, "dead", "python"
    )
    if isinstance(vulture, GateResult):
        return vulture
    source = root / "src"
    if not source.exists():
        return skip_result("dead", "no src/ directory found")
    result = run(
        [vulture, str(source), "--min-confidence", "80"], cwd=root, timeout=120
    )
    findings: list[Finding] = []
    for line in result.combined.splitlines():
        parsed = _parse_line(line)
        if parsed is None:
            continue
        path, location, message = parsed
        findings.append(
            Finding(
                gate="dead",
                rule="unused-code",
                path=path,
                line=location,
                message=message,
                severity="error",
            )
        )
    if result.returncode not in {0, 3} and not findings:
        findings.append(
            Finding(
                gate="dead",
                rule="execution-failed",
                message=result.combined[:500] or "vulture failed",
            )
        )
    return fail_or_pass(
        "dead",
        findings,
        [f"scanned Python code with vulture; findings: {len(findings)}"],
    )


def _parse_line(line: str) -> tuple[str, int | None, str] | None:
    text = line.strip()
    match = re.match(r"^(?P<path>.+):(?P<line>\d+):\s*(?P<message>.+)$", text)
    if match is None:
        return None
    return match.group("path"), int(match.group("line")), match.group("message")
