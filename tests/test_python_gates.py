from __future__ import annotations

from pathlib import Path

import pytest

from quality_gates.config import load_config
from quality_gates.gates.format import _ruff_unformatted_path, run_format
from quality_gates.gates.lint import run_lint
from quality_gates.tools import which


def test_ruff_unformatted_path_ignores_summary_lines() -> None:
    assert _ruff_unformatted_path("Would reformat: src/app.py") == "src/app.py"
    assert _ruff_unformatted_path('Would reformat: "src/app.py"') == "src/app.py"
    assert _ruff_unformatted_path("unformatted: File would be reformatted") is None
    assert _ruff_unformatted_path(" --> sample.py:3:2") == "sample.py"
    assert _ruff_unformatted_path("6 files would be reformatted") is None
    assert _ruff_unformatted_path("File would be reformatted") is None
    assert _ruff_unformatted_path("1 file would be reformatted") is None
    colored = (
        "\x1b[1m\x1b[91munformatted:\x1b[0m\x1b[1m File would be reformatted\x1b[0m"
    )
    assert _ruff_unformatted_path(colored) is None
    assert _ruff_unformatted_path(" \x1b[1m\x1b[94m--> \x1b[0msample.py:3:2") == (
        "sample.py"
    )


@pytest.mark.skipif(which("ruff") is None, reason="ruff not installed")
def test_ruff_format_and_lint_on_temp_project(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("import os\n\nx=1\n", encoding="utf-8")
    config = load_config(tmp_path)
    formatted = run_format(tmp_path, config, ["python"], check=True)
    assert formatted.status == "fail"
    assert any(item.path.endswith("sample.py") for item in formatted.findings)
    linted = run_lint(tmp_path, config, ["python"])
    assert linted.status == "fail"
    assert any(
        item.rule == "F401" or "unused" in item.message.lower()
        for item in linted.findings
    )
