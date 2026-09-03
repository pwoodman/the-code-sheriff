from __future__ import annotations

from pathlib import Path

from quality_gates.cli import main
from quality_gates.models import Finding, GateResult
from quality_gates.report import (
    build_digest,
    render_console,
    render_html,
    render_markdown,
    write_reports,
)


def _fail(name: str, message: str, *, path: str = "a.py") -> GateResult:
    return GateResult(
        name=name,
        status="fail",
        findings=[
            Finding(gate=name, rule=f"{name}-1", path=path, line=3, message=message)
        ],
        duration_ms=12,
    )


def test_digest_includes_performance_issues_and_recs() -> None:
    results = [
        GateResult(
            name="format",
            status="pass",
            notes=["ruff format ok"],
            duration_ms=40,
        ),
        _fail("lint", "unused import"),
        GateResult(
            name="coverage",
            status="pass",
            notes=["line coverage 55.0% (floor 50%), branch 30.0% from coverage.xml"],
            duration_ms=800,
        ),
        GateResult(
            name="dry",
            status="pass",
            notes=["duplication: 0% of tokens"],
            duration_ms=100,
        ),
        GateResult(
            name="audit",
            status="pass",
            notes=["surfaces: ci, deps", "confirmed findings: 0 (0 at fail priority)"],
            duration_ms=50,
        ),
        GateResult(
            name="security",
            status="skip",
            notes=["security scanners skipped"],
            skipped_tools=["gitleaks", "osv-scanner", "semgrep"],
            duration_ms=5,
        ),
    ]
    digest = build_digest(results, policy="enforce")
    assert digest.verdict == "fail"
    assert digest.errors == 1
    assert digest.performance.coverage_line == 55.0
    assert digest.performance.duplication_percent == 0.0
    assert digest.performance.audit_surfaces == ["ci", "deps"]
    titles = [item.title for item in digest.recommendations]
    assert "Fix lint errors" in titles
    assert "Install security scanners" in titles
    assert any("80%" in item.detail for item in digest.recommendations)

    text = render_console(digest)
    assert "Scorecard" in text
    assert "Performance" in text
    assert "Issues" in text
    assert "Recommendations" in text
    assert "unused import" in text

    md = render_markdown(digest)
    assert "## Performance" in md
    assert "## Issues" in md
    assert "## Recommendations" in md

    page = render_html(digest)
    assert "<!DOCTYPE html>" in page
    assert "Quality report" in page
    assert "unused import" in page


def test_write_reports_emits_html_and_json(tmp_path: Path) -> None:
    results = [
        GateResult(name="format", status="pass", duration_ms=9),
        GateResult(name="version", status="pass", duration_ms=4),
    ]
    write_reports(results, tmp_path / ".quality-reports", policy="enforce")
    report_dir = tmp_path / ".quality-reports"
    assert (report_dir / "quality-report.md").is_file()
    assert (report_dir / "quality-report.html").is_file()
    payload = (report_dir / "quality-report.json").read_text(encoding="utf-8")
    assert '"verdict": "pass"' in payload
    assert "recommendations" in payload


def test_quality_report_reprints_last_run(tmp_path: Path, capsys, monkeypatch) -> None:
    results = [_fail("version", "bump required", path="src/app.py")]
    write_reports(results, tmp_path / ".quality-reports", policy="enforce")
    monkeypatch.chdir(tmp_path)
    code = main(["report"])
    assert code == 1
    out = capsys.readouterr().out
    assert "Bump the version" in out
    assert "quality bump auto" in out


def test_observe_recommends_adopt() -> None:
    results = [
        GateResult(
            name="lint",
            status="pass",
            findings=[
                Finding(
                    gate="lint",
                    message="style",
                    severity="warning",
                    path="a.py",
                )
            ],
        )
    ]
    digest = build_digest(results, policy="observe")
    assert any("observe" in item.detail.lower() for item in digest.recommendations)
