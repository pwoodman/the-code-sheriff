from __future__ import annotations

import json
from pathlib import Path

from quality_gates.gates.common import (
    execution_details,
    fail_or_pass,
    findings_from_text,
    merge_results,
)
from quality_gates.models import Finding, GateResult, RunResult
from quality_gates.report import (
    load_results,
    render_console,
    render_html,
    render_junit,
    render_sarif,
)


def test_parsable_tool_output_has_location_reason_snippet_and_fix(
    tmp_path: Path,
) -> None:
    source = tmp_path / "config.yml"
    source.write_text("name: demo\non: [push]\n", encoding="utf-8")
    result = RunResult(
        argv=["yamllint", "--format", "parsable", "config.yml"],
        returncode=1,
        stdout="config.yml:2:1: [warning] truthy value (truthy)\n",
        tool="yamllint",
        exit_state="failed",
        cwd=str(tmp_path),
    )

    finding = findings_from_text("lint", result, root=tmp_path)[0]

    assert finding.path == "config.yml"
    assert finding.line == 2
    assert finding.column == 1
    assert finding.rule == "truthy"
    assert finding.severity == "warning"
    assert finding.message == "truthy value"
    assert finding.snippet == "2 | on: [push]"
    assert "booleans" in (finding.reason or "")
    assert '"on":' in (finding.suggestion or "")
    assert finding.documentation_url
    assert "yamllint.readthedocs.io" in finding.documentation_url


def test_successful_tool_chatter_is_not_turned_into_errors() -> None:
    result = RunResult(
        argv=["yamllint", "config.yml"],
        returncode=0,
        stdout="checked 1 file\n",
        tool="yamllint",
    )

    assert findings_from_text("lint", result) == []


def test_execution_details_include_redacted_command_context(tmp_path: Path) -> None:
    result = RunResult(
        argv=["tool", "--token=secret-value"],
        returncode=2,
        stderr="api_key=secret-value failed",
        tool="tool",
        exit_state="failed",
        cwd=str(tmp_path),
    )

    details = execution_details(result)

    assert details["command"] == ["tool", "--token=<redacted>"]
    assert details["working_directory"] == str(tmp_path)
    assert details["return_code"] == 2
    assert details["output_excerpt"] == "api_key=<redacted> failed"


def test_merge_results_keeps_failing_command_context() -> None:
    passed = fail_or_pass("lint", [])
    failed = GateResult(
        name="lint",
        status="fail",
        findings=[Finding(gate="lint", message="bad yaml", path="a.yml", line=1)],
        command=["yamllint", "a.yml"],
        working_directory="/tmp/demo",
        return_code=1,
        output_excerpt="a.yml:1:1: [error] bad",
    )

    merged = merge_results("lint", [passed, failed])

    assert merged.status == "fail"
    assert merged.command == ["yamllint", "a.yml"]
    assert merged.working_directory == "/tmp/demo"
    assert merged.return_code == 1
    assert merged.output_excerpt == "a.yml:1:1: [error] bad"


def test_warnings_do_not_fail_the_gate() -> None:
    result = fail_or_pass(
        "lint",
        [Finding(gate="lint", message="truthy", severity="warning", rule="truthy")],
    )
    assert result.status == "pass"


def test_diagnostics_survive_all_report_formats(tmp_path: Path) -> None:
    source = tmp_path / "config.yml"
    source.write_text("root:\n   nested: true\n", encoding="utf-8")
    run = RunResult(
        argv=["yamllint", "config.yml"],
        returncode=1,
        stdout="config.yml:2:4: [error] bad indentation (indentation)\n",
        tool="yamllint",
        exit_state="failed",
        cwd=str(tmp_path),
    )
    result = GateResult(
        name="lint",
        status="fail",
        findings=findings_from_text("lint", run, root=tmp_path),
        **execution_details(run),
    )

    console = render_console([result])
    assert "config.yml:2:4 [indentation] via yamllint" in console
    assert "where: 2 |    nested: true" in console
    assert "why: The YAML indentation" in console
    assert "fix: Re-indent with two spaces" in console
    assert "docs: https://yamllint.readthedocs.io" in console

    html = render_html([result])
    assert "Why." in html
    assert "Fix." in html
    assert "nested: true" in html

    sarif = render_sarif([result])
    entry = sarif["runs"][0]["results"][0]
    assert entry["locations"][0]["physicalLocation"]["region"]["startColumn"] == 4
    assert entry["locations"][0]["physicalLocation"]["region"]["snippet"]["text"]
    assert entry["properties"]["tool"] == "yamllint"
    assert entry["properties"]["suggestion"]

    junit = render_junit([result])
    assert "command: yamllint config.yml" in junit
    assert "return code: 1" in junit

    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "quality-report.json").write_text(
        json.dumps(
            {
                "policy": "enforce",
                "results": [result.to_dict()],
            }
        ),
        encoding="utf-8",
    )
    loaded, _ = load_results(report_dir)
    assert loaded[0].command == ["yamllint", "config.yml"]
    assert loaded[0].findings[0].suggestion
    assert loaded[0].findings[0].snippet
