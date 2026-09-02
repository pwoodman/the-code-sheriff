from __future__ import annotations

from pathlib import Path

import pytest

from quality_gates.config import load_config
from quality_gates.gates.format import run_format
from quality_gates.gates.lint import run_lint
from quality_gates.tools import which


@pytest.mark.skipif(which("ruff") is None, reason="ruff not installed")
def test_ruff_format_and_lint_on_temp_project(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("import os\n\nx=1\n", encoding="utf-8")
    config = load_config(tmp_path)
    formatted = run_format(tmp_path, config, ["python"], check=True)
    assert formatted.status == "fail"
    linted = run_lint(tmp_path, config, ["python"])
    assert linted.status == "fail"
    assert any(
        item.rule == "F401" or "unused" in item.message.lower()
        for item in linted.findings
    )
