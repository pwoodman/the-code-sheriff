from __future__ import annotations

from pathlib import Path

from quality_gates.config import QualityConfig, load_config
from quality_gates.coverage_parse import (
    CoverageSummary,
    parse_cobertura_xml,
    parse_istanbul_summary,
    parse_lcov,
)
from quality_gates.gates.coverage import _run_tool, run_coverage


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


def test_failed_tests_block_even_with_full_coverage(
    tmp_path: Path, monkeypatch
) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_demo.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    summary = CoverageSummary(100.0, 100.0, 10, 10, source="coverage.xml")
    monkeypatch.setattr(
        "quality_gates.gates.coverage._collect",
        lambda *_args: (summary, ["test execution failed: pytest --cov exited 1"]),
    )

    result = run_coverage(tmp_path, QualityConfig())

    assert result.status == "fail"
    assert [item.rule for item in result.findings] == ["test-execution-failed"]


def test_coverage_config_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    assert config.coverage_line == 80.0
    assert config.coverage_branch == 0.0
    assert "coverage" in config.fail_on


def test_all_applicable_coverage_runners_are_aggregated(
    tmp_path: Path, monkeypatch
) -> None:
    first = CoverageSummary(50.0, None, 5, 10, source=str(tmp_path / "python.xml"))
    second = CoverageSummary(80.0, None, 8, 10, source=str(tmp_path / "lcov.info"))
    calls: list[str] = []

    def runner(name: str, summary: CoverageSummary):
        def run(*_args):
            calls.append(name)
            return summary

        return run

    monkeypatch.setattr(
        "quality_gates.gates.coverage._pytest_cov", runner("python", first)
    )
    monkeypatch.setattr(
        "quality_gates.gates.coverage._js_coverage", runner("javascript", second)
    )
    monkeypatch.setattr("quality_gates.gates.coverage._go_cover", runner("go", None))
    notes: list[str] = []
    summary = _run_tool(tmp_path, QualityConfig(), tmp_path, notes)

    assert calls == ["python", "javascript", "go"]
    assert summary is not None
    assert summary.lines_covered == 13
    assert summary.lines_valid == 20
    assert summary.line_percent == 65.0
    assert any("partial polyglot coverage" in note for note in notes)


def test_coverage_runner_deduplicates_same_source(tmp_path: Path, monkeypatch) -> None:
    source = str(tmp_path / "coverage.xml")
    summary = CoverageSummary(50.0, None, 5, 10, source=source)
    monkeypatch.setattr(
        "quality_gates.gates.coverage._pytest_cov", lambda *_args: summary
    )
    monkeypatch.setattr(
        "quality_gates.gates.coverage._js_coverage", lambda *_args: summary
    )
    monkeypatch.setattr("quality_gates.gates.coverage._go_cover", lambda *_args: None)
    notes: list[str] = []
    combined = _run_tool(tmp_path, QualityConfig(), tmp_path, notes)
    assert combined is not None
    assert combined.lines_valid == 10
    assert any("duplicate coverage report ignored" in note for note in notes)


def test_changed_lines_coverage_detects_untested_new_lines(
    tmp_path: Path, monkeypatch
) -> None:
    from quality_gates.change_manifest import Change, ChangedHunk, ChangeManifest

    cov_xml = tmp_path / "coverage.xml"
    cov_xml.write_text(
        """<?xml version="1.0" ?>
<coverage version="7.0" line-rate="0.9" branch-rate="0" lines-covered="9" lines-valid="10">
  <packages>
    <package name="pkg">
      <classes>
        <class name="core.py" filename="src/app.py" line-rate="0.9">
          <lines>
            <line number="1" hits="1"/>
            <line number="2" hits="1"/>
            <line number="3" hits="0"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
""",
        encoding="utf-8",
    )
    summary = CoverageSummary(90.0, None, 9, 10, source=str(cov_xml))
    monkeypatch.setattr(
        "quality_gates.gates.coverage._collect",
        lambda *_args: (summary, ["collected via pytest-cov"]),
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_smoke.py").write_text("def test_ok(): pass\n", encoding="utf-8")

    manifest = ChangeManifest(
        state="available",
        base="HEAD~1",
        target="HEAD",
        target_tree=None,
        working_tree_digest="digest",
        changes=(
            Change(
                "modified",
                "src/app.py",
                hunks=(ChangedHunk("src/app.py", 1, 1, 3, 1),),
            ),
        ),
    )
    result = run_coverage(
        tmp_path, QualityConfig(coverage_line=80.0), manifest=manifest
    )
    assert any(item.rule == "uncovered-changed-lines" for item in result.findings)
