from __future__ import annotations

import json
from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.gates.common import fail_or_pass, skip_result, tool_or_skip
from quality_gates.models import Finding, GateResult
from quality_gates.paths import cache_dir
from quality_gates.tools import run


def run_dry(root: Path, config: QualityConfig, languages: list[str]) -> GateResult:
    if not languages:
        return skip_result("dry", "no supported languages detected")
    jscpd = tool_or_skip("jscpd", root, config.prefer_project_tools, "dry", "multi")
    if isinstance(jscpd, GateResult):
        return jscpd
    report_dir = cache_dir() / "jscpd"
    report_dir.mkdir(parents=True, exist_ok=True)
    argv = [
        jscpd,
        "--min-lines",
        str(config.dry_min_lines),
        "--min-tokens",
        str(config.dry_min_tokens),
        "--threshold",
        str(config.dry_threshold),
        "--reporters",
        "json",
        "--output",
        str(report_dir),
        "--ignore",
        ",".join(config.dry_ignore),
        ".",
    ]
    help_text = run([jscpd, "--help"], cwd=root, timeout=15).combined
    if "--gitignore" in help_text:
        argv.insert(-1, "--gitignore")
    if "--silent" in help_text:
        argv.insert(-1, "--silent")
    result = run(argv, cwd=root, timeout=300)
    report = report_dir / "jscpd-report.json"
    findings: list[Finding] = []
    if report.is_file():
        try:
            payload = json.loads(report.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        duplicates = payload.get("duplicates") or []
        for item in duplicates:
            first = (item.get("firstFile") or {}).get("name")
            second = (item.get("secondFile") or {}).get("name")
            lines = item.get("lines")
            findings.append(
                Finding(
                    gate="dry",
                    rule="jscpd",
                    path=first,
                    line=(item.get("firstFile") or {}).get("start"),
                    message=(
                        f"duplicated {lines} lines also found in {second}. "
                        "Extract a shared helper instead of copying."
                    ),
                    severity="error" if config.dry_threshold <= 0 else "warning",
                )
            )
        stats = payload.get("statistics") or {}
        total = stats.get("total") or {}
        percentage = total.get("percentage")
        if percentage is not None:
            notes = [f"duplication: {percentage}% of tokens"]
        else:
            notes = []
        if (
            config.dry_threshold > 0
            and isinstance(percentage, (int, float))
            and percentage > config.dry_threshold
        ):
            findings.append(
                Finding(
                    gate="dry",
                    rule="jscpd-threshold",
                    message=f"duplication {percentage}% exceeds threshold {config.dry_threshold}%",
                )
            )
        return fail_or_pass("dry", findings, notes)
    if result.returncode != 0:
        return fail_or_pass(
            "dry",
            [
                Finding(
                    gate="dry",
                    message=result.combined[:500] or "jscpd failed",
                )
            ],
        )
    return fail_or_pass(
        "dry", [], ["no duplication report produced; treating as clean"]
    )
