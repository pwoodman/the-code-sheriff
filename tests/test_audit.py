from __future__ import annotations

from pathlib import Path

from quality_gates.audit.catalog import CHECK_BY_ID, CHECK_COUNT, CHECKS
from quality_gates.audit.engine import run_audit_engine
from quality_gates.audit.patterns import _JWT_NONE, _SYNC_LONG, scan_patterns
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
        "API_KEY = " + '"' + "sk_live_" + "this_is_not_a_real_key_value" + '"\n',
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


def test_weak_needles_do_not_invent_surfaces(tmp_path: Path) -> None:
    (tmp_path / "cli.py").write_text(
        'select = "changed"\nimport zipfile\npassword = "example"\nsession = {}\n',
        encoding="utf-8",
    )
    ctx = load_context(tmp_path, QualityConfig())
    assert "sql" not in ctx.surfaces
    assert "db" not in ctx.surfaces
    assert "upload" not in ctx.surfaces
    assert "auth" not in ctx.surfaces


def test_sqlalchemy_still_marks_db(tmp_path: Path) -> None:
    (tmp_path / "db.py").write_text(
        "from sqlalchemy import create_engine\n", encoding="utf-8"
    )
    ctx = load_context(tmp_path, QualityConfig())
    assert "sql" in ctx.surfaces
    assert "db" in ctx.surfaces


def test_jwt_decode_with_algorithms_is_not_flagged() -> None:
    good = "payload = jwt.decode(token, key, algorithms=['HS256'])"
    assert _JWT_NONE.search(good) is None
    assert _JWT_NONE.search("jwt.decode(token, key, verify=False)")
    assert _JWT_NONE.search("jwt.decode(token, key, algorithms=['none'])")


def test_sync_long_requires_word_boundary() -> None:
    assert _SYNC_LONG.search("def _chat_anthropic(prompt):") is None
    assert _SYNC_LONG.search("result = anthropic(prompt)")


def test_check_68_is_runtime_not_false_pass(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        "from fastapi import FastAPI\n"
        "from sqlalchemy import create_engine\n"
        "app = FastAPI()\n",
        encoding="utf-8",
    )
    assert CHECK_BY_ID[68].detector == "runtime"
    outcomes, ctx = run_audit_engine(tmp_path, QualityConfig())
    assert "http" in ctx.surfaces
    assert "db" in ctx.surfaces
    by_id = {row.check_id: row for row in outcomes}
    assert by_id[68].status == "not_statically_provable"


def test_self_audit_on_repo_root_does_not_raise() -> None:
    root = Path(__file__).resolve().parents[1]
    config = load_config(root)
    result = run_audit(root, config)
    assert result.status in {"pass", "fail", "skip"}
    ctx = load_context(root, config)
    assert "auth" not in ctx.surfaces
    assert "sql" not in ctx.surfaces
    assert "db" not in ctx.surfaces
    assert "upload" not in ctx.surfaces
    assert "http" not in ctx.surfaces
