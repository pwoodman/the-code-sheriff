from __future__ import annotations

from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.gates.compile import security_cleared
from quality_gates.gates.security import run_security


def _skip_all_scanners(monkeypatch) -> None:
    def missing() -> None:
        raise OSError("not installed")

    monkeypatch.setattr("quality_gates.gates.security.ensure_gitleaks", missing)
    monkeypatch.setattr("quality_gates.gates.security.ensure_osv_scanner", missing)
    monkeypatch.setattr("quality_gates.gates.security.which", lambda *_a, **_k: None)


def test_security_skips_when_scanners_missing(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _skip_all_scanners(monkeypatch)
    result = run_security(tmp_path, QualityConfig(), ["python"])
    assert result.status == "skip"
    assert "gitleaks" in result.skipped_tools
    assert "osv-scanner" in result.skipped_tools
    assert "semgrep" in result.skipped_tools
    ok, reason = security_cleared(result)
    assert ok is False
    assert "scanner" in reason.lower() or "security" in reason.lower()


def test_security_still_reports_heuristic_secrets(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "app.py").write_text(
        "API_KEY = " + '"' + "sk_live_" + "this_is_not_a_real_key_value" + '"\n',
        encoding="utf-8",
    )
    _skip_all_scanners(monkeypatch)
    result = run_security(tmp_path, QualityConfig(), ["python"])
    assert result.status != "skip"
    assert any(item.rule == "hardcoded-secret" for item in result.findings)
