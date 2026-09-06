from __future__ import annotations

import subprocess
from pathlib import Path

from quality_gates.change_manifest import (
    Change,
    ChangeManifest,
    _parse_hunks,
    discover_changes,
)
from quality_gates.config import QualityConfig, load_config
from quality_gates.decision import evaluate
from quality_gates.evidence import attach_evidence, evidence_is_fresh
from quality_gates.gates.advanced import run_advanced
from quality_gates.gates.common import skip_result
from quality_gates.gates.test import run_tests
from quality_gates.impact_graph import analyze, build_graph
from quality_gates.models import Finding, GateResult
from quality_gates.planner import build_plan
from quality_gates.policy import apply_policy, write_baseline


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_risk_gate_requires_configured_verification(tmp_path: Path) -> None:
    result = run_advanced(
        tmp_path, QualityConfig(), "migration", ["migrations/002_drop_users.sql"]
    )
    assert result.status == "unsupported"
    assert result.exit_state == "unsupported"
    assert result.findings[0].rule == "verification-not-configured"
    assert not evaluate([result], ["migration"]).approved


def test_migration_gate_checks_recovery_strategy_after_command(tmp_path: Path) -> None:
    path = tmp_path / "migrations"
    path.mkdir()
    (path / "002.sql").write_text("DROP TABLE users;", encoding="utf-8")
    config = QualityConfig(raw={"quality": {"migration": {"command": ["true"]}}})
    result = run_advanced(tmp_path, config, "migration", ["migrations/002.sql"])
    assert result.status == "fail"
    assert result.findings[0].rule == "destructive-operation"


def test_evidence_binds_result_to_snapshot_and_configuration(tmp_path: Path) -> None:
    config = QualityConfig(raw={"quality": {}})
    result = attach_evidence(GateResult(name="lint", status="pass"), tmp_path, config)
    assert evidence_is_fresh(result.evidence, tmp_path, config)
    (tmp_path / "changed.py").write_text("x = 1\n", encoding="utf-8")
    assert not evidence_is_fresh(result.evidence, tmp_path, config)


def test_expiring_approved_exception_is_narrow_and_auditable(tmp_path: Path) -> None:
    result = GateResult(
        name="lint",
        status="fail",
        findings=[Finding(gate="lint", rule="X1", path="app.py", message="bad")],
    )
    config = QualityConfig(
        policy="enforce",
        policy_exceptions=[
            {
                "owner": "security@example.test",
                "approved_by": "maintainer@example.test",
                "reason": "tracked migration",
                "expires": "2099-01-01T00:00:00+00:00",
                "gate": "lint",
                "rule": "X1",
                "path": "app.py",
            }
        ],
    )
    applied, _ = apply_policy([result], tmp_path, config)
    assert applied[0].status == "pass"
    assert "expires 2099" in (applied[0].findings[0].reason or "")


def test_manifest_parses_changed_line_ranges() -> None:
    hunks = _parse_hunks("+++ b/src/app.py\n@@ -10,2 +11,3 @@ def f():\n")
    assert hunks["src/app.py"][0].new_start == 11
    assert hunks["src/app.py"][0].old_count == 2


def test_scenario_1_small_isolated_change_produces_small_justified_plan() -> None:
    manifest = ChangeManifest(
        state="available",
        base="main",
        target="HEAD",
        target_tree="tree",
        working_tree_digest="digest",
        changes=(Change("modified", "src/util.py"),),
    )
    plan = build_plan(["format", "lint"], QualityConfig(fail_on=["lint"]), manifest)
    selected = [task for task in plan if task.status == "selected"]
    assert len(selected) == 2
    assert selected[0].inputs == ("src/util.py",)


def test_scenario_2_shared_config_change_expands_plan(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "core.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="demo"\n', encoding="utf-8"
    )
    graph = build_graph(tmp_path, QualityConfig())
    impact = analyze(graph, ["pyproject.toml"], depth=2, root=tmp_path)
    assert "pkg/core.py" in impact.config_affected


def test_scenario_3_deletions_renames_first_commits_untracked(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "old.py").write_text("old\n", encoding="utf-8")
    (tmp_path / "del.py").write_text("del\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "first")

    _git(tmp_path, "mv", "old.py", "renamed.py")
    (tmp_path / "del.py").unlink()
    (tmp_path / "untracked.py").write_text("new\n", encoding="utf-8")

    manifest = discover_changes(tmp_path, "HEAD")
    assert manifest.state == "available"
    kinds = {c.kind for c in manifest.changes}
    assert {"renamed", "deleted", "untracked"}.issubset(kinds)


def test_scenario_4_new_and_legacy_repositories_automatic_verification(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    result = run_tests(tmp_path, QualityConfig())
    assert result.status == "unsupported"
    assert result.findings[0].rule == "test-readiness"

    config = QualityConfig(policy="adopt")
    static_debt = GateResult(
        name="lint",
        status="fail",
        findings=[Finding(gate="lint", rule="E1", path="app.py", message="style")],
    )
    write_baseline(tmp_path, config, [static_debt])
    test_failure = GateResult(
        name="test",
        status="fail",
        findings=[Finding(gate="test", rule="execution-failed", message="failed")],
    )
    applied, _ = apply_policy([static_debt, test_failure], tmp_path, config)
    assert applied[0].status == "pass"
    assert applied[1].status == "fail"


def test_scenario_5_required_missing_tools_stale_reports_failed_tests_partial_reviews_cannot_approve() -> (
    None
):
    unsupported = GateResult(name="compile", status="skip", exit_state="unsupported")
    assert not evaluate([unsupported], ["compile"]).approved

    stale_cov = GateResult(name="coverage", status="fail", exit_state="blocked")
    assert not evaluate([stale_cov], ["coverage"]).approved

    failed_test = GateResult(name="test", status="fail", exit_state="failed")
    assert not evaluate([failed_test], ["test"]).approved

    partial_rev = GateResult(name="review", status="fail", exit_state="failed")
    assert not evaluate([partial_rev], ["review"]).approved


def test_scenario_6_policy_changes_in_pr_cannot_weaken_pr_own_requirements(
    tmp_path: Path, monkeypatch
) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "quality.toml").write_text(
        '[quality]\nfail_on = ["compile", "security"]\ntrust = "untrusted"\n',
        encoding="utf-8",
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "initial base")

    # Create a feature branch and commit the weakened policy
    _git(tmp_path, "checkout", "-b", "feature", "-q")
    (tmp_path / "quality.toml").write_text(
        '[quality]\nfail_on = []\ntrust = "trusted"\n', encoding="utf-8"
    )
    _git(tmp_path, "commit", "-am", "weaken policy", "-q")

    monkeypatch.setenv("QUALITY_TRUSTED_BASE", "HEAD~1")
    config = load_config(tmp_path)
    assert "compile" in config.fail_on
    assert config.trust == "untrusted"


def test_scenario_7_cli_oracle_mcp_hosted_return_consistent_decisions() -> None:
    from quality_gates.oracle import remaining_from_results

    failed_gate = GateResult(name="compile", status="fail")
    cli_eval = evaluate([failed_gate], ["compile"])
    oracle_eval = remaining_from_results([failed_gate], required=["compile"])

    assert cli_eval.approved is False
    assert oracle_eval["green"] is False


def test_scenario_8_fixes_receive_fresh_verification_before_resolved(
    tmp_path: Path, monkeypatch
) -> None:
    from quality_gates.review.apply import apply_and_verify

    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    finding = Finding(
        gate="review",
        message="unused",
        path="app.py",
        patch="""--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-x = 1
+x = 2
""",
    )
    monkeypatch.setattr("quality_gates.cli.main", lambda _argv: 0)
    monkeypatch.setattr(
        "quality_gates.report.load_results",
        lambda _dir: ([GateResult(name="review", status="pass")], "enforce"),
    )
    result = apply_and_verify(tmp_path, finding)
    assert result["resolved"] is True
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "x = 2\n"


def test_scenario_9_unsupported_capabilities_visible_and_never_verified() -> None:
    result = skip_result("compile", "tsc missing", tool="tsc")
    assert result.exit_state == "unsupported"
    assert not evaluate([result], ["compile"]).approved


def test_scenario_10_users_complete_workflow_through_one_command_run(
    tmp_path: Path,
) -> None:
    from quality_gates.cli import main

    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "quality.toml").write_text(
        '[quality]\npolicy = "observe"\nfail_on = ["format"]\n', encoding="utf-8"
    )
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "initial")

    code = main(["--root", str(tmp_path), "run", "--plan"])
    assert code == 0
