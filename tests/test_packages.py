from __future__ import annotations

from pathlib import Path

from quality_gates.config import QualityConfig, load_config
from quality_gates.gates.packages import (
    _compiled_risks,
    load_declared_packages,
    run_packages,
    scan_diff,
)


def _scan(
    diff: str,
    tmp_path: Path,
    *,
    require_declared: bool = True,
    allow: set[str] | None = None,
) -> list:
    return scan_diff(
        diff,
        risks=_compiled_risks(QualityConfig()),
        declared=load_declared_packages(tmp_path),
        local_python={"app", "quality_gates"},
        require_declared=require_declared,
        allow=allow or set(),
        skip_globs=[],
    )


def test_flags_python_typosquat_import(tmp_path: Path) -> None:
    diff = "+++ b/src/app.py\n@@ -0,0 +1,1 @@\n+import request\n"
    hits = _scan(diff, tmp_path)
    assert any(
        item.rule == "package-risk" and "request" in item.message for item in hits
    )


def test_flags_npm_malware_and_skips_fs(tmp_path: Path) -> None:
    diff = (
        "+++ b/src/app.js\n"
        "@@ -0,0 +1,2 @@\n"
        "+const fs = require('fs');\n"
        "+require('event-stream');\n"
    )
    hits = _scan(diff, tmp_path, require_declared=False)
    assert any(
        item.rule == "package-risk" and "event-stream" in item.message for item in hits
    )
    assert not any("fs" in (item.message or "") for item in hits)


def test_undeclared_third_party_python(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = []\n', encoding="utf-8"
    )
    diff = "+++ b/src/app.py\n@@ -0,0 +1,1 @@\n+import requests\n"
    hits = _scan(diff, tmp_path)
    assert any(item.rule == "undeclared-import" for item in hits)


def test_stdlib_and_local_imports_are_clean(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    diff = "+++ b/src/app.py\n@@ -0,0 +1,2 @@\n+import json\n+from app import VALUE\n"
    hits = _scan(diff, tmp_path)
    assert hits == []


def test_declared_optional_dep_is_clean(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n'
        '[project.optional-dependencies]\ndev = ["pytest>=8"]\n',
        encoding="utf-8",
    )
    diff = "+++ b/tests/test_app.py\n@@ -0,0 +1,1 @@\n+import pytest\n"
    hits = _scan(diff, tmp_path)
    assert hits == []


def test_pyproject_added_risky_dep(tmp_path: Path) -> None:
    diff = '+++ b/pyproject.toml\n@@ -0,0 +1,1 @@\n+  "pycrypto>=2.6",\n'
    hits = _scan(diff, tmp_path)
    assert any(
        item.rule == "package-risk" and "pycrypto" in item.message for item in hits
    )


def test_jwt_go_abandoned(tmp_path: Path) -> None:
    diff = '+++ b/auth.go\n@@ -0,0 +1,1 @@\n+import "github.com/dgrijalva/jwt-go"\n'
    hits = _scan(diff, tmp_path, require_declared=False)
    assert any("jwt-go" in item.message for item in hits)


def test_allow_list_suppresses_risk(tmp_path: Path) -> None:
    diff = "+++ b/src/app.py\n@@ -0,0 +1,1 @@\n+import request\n"
    hits = _scan(diff, tmp_path, allow={"request"})
    assert hits == []


def test_custom_deny_from_config(tmp_path: Path) -> None:
    (tmp_path / "quality.toml").write_text(
        """
[quality.packages]
include_defaults = false
[[quality.packages.deny]]
name = "left-pad"
ecosystem = "npm"
message = "no left-pad"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    diff = "+++ b/index.js\n@@ -0,0 +1,1 @@\n+require('left-pad');\n"
    result = run_packages(tmp_path, config, ["javascript"], diff=diff)
    assert result.status == "fail"
    assert result.findings[0].rule == "package-risk"


def test_disabled_gate_skips(tmp_path: Path) -> None:
    result = run_packages(tmp_path, QualityConfig(packages_enabled=False), ["python"])
    assert result.status == "skip"


def test_sql_only_change_skips(tmp_path: Path) -> None:
    diff = "+++ b/schema.sql\n@@ -0,0 +1,1 @@\n+SELECT 1;\n"
    result = run_packages(tmp_path, QualityConfig(), ["sql"], diff=diff)
    assert result.status == "skip"
