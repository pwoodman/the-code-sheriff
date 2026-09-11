from __future__ import annotations

from pathlib import Path

from quality_gates.gates.dead import _parse_line
from quality_gates.tools import _decode, run


def test_decode_replaces_invalid_bytes() -> None:
    assert _decode(None) == ""
    assert _decode("already text") == "already text"
    assert "\ufffd" in _decode(b"ok \xff")


def test_run_does_not_crash_on_non_utf8(tmp_path: Path, monkeypatch) -> None:
    class Fake:
        returncode = 0
        stdout = b"hello \xff world"
        stderr = b""

    monkeypatch.setattr("quality_gates.tools.subprocess.run", lambda *_a, **_k: Fake())
    result = run(["echo"], cwd=tmp_path)
    assert result.returncode == 0
    assert "hello" in result.stdout
    assert "world" in result.stdout


def test_isolated_run_fails_closed_without_bubblewrap(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("quality_gates.tools.which", lambda *_args, **_kwargs: None)

    result = run(["echo", "unsafe"], cwd=tmp_path, isolated=True)

    assert result.skipped is True
    assert result.exit_state == "isolation-unavailable"
    assert "bubblewrap" in result.skip_reason


def test_dead_code_parser_reads_vulture_locations() -> None:
    assert _parse_line("src/example.py:12: unused function 'old'") == (
        "src/example.py",
        12,
        "unused function 'old'",
    )
    assert _parse_line("no diagnostic") is None
