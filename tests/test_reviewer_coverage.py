from __future__ import annotations

import json
from pathlib import Path

from quality_gates import __version__
from quality_gates.config import QualityConfig
from quality_gates.fix_pr import branch_name, generate_test_patch, plan_fix_pr
from quality_gates.github_app import default_manifest, job_from_webhook, list_deliveries
from quality_gates.host import (
    DEFAULT_EVENTS,
    PERMISSIONS,
    api_base,
    api_url,
    app_identity,
    graphql_url,
    install_url,
    marketplace_url,
)
from quality_gates.models import Finding
from quality_gates.notes import draft_notes
from quality_gates.platform import (
    api_state,
    dedupe_findings,
    emit_outcome,
    export_evidence,
    ingest_sarif,
    map_github_role,
    notify_chat,
    rule_stats,
    simulate_rule,
    terraform_schema,
)
from quality_gates.redact import redact_secrets
from quality_gates.review.commands import help_text, parse_sheriff_command
from quality_gates.review.context_extra import (
    adr_conflicts,
    docs_drift,
    linked_issues,
    load_adrs,
    owners_for,
    parse_codeowners,
    review_lockfiles,
    similar_history,
    suggest_reviewers,
    triage_ci_failures,
)
from quality_gates.review.cost import (
    gc_reports,
    latency_breakdown,
    record_usage,
    within_budget,
)
from quality_gates.review.explain import explain_diff, explain_finding
from quality_gates.review.feedback import (
    apply_feedback,
    classify_reaction,
    record_feedback,
    should_suppress_rule,
)
from quality_gates.review.index import build_symbol_index, callers_of, search_symbols
from quality_gates.review.packs import PACK_IDS, detect_packs, load_packs
from quality_gates.review.providers import PROVIDERS, task_model
from quality_gates.review.severity import LEVELS, blocks_merge, taxonomy_level
from quality_gates.review.summary import (
    classify_intent,
    impact_map,
    merge_signal,
    render_structured_summary,
    score_risk,
)
from quality_gates.reviewer_coverage import (
    ITEMS,
    assert_complete,
    coverage_ids,
    shipped_count,
)


def test_all_one_hundred_ids_are_present() -> None:
    assert coverage_ids() == list(range(1, 101))
    assert shipped_count() == 100
    assert_complete()
    assert {item.id for item in ITEMS} == set(range(1, 101))


def test_native_app_events_permissions_and_install(monkeypatch) -> None:
    assert set(DEFAULT_EVENTS) == {
        "pull_request",
        "check_run",
        "check_suite",
        "issue_comment",
    }
    manifest = default_manifest(
        webhook_url="https://example.test/hook",
        redirect_url="http://127.0.0.1/callback",
        public=True,
    )
    assert manifest["public"] is True
    assert set(manifest["default_events"]) == set(DEFAULT_EVENTS)
    assert "checks" in PERMISSIONS
    assert install_url().endswith("/installations/new")
    assert "marketplace" in marketplace_url()
    identity = app_identity()
    assert identity["private_repos"] is True
    assert "SAML" in identity["sso"]
    assert "SCIM" in identity["scim"]
    assert "MIT" in identity["pricing"]
    monkeypatch.setenv("GITHUB_API_URL", "https://ghe.example/api/v3")
    assert api_base() == "https://ghe.example/api/v3"
    assert api_url("/repos/a/b") == "https://ghe.example/api/v3/repos/a/b"
    assert graphql_url() == "https://ghe.example/api/graphql"


def test_sheriff_commands_and_webhook_jobs() -> None:
    assert parse_sheriff_command("/sheriff review").name == "review"
    assert parse_sheriff_command("/sheriff check tests").focus == "tests"
    assert parse_sheriff_command(
        "/sheriff explain What does billing do?"
    ).argument.startswith("What does")
    assert "`/sheriff review`" in help_text()
    payload = {
        "action": "created",
        "installation": {"id": 9},
        "repository": {"full_name": "acme/app"},
        "issue": {
            "number": 4,
            "pull_request": {"head": {"sha": "abc"}, "base": {"ref": "main"}},
        },
        "comment": {"body": "/sheriff review"},
    }
    job = job_from_webhook("issue_comment", payload)
    assert job is not None
    assert job["command"] == "review"
    suite = {
        "action": "rerequested",
        "installation": {"id": 9},
        "repository": {"full_name": "acme/app"},
        "check_suite": {
            "head_sha": "def",
            "pull_requests": [{"number": 4, "base": {"ref": "main"}}],
        },
    }
    assert job_from_webhook("check_suite", suite)["sha"] == "def"
    assert list_deliveries() == []


def test_summary_risk_severity_and_explanation() -> None:
    finding = Finding(
        gate="review",
        rule="eval",
        severity="error",
        path="app.py",
        line=3,
        message="eval is unsafe",
        reason="user input reaches eval",
        suggestion="parse JSON instead",
        snippet="eval(x)",
        confidence="HIGH",
    )
    assert taxonomy_level(finding) in LEVELS
    assert classify_intent(["docs/README.md"]) == "docs"
    assert score_risk(["src/auth/login.py"], [finding], auth_touched=True) in {
        "high",
        "critical",
    }
    assert merge_signal([finding], risk="high") == "needs work"
    text = render_structured_summary(
        intent="feature",
        risk="low",
        signal="safe to merge",
        findings=[],
        paths=["a.py"],
        languages=["python"],
    )
    assert "safe to merge" in text
    explained = explain_finding(finding)
    assert "What is wrong" in explained
    assert "Confidence" in explained
    assert "billing" in explain_diff("Why billing?", ["billing.py"])
    assert blocks_merge("critical", ["high"]) is True
    assert impact_map(["api/routes.py", "models/user.py"])["apis"]


def test_index_packs_feedback_cost_and_context(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        "def checkout():\n    return 1\n", encoding="utf-8"
    )
    (tmp_path / "CODEOWNERS").write_text("* @acme/platform\n", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        '{"deps": {"leftpad": "latest"}}\n', encoding="utf-8"
    )
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    (tmp_path / "docs" / "adr" / "0001.md").write_text(
        "# ADR Use Postgres\nMUST NOT add a second database.\n",
        encoding="utf-8",
    )
    config = QualityConfig()
    index = build_symbol_index(tmp_path, config)
    assert search_symbols(index, "checkout")
    assert callers_of(index, "checkout")
    packs = load_packs(
        tmp_path, config, paths=["app.tsx", "main.tf"], languages=["typescript"]
    )
    assert "security" in detect_packs(["app.tsx"], ["typescript"])
    assert {pack.name for pack in packs} <= set(PACK_IDS)
    assert "terraform" in PACK_IDS and "nextjs" in PACK_IDS
    record_feedback(tmp_path, rule="style-nit", disposition="not_useful")
    record_feedback(tmp_path, rule="style-nit", disposition="not_useful")
    record_feedback(tmp_path, rule="style-nit", disposition="incorrect")
    assert should_suppress_rule(tmp_path, "style-nit")
    assert classify_reaction("+1") == "useful"
    noisy = Finding(gate="review", rule="style-nit", message="nit", severity="info")
    assert apply_feedback(tmp_path, [noisy]) == []
    record_usage(
        tmp_path, provider="openai", model="gpt", input_tokens=10, output_tokens=5
    )
    ok, _reason = within_budget(tmp_path, monthly_cap=0, per_pr_tokens=0)
    assert ok
    assert gc_reports(tmp_path, days=30)["days"] == 30
    assert latency_breakdown(queue_ms=1, model_ms=2)["complete_ms"] == 3
    owners = owners_for(["app.py"], parse_codeowners(tmp_path))
    assert "@acme/platform" in owners
    assert linked_issues("Fixes #12") == ["12"]
    assert load_adrs(tmp_path)
    assert review_lockfiles(tmp_path, ["package.json"])
    assert docs_drift(["src/app.py"])
    triage = triage_ci_failures(
        [{"name": "tests", "conclusion": "failure", "output": "app.py failed"}],
        ["app.py"],
    )
    assert triage["failed"] == 1
    assert suggest_reviewers(owners, ["alice"])
    assert similar_history([{"paths": ["app.py"], "title": "old"}], ["app.py"])
    adr_conflicts(load_adrs(tmp_path), ["db.py"], "add mysql")


def test_providers_fix_pr_platform_and_notes(tmp_path: Path, monkeypatch) -> None:
    assert {"azure", "bedrock", "gemini", "openrouter", "compat"} <= set(PROVIDERS)
    config = QualityConfig(review_cheap_model="cheap", review_full_model="full")
    assert task_model(config, "summary", cheap="c", full="f") == "cheap"
    assert task_model(config, "security", cheap="c", full="f") == "full"
    finding = Finding(
        gate="review",
        message="x",
        path="app.py",
        patch="--- a/app.py\n+++ b/app.py\n",
    )
    plan = plan_fix_pr(pr=3, findings=[finding])
    assert plan["fix_branch"] == branch_name(3)
    assert plan["author_branch_untouched"] is True
    assert "def test_checkout" in generate_test_patch("app.py", "checkout")
    sarif = {
        "runs": [
            {
                "tool": {"driver": {"name": "eslint"}},
                "results": [
                    {
                        "ruleId": "no-eval",
                        "level": "error",
                        "message": {"text": "eval"},
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {"uri": "app.js"},
                                    "region": {"startLine": 2},
                                }
                            }
                        ],
                    }
                ],
            }
        ]
    }
    (tmp_path / "in.sarif").write_text(json.dumps(sarif), encoding="utf-8")
    ingested = ingest_sarif(tmp_path, tmp_path / "in.sarif")
    merged = dedupe_findings([ingested, ingested])
    assert len(merged) == 1
    export_evidence(tmp_path, framework="soc2")
    assert (tmp_path / ".quality-reports" / "evidence-soc2.json").is_file()
    assert map_github_role("admin") == "org admin"
    assert terraform_schema()["resources"]
    assert (
        simulate_rule(["src/auth/a.py", "docs/a.md"], "src/auth/**")["matched_files"]
        == 1
    )
    assert rule_stats(ingested)[0]["rule"] == "no-eval"
    assert emit_outcome("http://127.0.0.1:9", "review.completed", {}) == 0
    assert notify_chat("http://127.0.0.1:9", "done") == 0
    notes = draft_notes([{"title": "feat: add invoices"}, {"title": "chore: bump ci"}])
    assert notes and "invoices" in notes[0].lower()
    assert "supersecret" not in redact_secrets("password=supersecret")
    state = api_state(tmp_path)
    assert "identity" in state
    assert __version__ == "1.15.0"


def test_shipped_surfaces_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "editor" / "vscode" / "extension.js").is_file()
    assert (
        root
        / "editor"
        / "jetbrains"
        / "src"
        / "main"
        / "resources"
        / "META-INF"
        / "plugin.xml"
    ).is_file()
    assert (root / "github-app" / "compose.yaml").is_file()
    assert (root / "terraform" / "codesheriff" / "main.tf").is_file()
    assert (root / "standards" / "EVAL.md").is_file()
    assert (root / "docs" / "PRICING.md").is_file()
    assert (root / "docs" / "ENTERPRISE.md").is_file()
    packs = root / "configs" / "packs"
    for name in PACK_IDS:
        assert (packs / f"{name}.md").is_file(), name
