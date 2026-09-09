from __future__ import annotations

import pytest

from quality_gates.ci_plan import (
    CHEAP_GITHUB_GATES,
    HEAVY_GATES,
    select_gates,
    unknown_gates,
)
from quality_gates.config import QualityConfig
from quality_gates.gates.compile import run_compile, security_cleared
from quality_gates.models import Finding, GateResult, RunResult


def _recording_runner(calls: list[list[str]]):
    def run(argv, **_kwargs):
        calls.append(list(argv))
        return RunResult(argv=list(argv), returncode=0)

    return run


def test_local_mode_on_github_is_cheap(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("QUALITY_CI_FULL", raising=False)
    config = QualityConfig()
    assert config.ci_mode == "local"
    assert select_gates(config) == list(config.ci_github_gates)
    assert "regex" in config.ci_github_gates
    assert "format" in CHEAP_GITHUB_GATES
    assert "lint" in CHEAP_GITHUB_GATES
    assert "regex" in CHEAP_GITHUB_GATES
    assert "packages" in CHEAP_GITHUB_GATES
    assert "security" in CHEAP_GITHUB_GATES
    assert "format" not in HEAVY_GATES
    assert "lint" not in HEAVY_GATES


def test_both_or_full_flag_runs_heavy_gates(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    config = QualityConfig(ci_mode="both")
    gates = select_gates(config)
    assert "security" in gates
    assert "compile" in gates
    assert "format" in gates


def test_compile_blocked_when_security_failed() -> None:
    failed = GateResult(
        name="security",
        status="fail",
        findings=[Finding(gate="security", message="CVE-1")],
    )
    ok, reason = security_cleared(failed)
    assert ok is False
    assert "vulnerabilit" in reason or "security" in reason


def test_compile_blocked_when_security_skipped() -> None:
    skipped = GateResult(name="security", status="skip", notes=["no scanners"])
    ok, _reason = security_cleared(skipped)
    assert ok is False


def test_compile_allowed_when_security_passed() -> None:
    passed = GateResult(name="security", status="pass")
    ok, _reason = security_cleared(passed)
    assert ok is True


def test_unknown_only_gates_are_rejected() -> None:
    assert unknown_gates(["audit", "nope"]) == ["nope"]
    with pytest.raises(ValueError, match="unknown gate"):
        select_gates(QualityConfig(), only=["not-a-gate"])


def test_ui_stays_in_full_local_plan(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    config = QualityConfig()
    gates = select_gates(config)
    assert gates.index("compile") < gates.index("impact") < gates.index("ui")
    assert "impact" in gates
    assert "ui" in gates
    assert "coverage" in gates
    assert "audit" in gates
    assert (
        gates.index("impact")
        < gates.index("coverage")
        < gates.index("audit")
        < gates.index("ui")
    )


@pytest.mark.parametrize(
    ("language", "filename", "expected"),
    [
        ("swift", "demo.swift", "-parse"),
        ("scala", "demo.scala", "-Ystop-after:parser"),
        ("shell", "demo.sh", "-n"),
        ("r", "demo.r", "parse(file=commandArgs(trailingOnly=TRUE)[1]"),
    ],
)
def test_untrusted_syntax_checks_never_execute_project_code(
    tmp_path, monkeypatch, language: str, filename: str, expected: str
) -> None:
    (tmp_path / filename).write_text("placeholder\n", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "quality_gates.gates.compile.which",
        lambda name, **_kwargs: f"/tools/{name}",
    )

    monkeypatch.setattr("quality_gates.gates.compile.run", _recording_runner(calls))
    result = run_compile(
        tmp_path,
        QualityConfig(trust="untrusted"),
        [language],
        security=GateResult(name="security", status="skip"),
    )
    assert result.status == "pass"
    assert len(calls) == 1
    assert any(expected in argument for argument in calls[0])


def test_kotlin_compiles_only_to_temporary_output_when_trusted(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "demo.kt"
    source.write_text("fun answer() = 42\n", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "quality_gates.gates.compile.which",
        lambda name, **_kwargs: f"/tools/{name}",
    )

    monkeypatch.setattr("quality_gates.gates.compile.run", _recording_runner(calls))
    trusted = run_compile(
        tmp_path,
        QualityConfig(trust="trusted"),
        ["kotlin"],
        security=GateResult(name="security", status="pass"),
    )
    assert trusted.status == "pass"
    assert calls[0][0] == "/tools/kotlinc"
    assert "-d" in calls[0]
    assert str(source) in calls[0]

    calls.clear()
    untrusted = run_compile(
        tmp_path,
        QualityConfig(trust="untrusted"),
        ["kotlin"],
        security=GateResult(name="security", status="skip"),
    )
    assert untrusted.status == "skip"
    assert not calls
