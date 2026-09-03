from __future__ import annotations

from pathlib import Path

from quality_gates.cli import main
from quality_gates.gates.common import fail_or_pass, merge_results
from quality_gates.models import Finding


def test_detect_cli_json(tmp_path: Path, capsys, monkeypatch) -> None:
    (tmp_path / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    code = main(["--json", "detect"])
    assert code == 0
    out = capsys.readouterr().out
    assert "python" in out


def test_run_unknown_gate_errors(tmp_path: Path, capsys, monkeypatch) -> None:
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    code = main(["run", "--only", "not-a-gate"])
    assert code == 2
    err = capsys.readouterr().err
    assert "unknown gate" in err
    assert "not-a-gate" in err


def test_merge_results_fail_wins() -> None:
    passed = fail_or_pass("format", [])
    failed = fail_or_pass(
        "format",
        [Finding(gate="format", message="not formatted", path="a.py")],
    )
    merged = merge_results("format", [passed, failed])
    assert merged.status == "fail"
    assert merged.error_count() == 1
