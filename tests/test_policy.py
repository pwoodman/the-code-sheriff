from __future__ import annotations

from pathlib import Path

from quality_gates.config import QualityConfig, load_config
from quality_gates.models import Finding, GateResult
from quality_gates.policy import apply_policy, fingerprint, write_baseline


def _failing(name: str, rule: str, path: str) -> GateResult:
    return GateResult(
        name=name,
        status="fail",
        findings=[
            Finding(gate=name, rule=rule, path=path, message="bad", severity="error")
        ],
    )


def test_observe_never_blocks(tmp_path: Path) -> None:
    config = QualityConfig(policy="observe")
    results, policy = apply_policy([_failing("lint", "E001", "a.py")], tmp_path, config)
    assert policy == "observe"
    assert results[0].status == "pass"
    assert results[0].error_count() == 0
    assert results[0].warning_count() == 1


def test_adopt_without_baseline_does_not_block(tmp_path: Path) -> None:
    config = QualityConfig(policy="adopt")
    results, _ = apply_policy(
        [_failing("audit", "audit-4", "app.py")], tmp_path, config
    )
    assert results[0].status == "pass"


def test_adopt_fails_only_new_fingerprints(tmp_path: Path) -> None:
    config = QualityConfig(policy="adopt")
    old = _failing("audit", "audit-39", ".github/workflows/ci.yml")
    (tmp_path / ".quality-reports").mkdir()
    write_baseline(tmp_path, config, [old])
    mixed = [
        old,
        _failing("audit", "audit-4", "app.py"),
    ]
    mixed[0].status = "fail"
    mixed[1].status = "fail"
    # combine into one gate result as the real audit gate does
    combined = GateResult(
        name="audit",
        status="fail",
        findings=old.findings + mixed[1].findings,
    )
    results, _ = apply_policy([combined], tmp_path, config)
    assert results[0].status == "fail"
    assert results[0].error_count() == 1
    assert results[0].warning_count() == 1
    assert fingerprint(results[0].findings[1]).endswith("app.py")


def test_adopt_coverage_respects_repo_baseline(tmp_path: Path) -> None:
    config = QualityConfig(policy="adopt")
    reports = tmp_path / ".quality-reports"
    reports.mkdir()
    (reports / "coverage.json").write_text('{"line_percent": 52.0}\n', encoding="utf-8")
    (tmp_path / ".quality-baseline.json").write_text(
        '{"version": 1, "coverage_line": 50.0, "fingerprints": []}\n',
        encoding="utf-8",
    )
    coverage = GateResult(
        name="coverage",
        status="fail",
        findings=[
            Finding(
                gate="coverage",
                rule="below-floor",
                message="line coverage 52.0% is below the 80% floor",
                severity="error",
            )
        ],
    )
    results, _ = apply_policy([coverage], tmp_path, config)
    assert results[0].status == "pass"
    assert "baseline" in results[0].notes[-1]


def test_enforce_still_fails(tmp_path: Path) -> None:
    config = QualityConfig(policy="enforce")
    results, policy = apply_policy([_failing("lint", "E001", "a.py")], tmp_path, config)
    assert policy == "enforce"
    assert results[0].status == "fail"


def test_quality_toml_policy(tmp_path: Path) -> None:
    (tmp_path / "quality.toml").write_text(
        '[quality]\npolicy = "observe"\n', encoding="utf-8"
    )
    config = load_config(tmp_path)
    assert config.policy == "observe"


def test_default_policy_is_adopt(tmp_path: Path) -> None:
    assert load_config(tmp_path).policy == "adopt"
