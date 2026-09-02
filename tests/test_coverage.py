from __future__ import annotations

from pathlib import Path

from quality_gates.config import QualityConfig, load_config
from quality_gates.coverage_parse import (
    parse_cobertura_xml,
    parse_istanbul_summary,
    parse_lcov,
)
from quality_gates.gates.coverage import run_coverage


def test_cobertura_percent(tmp_path: Path) -> None:
    xml = tmp_path / "coverage.xml"
    xml.write_text(
        """<?xml version="1.0" ?>
<coverage line-rate="0.82" branch-rate="0.4" lines-covered="82" lines-valid="100"
          branches-covered="4" branches-valid="10" version="7.0">
</coverage>
""",
        encoding="utf-8",
    )
    summary = parse_cobertura_xml(xml)
    assert summary.line_percent == 82.0
    ok, _ = summary.meets(80.0, 0.0)
    assert ok is True
    ok, reason = summary.meets(90.0, 0.0)
    assert ok is False
    assert "90" in reason


def test_lcov_and_istanbul(tmp_path: Path) -> None:
    lcov = tmp_path / "lcov.info"
    lcov.write_text(
        "TN:\nSF:a.py\nDA:1,1\nDA:2,0\nLF:2\nLH:1\nend_of_record\n", encoding="utf-8"
    )
    summary = parse_lcov(lcov)
    assert summary.line_percent == 50.0

    js = tmp_path / "coverage-summary.json"
    js.write_text(
        '{"total":{"lines":{"pct":91.5,"covered":91,"total":100},'
        '"branches":{"pct":10,"covered":1,"total":10}}}',
        encoding="utf-8",
    )
    istanbul = parse_istanbul_summary(js)
    assert istanbul.line_percent == 91.5


def test_coverage_skips_without_tests(tmp_path: Path) -> None:
    (tmp_path / "pkg.py").write_text("VALUE = 1\n", encoding="utf-8")
    result = run_coverage(tmp_path, QualityConfig())
    assert result.status == "skip"


def test_coverage_fails_under_floor(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_demo.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    xml = tmp_path / "coverage.xml"
    xml.write_text(
        """<?xml version="1.0" ?>
<coverage line-rate="0.4" branch-rate="0" lines-covered="4" lines-valid="10"
          version="7.0"></coverage>
""",
        encoding="utf-8",
    )
    config = QualityConfig(coverage_tool="existing", coverage_line=80.0)
    result = run_coverage(tmp_path, config)
    assert result.status == "fail"
    assert result.error_count() == 1


def test_coverage_config_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    assert config.coverage_line == 80.0
    assert config.coverage_branch == 0.0
    assert "coverage" in config.fail_on
