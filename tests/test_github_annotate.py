from __future__ import annotations

from pathlib import Path

from quality_gates.github_annotate import (
    github_annotation,
    run_ruff_github,
    summary_from_results,
    unformatted_path,
)
from quality_gates.models import Finding, GateResult
from quality_gates.report import emit_annotations


def test_annotation_pins_source_file_not_workflow() -> None:
    text = github_annotation(
        "Undefined name GateResult",
        title="F821",
        path="src/quality_gates/gates/comments.py",
        line=23,
    )
    assert text.startswith("::error ")
    assert "file=src/quality_gates/gates/comments.py" in text
    assert "line=23" in text
    assert "title=F821" in text
    assert "Undefined name GateResult" in text
    assert ".github" not in text


def test_unformatted_path_parses_ruff_format_check() -> None:
    assert unformatted_path("Would reformat: src/app.py") == "src/app.py"
    assert unformatted_path("unformatted: File would be reformatted") is None
    assert unformatted_path(" --> src/app.py:3:2") == "src/app.py"
    assert unformatted_path("6 files would be reformatted") is None
    assert unformatted_path("File would be reformatted") is None
    assert unformatted_path("warning: something") is None


def test_failed_gate_without_findings_still_annotates(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    emit_annotations(
        [GateResult(name="format", status="fail", notes=["ruff format --check failed"])]
    )
    out = capsys.readouterr().out
    assert "execution-failed" in out
    assert "ruff format --check failed" in out
    assert "format" in summary.read_text(encoding="utf-8")


def test_summary_lists_findings() -> None:
    body = summary_from_results(
        [
            GateResult(
                name="lint",
                status="fail",
                findings=[
                    Finding(
                        gate="lint",
                        rule="F821",
                        path="src/app.py",
                        line=4,
                        message="undefined name",
                    )
                ],
            )
        ]
    )
    assert "| lint | `src/app.py:4` | undefined name |" in body
    assert "Process completed" in body


def test_ruff_github_annotates_unformatted_file(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "messy.py").write_text("x=1\n", encoding="utf-8")
    code = run_ruff_github(["messy.py"])
    out = capsys.readouterr().out + capsys.readouterr().err
    assert code == 1
    assert "ruff-format" in out or "Would reformat" in out
