from __future__ import annotations

from pathlib import Path

from quality_gates.audit.catalog import CHECK_COUNT, CHECKS
from quality_gates.audit.patterns import scan_patterns
from quality_gates.audit.walk import load_context
from quality_gates.config import QualityConfig, load_config
from quality_gates.gates.audit import run_audit


def test_catalog_is_exactly_120() -> None:
    assert CHECK_COUNT == 120
    assert [item.id for item in CHECKS] == list(range(1, 121))
    assert CHECKS[0].priority == "P0"
    assert CHECKS[3].title == "Hardcoded Secrets"


def test_python_cli_marks_http_checks_na(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "core.py").write_text(
        "VALUE = 1\n\ndef add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    result = run_audit(tmp_path, QualityConfig())
    assert result.status in {"pass", "fail"}
    report = tmp_path / ".quality-reports" / "audit.json"
    assert report.is_file()
    text = report.read_text(encoding="utf-8")
    assert '"id": 1' in text
    assert "not_applicable" in text
    # No HTTP surface → missing server-side auth is N/A, not a fail.
    assert result.error_count() == 0


def test_hardcoded_secret_is_p0(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        'API_KEY = "sk_live_this_is_not_a_real_key_value"\n',
        encoding="utf-8",
    )
    result = run_audit(tmp_path, QualityConfig())
    assert result.status == "fail"
    rules = {item.rule for item in result.findings}
    assert "audit-4" in rules


def test_open_api_route_is_p0(tmp_path: Path) -> None:
    (tmp_path / "api.py").write_text(
        """
from fastapi import FastAPI

app = FastAPI()

@app.delete("/orders/{order_id}")
def delete_order(order_id: str):
    return {"ok": True}
""",
        encoding="utf-8",
    )
    result = run_audit(tmp_path, QualityConfig())
    assert result.status == "fail"
    ids = {item.rule for item in result.findings if item.severity == "error"}
    assert "audit-1" in ids or "audit-2" in ids or "audit-105" in ids


def test_detector_help_text_is_not_xss(tmp_path: Path) -> None:
    (tmp_path / "rules.py").write_text(
        'HINT = "dangerouslySetInnerHTML bypasses React XSS protections"\n',
        encoding="utf-8",
    )
    result = run_audit(tmp_path, QualityConfig())
    assert "audit-8" not in {item.rule for item in result.findings}


def test_audit_config_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    assert config.audit_fail_on_priority == ["P0"]
    assert config.audit_min_confidence == "HIGH"
    assert "audit" in config.fail_on
    assert "audit" in config.ci_github_gates


def test_python_only_repo_has_no_http_surface(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    ctx = load_context(tmp_path, QualityConfig())
    assert "http" not in ctx.surfaces
    assert "frontend" not in ctx.surfaces
    assert 4 not in scan_patterns(ctx)
