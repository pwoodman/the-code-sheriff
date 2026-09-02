from __future__ import annotations

from quality_gates.ci_plan import select_gates
from quality_gates.config import QualityConfig
from quality_gates.gates.compile import security_cleared
from quality_gates.models import Finding, GateResult


def test_local_mode_on_github_is_cheap(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("QUALITY_CI_FULL", raising=False)
    config = QualityConfig()
    assert config.ci_mode == "local"
    assert select_gates(config) == ["impact", "audit", "version", "review"]


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
