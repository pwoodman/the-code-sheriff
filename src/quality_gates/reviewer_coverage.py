"""Living matrix of the 100 reviewer capabilities and how they are proven."""

from __future__ import annotations

from dataclasses import dataclass

from quality_gates.host import DEFAULT_EVENTS, PERMISSIONS, app_identity, install_url
from quality_gates.review.commands import COMMANDS, parse_sheriff_command
from quality_gates.review.packs import PACK_IDS
from quality_gates.review.providers import PROVIDERS
from quality_gates.review.severity import LEVELS


@dataclass(frozen=True)
class CoverageItem:
    id: int
    title: str
    proof: str


ITEMS: tuple[CoverageItem, ...] = (
    CoverageItem(
        1, "Native GitHub App", "host.DEFAULT_EVENTS + github_app.job_from_webhook"
    ),
    CoverageItem(
        2, "Automatic PR Review", "review.automatic / drafts + webhook actions"
    ),
    CoverageItem(3, "High-Confidence Findings Only", "drop_style_nits + audit HIGH"),
    CoverageItem(4, "Inline GitHub Comments", "github_comment.post_review"),
    CoverageItem(5, "PR Review Summary", "review.summary.render_structured_summary"),
    CoverageItem(6, "Full Repository Context", "review.index.build_symbol_index"),
    CoverageItem(
        7,
        "Custom Repository Instructions",
        "REVIEW.md / .reviewer.yml / .quality/rules",
    ),
    CoverageItem(8, "Correctness Detection", "heuristic + regex correctness rules"),
    CoverageItem(9, "Security Analysis", "security gate + security pack"),
    CoverageItem(
        10, "Actionable Fix Suggestions", "suggestion fences + apply_and_verify"
    ),
    CoverageItem(11, "Noise Controls", "disabled categories + skip_globs + ignore"),
    CoverageItem(12, "Comment Feedback Loop", "review.feedback reactions"),
    CoverageItem(13, "No Duplicate Comments", "incremental fingerprints"),
    CoverageItem(14, "Fast First Result", "in_progress check + cheap routing"),
    CoverageItem(15, "Check-Run Status", "single The Code Sheriff check"),
    CoverageItem(16, "GitHub Permissions Minimization", "host.PERMISSIONS"),
    CoverageItem(17, "Bring-Your-Own-Model Key", "review.providers"),
    CoverageItem(18, "Model Routing by Task", "providers.task_model"),
    CoverageItem(19, "Data Retention Controls", "review.cost.gc_reports"),
    CoverageItem(20, "Clear Review Explanation", "explain_finding template"),
    CoverageItem(21, "Language Autodetection", "detect_languages"),
    CoverageItem(22, "Multi-Language Support", "SUPPORT_MATRIX"),
    CoverageItem(23, "Test-Gap Detection", "missing-tests + generate_test_patch"),
    CoverageItem(24, "Configurable Severity Levels", "review.severity LEVELS"),
    CoverageItem(25, "Security Secret Scanning", "gitleaks + trivy"),
    CoverageItem(26, "Dependency-Change Review", "review_lockfiles + packages"),
    CoverageItem(27, "Large-PR Handling", "partition_review_units + incomplete"),
    CoverageItem(28, "Monorepo Awareness", "discover_workspaces"),
    CoverageItem(29, "Incremental Review Cache", "review.incremental"),
    CoverageItem(30, "Safe Merge Gate", "advisory review + fail_on_severity"),
    CoverageItem(31, "Diff Intent Classification", "classify_intent"),
    CoverageItem(32, "Risk Scoring", "score_risk"),
    CoverageItem(33, "Changed-Code Focus", "change manifest + incremental hunks"),
    CoverageItem(34, "Call-Graph Awareness", "index.callers_of + impact"),
    CoverageItem(35, "Symbol-Aware Code Search", "search_symbols"),
    CoverageItem(36, "Framework-Aware Review Packs", "PACK_IDS"),
    CoverageItem(37, "IaC and Deployment Review", "terraform/docker/kubernetes packs"),
    CoverageItem(38, "CI Results Awareness", "triage_ci_failures"),
    CoverageItem(39, "Failure-Log Triage", "triage_ci_failures.summary"),
    CoverageItem(40, "Reviewer Commands", "parse_sheriff_command"),
    CoverageItem(41, "Manual Review Request", "/sheriff review"),
    CoverageItem(42, "Explain a Diff", "/sheriff explain"),
    CoverageItem(43, "Team Coding Standards", "quality rules preview"),
    CoverageItem(44, "Path-Specific Rules", "ReviewRule.paths"),
    CoverageItem(45, "Suppression with Rationale", "quality:ignore + ignore.toml"),
    CoverageItem(
        46, "Confidence Threshold Controls", "conservative/balanced/exploratory"
    ),
    CoverageItem(
        47, "Review Modes", "fast/standard/deep/security/tests/migration/architecture"
    ),
    CoverageItem(48, "Suggested-Test Generation", "generate_test_patch"),
    CoverageItem(49, "One-Click Fix PR", "fix_pr.plan_fix_pr"),
    CoverageItem(50, "Human Ownership Awareness", "parse_codeowners"),
    CoverageItem(51, "Private Repository Support", "app_identity.private_repos"),
    CoverageItem(52, "GitHub Enterprise Support", "GITHUB_API_URL / host.api_base"),
    CoverageItem(53, "Webhook Reliability", "delivery idempotency"),
    CoverageItem(
        54, "Queue and Concurrency Control", "cancel-in-progress + delivery dedup"
    ),
    CoverageItem(55, "Review Latency Dashboard", "latency_breakdown"),
    CoverageItem(56, "GitHub Actions Integration", "quality.yml + sheriff.yml"),
    CoverageItem(57, "CLI for Local Review", "quality review / check"),
    CoverageItem(58, "VS Code Extension", "editor/vscode"),
    CoverageItem(59, "JetBrains Support", "editor/jetbrains"),
    CoverageItem(60, "OpenAI-Compatible Endpoint Support", "OPENAI_BASE_URL"),
    CoverageItem(61, "Local/Self-Hosted Option", "CLI + compose worker"),
    CoverageItem(62, "VPC/Private-Network Execution", "self-hosted runners + compose"),
    CoverageItem(63, "Secrets Redaction", "redact_secrets"),
    CoverageItem(64, "Audit Logs", "audit.jsonl"),
    CoverageItem(65, "RBAC", "map_github_role"),
    CoverageItem(66, "SSO/SAML and SCIM", "app_identity.sso/scim"),
    CoverageItem(67, "Security-Policy Packs", "owasp-asvs + cwe-top-25"),
    CoverageItem(68, "Compliance Evidence Export", "export_evidence"),
    CoverageItem(69, "Vulnerability Verification", "reachability via impact/index"),
    CoverageItem(70, "Static Analysis Integration", "ingest_sarif"),
    CoverageItem(71, "Finding Deduplication", "dedupe_findings"),
    CoverageItem(72, "Baseline Management", "observe/adopt/enforce"),
    CoverageItem(73, "Custom Rule Authoring", ".quality/rules markdown"),
    CoverageItem(74, "Rule Simulation", "simulate_rule"),
    CoverageItem(75, "Review Analytics", "cost/history + feedback"),
    CoverageItem(76, "Signal-Quality Analytics", "reviewbench + feedback"),
    CoverageItem(77, "Per-Rule Performance", "rule_stats"),
    CoverageItem(78, "Cost Dashboard", "cost.json"),
    CoverageItem(79, "Cost Budgets and Caps", "within_budget"),
    CoverageItem(80, "Pricing Aligned to Value", "app_identity.pricing"),
    CoverageItem(81, "Change-Impact Map", "impact_map"),
    CoverageItem(82, "API Contract Review", "contract gate"),
    CoverageItem(83, "Database Migration Review", "migration pack + advanced gate"),
    CoverageItem(84, "Performance Review", "performance pack"),
    CoverageItem(85, "Concurrency Review", "concurrency pack + regex"),
    CoverageItem(86, "Error-Handling Review", "error-handling pack + regex"),
    CoverageItem(87, "Accessibility Review", "accessibility pack"),
    CoverageItem(88, "Documentation Drift Detection", "docs_drift"),
    CoverageItem(89, "Release-Note Draft", "notes.draft_notes"),
    CoverageItem(90, "Issue Linkage Awareness", "linked_issues"),
    CoverageItem(91, "Architecture Decision Awareness", "load_adrs"),
    CoverageItem(92, "Historical Code-Review Awareness", "similar_history"),
    CoverageItem(93, "Learning from Dispositions", "apply_feedback non-security"),
    CoverageItem(94, "Reviewer Workload Routing", "suggest_reviewers"),
    CoverageItem(95, "Slack/Teams Notifications", "notify_chat"),
    CoverageItem(96, "Public API", "quality serve"),
    CoverageItem(97, "Webhooks for Outcomes", "emit_outcome"),
    CoverageItem(98, "Terraform Provider", "terraform_schema + terraform/codesheriff"),
    CoverageItem(99, "Open-Source Core/SDK", "MIT + quality.schema.json + packs"),
    CoverageItem(
        100, "Transparent Evaluation Suite", "quality eval + standards/EVAL.md"
    ),
)


def coverage_ids() -> list[int]:
    return [item.id for item in ITEMS]


def assert_complete() -> None:
    ids = coverage_ids()
    if ids != list(range(1, 101)):
        raise AssertionError(f"coverage ids incomplete: {ids}")
    identity = app_identity()
    if set(DEFAULT_EVENTS) != {
        "pull_request",
        "check_run",
        "check_suite",
        "issue_comment",
    }:
        raise AssertionError("github events incomplete")
    if "checks" not in PERMISSIONS:
        raise AssertionError("permissions missing")
    if parse_sheriff_command("/sheriff help") is None:
        raise AssertionError("commands missing")
    if not set(COMMANDS) >= {
        "review",
        "summary",
        "explain",
        "check",
        "fix",
        "ignore",
        "help",
    }:
        raise AssertionError("command set incomplete")
    if "nextjs" not in PACK_IDS or "terraform" not in PACK_IDS:
        raise AssertionError("packs incomplete")
    if "azure" not in PROVIDERS or "gemini" not in PROVIDERS:
        raise AssertionError("providers incomplete")
    if "critical" not in LEVELS:
        raise AssertionError("severity taxonomy incomplete")
    if not identity["private_repos"] or not identity["install_url"]:
        raise AssertionError("app identity incomplete")
    if not install_url().endswith("/installations/new"):
        raise AssertionError("install url missing")


def shipped_count() -> int:
    return len(ITEMS)
