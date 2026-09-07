from __future__ import annotations

from pathlib import Path

import pytest

from quality_gates.audit.catalog import CHECK_BY_ID, CHECK_COUNT, CHECKS
from quality_gates.audit.code_quality import CODE_QUALITY_CAPABILITIES
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


def test_stub_and_unused_import_are_reported_as_warnings(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        "import json\n\ndef unfinished():\n    pass\n",
        encoding="utf-8",
    )

    result = run_audit(tmp_path, QualityConfig())

    assert result.status == "pass"
    by_rule = {item.rule: item for item in result.findings}
    assert by_rule["audit-51"].severity == "warning"
    assert by_rule["audit-57"].severity == "warning"
    assert "empty implementation body" in by_rule["audit-51"].message
    assert "never used" in by_rule["audit-57"].message


def test_unreachable_python_code_is_reported_as_a_warning(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        "def answer():\n    return 42\n    print('unreachable')\n",
        encoding="utf-8",
    )

    result = run_audit(tmp_path, QualityConfig())

    dead_code = [item for item in result.findings if item.rule == "audit-57"]
    assert len(dead_code) == 1
    assert dead_code[0].severity == "warning"
    assert dead_code[0].line == 3
    assert "unreachable" in dead_code[0].message


def test_intentional_python_interfaces_are_not_reported_as_stubs(
    tmp_path: Path,
) -> None:
    (tmp_path / "interfaces.py").write_text(
        "from abc import ABC, abstractmethod\n"
        "from typing import Protocol, overload\n\n"
        "class Service(ABC):\n"
        "    @abstractmethod\n"
        "    def run(self):\n"
        "        pass\n\n"
        "class Handler(Protocol):\n"
        "    def handle(self): ...\n\n"
        "@overload\n"
        "def parse(value: str) -> str: ...\n",
        encoding="utf-8",
    )

    result = run_audit(tmp_path, QualityConfig())

    assert "audit-51" not in {item.rule for item in result.findings}


def test_self_audit_on_repo_root_does_not_raise() -> None:
    root = Path(__file__).resolve().parents[1]
    config = load_config(root)
    result = run_audit(root, config)
    assert result.status in {"pass", "fail", "skip"}
    assert result.error_count() == 0
    ctx = load_context(root, config)
    assert "auth" not in ctx.surfaces
    assert "sql" not in ctx.surfaces
    assert "db" not in ctx.surfaces
    assert "upload" not in ctx.surfaces
    assert "http" not in ctx.surfaces
    assert not {item.rule for item in result.findings}.intersection(
        {"audit-51", "audit-57"}
    )
    outcomes, _ctx = run_audit_engine(root, config)
    assert {item.check_id: item.status for item in outcomes}[57] == "pass"


def test_lazy_imports_are_not_circular_dependencies(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        "def load():\n    from b import value\n    return value\n",
        encoding="utf-8",
    )
    (tmp_path / "b.py").write_text(
        "def load():\n    from a import load as other\n    return other\n",
        encoding="utf-8",
    )
    result = run_audit(tmp_path, QualityConfig())
    assert "audit-45" not in {item.rule for item in result.findings}


def test_module_level_import_cycle_is_reported(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("from b import value\nvalue = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("from a import value\nvalue = 1\n", encoding="utf-8")
    result = run_audit(tmp_path, QualityConfig())
    assert "audit-45" in {item.rule for item in result.findings}


@pytest.mark.parametrize(
    ("filename", "source"),
    [
        ("app.js", "function unfinished() {}\n"),
        ("app.ts", "const unfinished = () => {};\n"),
        ("App.java", "class App {\n  void unfinished() {}\n}\n"),
        ("App.cs", "class App {\n  void unfinished() {}\n}\n"),
        ("app.c", "void unfinished(void) {}\n"),
        ("app.cpp", "void unfinished() {}\n"),
        ("app.go", "func unfinished() {}\n"),
        ("app.rs", "fn unfinished() {}\n"),
        ("app.php", "<?php\nfunction unfinished() {}\n"),
        ("app.rb", "def unfinished\nend\n"),
        ("app.swift", "func unfinished() {}\n"),
        ("app.kt", "fun unfinished() {}\n"),
        ("app.dart", "void unfinished() {}\n"),
        ("app.scala", "def unfinished = {}\n"),
        ("app.lua", "function unfinished()\nend\n"),
        ("app.r", "unfinished <- function() {}\n"),
        ("app.ex", "def unfinished do\nend\n"),
        ("app.sh", "unfinished() { :; }\n"),
        ("app.ps1", "function Invoke-Unfinished {}\n"),
    ],
)
def test_narrow_multilanguage_empty_body_detectors(
    tmp_path: Path, filename: str, source: str
) -> None:
    (tmp_path / filename).write_text(source, encoding="utf-8")
    result = run_audit(tmp_path, QualityConfig())
    stubs = [item for item in result.findings if item.rule == "audit-51"]
    assert len(stubs) == 1
    assert "empty implementation body" in stubs[0].message


@pytest.mark.parametrize(
    ("filename", "source"),
    [
        ("app.js", "function f() {\n  return;\n  work();\n}\n"),
        ("app.java", "void f() {\n  return;\n  work();\n}\n"),
        ("app.go", "func f() {\n  return\n  work()\n}\n"),
        ("app.rs", "fn f() {\n  return;\n  work();\n}\n"),
    ],
)
def test_narrow_same_block_unreachable_detectors(
    tmp_path: Path, filename: str, source: str
) -> None:
    (tmp_path / filename).write_text(source, encoding="utf-8")
    result = run_audit(tmp_path, QualityConfig())
    dead = [item for item in result.findings if item.rule == "audit-57"]
    assert len(dead) == 1
    assert dead[0].line == 3


def test_code_quality_capabilities_are_explicit() -> None:
    expected = {
        "javascript",
        "typescript",
        "java",
        "csharp",
        "c",
        "cpp",
        "go",
        "rust",
        "php",
        "ruby",
        "swift",
        "kotlin",
        "dart",
        "scala",
        "lua",
        "r",
        "elixir",
        "shell",
        "powershell",
    }
    assert expected <= CODE_QUALITY_CAPABILITIES.keys()
    assert CODE_QUALITY_CAPABILITIES["ruby"]["unreachable"] == "unsupported"
