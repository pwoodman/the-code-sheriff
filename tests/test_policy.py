from __future__ import annotations

import subprocess
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


def test_adopt_rejects_a_corrupt_baseline(tmp_path: Path) -> None:
    config = QualityConfig(policy="adopt")
    (tmp_path / ".quality-baseline.json").write_text("not json", encoding="utf-8")

    results, _ = apply_policy([_failing("lint", "E001", "a.py")], tmp_path, config)

    assert results[0].status == "fail"
    assert results[0].findings[-1].rule == "baseline-invalid"


def test_adopt_rejects_a_deleted_tracked_baseline(tmp_path: Path) -> None:
    config = QualityConfig(policy="adopt")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".quality-baseline.json").write_text(
        '{"fingerprints": []}\n', encoding="utf-8"
    )
    subprocess.run(["git", "add", ".quality-baseline.json"], cwd=tmp_path, check=True)
    (tmp_path / ".quality-baseline.json").unlink()

    results, _ = apply_policy([_failing("lint", "E001", "a.py")], tmp_path, config)

    assert results[0].status == "fail"
    assert results[0].findings[-1].rule == "baseline-missing"


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


def test_baseline_keeps_distinct_repeated_findings(tmp_path: Path) -> None:
    config = QualityConfig(policy="adopt")
    duplicate = GateResult(
        name="lint",
        status="fail",
        findings=[
            Finding(gate="lint", rule="E1", path="app.py", line=10, message="bad"),
            Finding(gate="lint", rule="E1", path="app.py", line=20, message="bad"),
        ],
    )

    write_baseline(tmp_path, config, [duplicate])

    baseline = (tmp_path / ".quality-baseline.json").read_text(encoding="utf-8")
    assert '"fingerprints": [' in baseline
    assert baseline.count("app.py") == 2


def test_baseline_identity_survives_a_harmless_line_shift(tmp_path: Path) -> None:
    config = QualityConfig(policy="adopt")
    original = GateResult(
        name="lint",
        status="fail",
        findings=[
            Finding(gate="lint", rule="E1", path="app.py", line=10, message="bad")
        ],
    )
    write_baseline(tmp_path, config, [original])
    shifted = GateResult(
        name="lint",
        status="fail",
        findings=[
            Finding(gate="lint", rule="E1", path="app.py", line=14, message="bad")
        ],
    )

    results, _ = apply_policy([shifted], tmp_path, config)

    assert results[0].status == "pass"


def test_ratchet_removes_repaired_findings(tmp_path: Path) -> None:
    config = QualityConfig(policy="adopt")
    old = _failing("lint", "E001", "app.py")
    write_baseline(tmp_path, config, [old])

    write_baseline(tmp_path, config, [], ratchet=True)

    assert '"fingerprints": []' in (tmp_path / ".quality-baseline.json").read_text(
        encoding="utf-8"
    )


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


def test_adopt_never_grandfathers_fresh_test_execution_failure(tmp_path: Path) -> None:
    config = QualityConfig(policy="adopt")
    failed = GateResult(
        name="test",
        status="fail",
        findings=[Finding(gate="test", rule="execution-failed", message="failed")],
    )
    write_baseline(tmp_path, config, [failed])

    results, _ = apply_policy([failed], tmp_path, config)

    assert results[0].status == "fail"
    assert results[0].findings[0].severity == "error"


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
