from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.gates.test import run_tests
from quality_gates.models import RunResult


def test_test_gate_blocks_untrusted_execution(tmp_path: Path) -> None:
    result = run_tests(tmp_path, QualityConfig(trust="untrusted"))

    assert result.status == "blocked"


def test_test_gate_preserves_runner_failure(tmp_path: Path, monkeypatch) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_app.py").write_text("def test_nope(): pass\n", encoding="utf-8")
    monkeypatch.setattr("quality_gates.gates.test.which", lambda *_a, **_k: "pytest")
    monkeypatch.setattr(
        "quality_gates.gates.test.run",
        lambda *_a, **_k: RunResult(argv=["pytest"], returncode=1, exit_state="failed"),
    )

    result = run_tests(tmp_path, QualityConfig())

    assert result.status == "fail"
    assert result.findings[0].rule == "execution-failed"


def test_test_gate_uses_impact_selected_tests(tmp_path: Path, monkeypatch) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_app.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    reports = tmp_path / ".quality-reports"
    reports.mkdir()
    (reports / "impact.json").write_text(
        '{"tests":{"src/app.py":["tests/test_app.py"]}}', encoding="utf-8"
    )
    seen: list[list[str]] = []
    monkeypatch.setattr("quality_gates.gates.test.which", lambda *_a, **_k: "pytest")
    monkeypatch.setattr(
        "quality_gates.gates.test.run",
        lambda argv, **_k: (
            seen.append(argv)
            or RunResult(argv=argv, returncode=0, exit_state="success")
        ),
    )

    result = run_tests(tmp_path, QualityConfig())

    assert seen[0][-1] == "tests/test_app.py"
    assert any("impact-selected" in note for note in result.notes)


def test_source_without_tests_is_not_reported_as_verified(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")

    result = run_tests(tmp_path, QualityConfig())

    assert result.status == "unsupported"
    assert result.findings[0].rule == "test-readiness"
    assert "pytest" in (result.findings[0].suggestion or "")


def test_test_gate_handles_zero_tests_and_timeouts(tmp_path: Path, monkeypatch) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_app.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    monkeypatch.setattr("quality_gates.gates.test.which", lambda *_a, **_k: "pytest")
    monkeypatch.setattr(
        "quality_gates.gates.test.run",
        lambda *_a, **_k: RunResult(argv=["pytest"], returncode=5, exit_state="failed"),
    )

    result = run_tests(tmp_path, QualityConfig())

    assert result.status == "fail"
    assert any(f.rule == "zero-tests" for f in result.findings)


def test_onboarding_patch_proposal(tmp_path: Path) -> None:
    from quality_gates.gates.test import propose_onboarding_patch

    source = [tmp_path / "app.py"]
    patch = propose_onboarding_patch(tmp_path, source)
    assert "tests/test_smoke.py" in patch
    assert "def test_smoke():" in patch
