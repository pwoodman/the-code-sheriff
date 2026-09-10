# Reviewer capability coverage

Living matrix for the 100 GitHub-native reviewer capabilities.
Status is `shipped` only when `tests/test_reviewer_coverage.py` asserts the How.

The catalog lives in `quality_gates.reviewer_coverage.ITEMS`.

| ID | Capability | Status | Proof |
| --- | --- | --- | --- |
| 1 | Native GitHub App | shipped | `host.DEFAULT_EVENTS + github_app.job_from_webhook` |
| 2 | Automatic PR Review | shipped | `review.automatic / drafts + webhook actions` |
| 3 | High-Confidence Findings Only | shipped | `drop_style_nits + audit HIGH` |
| 4 | Inline GitHub Comments | shipped | `github_comment.post_review` |
| 5 | PR Review Summary | shipped | `review.summary.render_structured_summary` |
| 6 | Full Repository Context | shipped | `review.index.build_symbol_index` |
| 7 | Custom Repository Instructions | shipped | `REVIEW.md / .reviewer.yml / .quality/rules` |
| 8 | Correctness Detection | shipped | `heuristic + regex correctness rules` |
| 9 | Security Analysis | shipped | `security gate + security pack` |
| 10 | Actionable Fix Suggestions | shipped | `suggestion fences + apply_and_verify` |
| 11 | Noise Controls | shipped | `disabled categories + skip_globs + ignore` |
| 12 | Comment Feedback Loop | shipped | `review.feedback reactions` |
| 13 | No Duplicate Comments | shipped | `incremental fingerprints` |
| 14 | Fast First Result | shipped | `in_progress check + cheap routing` |
| 15 | Check-Run Status | shipped | `single The Code Sheriff check` |
| 16 | GitHub Permissions Minimization | shipped | `host.PERMISSIONS` |
| 17 | Bring-Your-Own-Model Key | shipped | `review.providers` |
| 18 | Model Routing by Task | shipped | `providers.task_model` |
| 19 | Data Retention Controls | shipped | `review.cost.gc_reports` |
| 20 | Clear Review Explanation | shipped | `explain_finding template` |
| 21 | Language Autodetection | shipped | `detect_languages` |
| 22 | Multi-Language Support | shipped | `SUPPORT_MATRIX` |
| 23 | Test-Gap Detection | shipped | `missing-tests + generate_test_patch` |
| 24 | Configurable Severity Levels | shipped | `review.severity LEVELS` |
| 25 | Security Secret Scanning | shipped | `gitleaks + trivy` |
| 26 | Dependency-Change Review | shipped | `review_lockfiles + packages` |
| 27 | Large-PR Handling | shipped | `partition_review_units + incomplete` |
| 28 | Monorepo Awareness | shipped | `discover_workspaces` |
| 29 | Incremental Review Cache | shipped | `review.incremental` |
| 30 | Safe Merge Gate | shipped | `advisory review + fail_on_severity` |
| 31 | Diff Intent Classification | shipped | `classify_intent` |
| 32 | Risk Scoring | shipped | `score_risk` |
| 33 | Changed-Code Focus | shipped | `change manifest + incremental hunks` |
| 34 | Call-Graph Awareness | shipped | `index.callers_of + impact` |
| 35 | Symbol-Aware Code Search | shipped | `search_symbols` |
| 36 | Framework-Aware Review Packs | shipped | `PACK_IDS` |
| 37 | IaC and Deployment Review | shipped | `terraform/docker/kubernetes packs` |
| 38 | CI Results Awareness | shipped | `triage_ci_failures` |
| 39 | Failure-Log Triage | shipped | `triage_ci_failures.summary` |
| 40 | Reviewer Commands | shipped | `parse_sheriff_command` |
| 41 | Manual Review Request | shipped | `/sheriff review` |
| 42 | Explain a Diff | shipped | `/sheriff explain` |
| 43 | Team Coding Standards | shipped | `quality rules preview` |
| 44 | Path-Specific Rules | shipped | `ReviewRule.paths` |
| 45 | Suppression with Rationale | shipped | `quality:ignore + ignore.toml` |
| 46 | Confidence Threshold Controls | shipped | `conservative/balanced/exploratory` |
| 47 | Review Modes | shipped | `fast/standard/deep/security/tests/migration/architecture` |
| 48 | Suggested-Test Generation | shipped | `generate_test_patch` |
| 49 | One-Click Fix PR | shipped | `fix_pr.plan_fix_pr` |
| 50 | Human Ownership Awareness | shipped | `parse_codeowners` |
| 51 | Private Repository Support | shipped | `app_identity.private_repos` |
| 52 | GitHub Enterprise Support | shipped | `GITHUB_API_URL / host.api_base` |
| 53 | Webhook Reliability | shipped | `delivery idempotency` |
| 54 | Queue and Concurrency Control | shipped | `cancel-in-progress + delivery dedup` |
| 55 | Review Latency Dashboard | shipped | `latency_breakdown` |
| 56 | GitHub Actions Integration | shipped | `quality.yml + sheriff.yml` |
| 57 | CLI for Local Review | shipped | `quality review / check` |
| 58 | VS Code Extension | shipped | `editor/vscode` |
| 59 | JetBrains Support | shipped | `editor/jetbrains` |
| 60 | OpenAI-Compatible Endpoint Support | shipped | `OPENAI_BASE_URL` |
| 61 | Local/Self-Hosted Option | shipped | `CLI + compose worker` |
| 62 | VPC/Private-Network Execution | shipped | `self-hosted runners + compose` |
| 63 | Secrets Redaction | shipped | `redact_secrets` |
| 64 | Audit Logs | shipped | `audit.jsonl` |
| 65 | RBAC | shipped | `map_github_role` |
| 66 | SSO/SAML and SCIM | shipped | `app_identity.sso/scim` |
| 67 | Security-Policy Packs | shipped | `owasp-asvs + cwe-top-25` |
| 68 | Compliance Evidence Export | shipped | `export_evidence` |
| 69 | Vulnerability Verification | shipped | `reachability via impact/index` |
| 70 | Static Analysis Integration | shipped | `ingest_sarif` |
| 71 | Finding Deduplication | shipped | `dedupe_findings` |
| 72 | Baseline Management | shipped | `observe/adopt/enforce` |
| 73 | Custom Rule Authoring | shipped | `.quality/rules markdown` |
| 74 | Rule Simulation | shipped | `simulate_rule` |
| 75 | Review Analytics | shipped | `cost/history + feedback` |
| 76 | Signal-Quality Analytics | shipped | `reviewbench + feedback` |
| 77 | Per-Rule Performance | shipped | `rule_stats` |
| 78 | Cost Dashboard | shipped | `cost.json` |
| 79 | Cost Budgets and Caps | shipped | `within_budget` |
| 80 | Pricing Aligned to Value | shipped | `app_identity.pricing` |
| 81 | Change-Impact Map | shipped | `impact_map` |
| 82 | API Contract Review | shipped | `contract gate` |
| 83 | Database Migration Review | shipped | `migration pack + advanced gate` |
| 84 | Performance Review | shipped | `performance pack` |
| 85 | Concurrency Review | shipped | `concurrency pack + regex` |
| 86 | Error-Handling Review | shipped | `error-handling pack + regex` |
| 87 | Accessibility Review | shipped | `accessibility pack` |
| 88 | Documentation Drift Detection | shipped | `docs_drift` |
| 89 | Release-Note Draft | shipped | `notes.draft_notes` |
| 90 | Issue Linkage Awareness | shipped | `linked_issues` |
| 91 | Architecture Decision Awareness | shipped | `load_adrs` |
| 92 | Historical Code-Review Awareness | shipped | `similar_history` |
| 93 | Learning from Dispositions | shipped | `apply_feedback non-security` |
| 94 | Reviewer Workload Routing | shipped | `suggest_reviewers` |
| 95 | Slack/Teams Notifications | shipped | `notify_chat` |
| 96 | Public API | shipped | `quality serve` |
| 97 | Webhooks for Outcomes | shipped | `emit_outcome` |
| 98 | Terraform Provider | shipped | `terraform_schema + terraform/codesheriff` |
| 99 | Open-Source Core/SDK | shipped | `MIT + quality.schema.json + packs` |
| 100 | Transparent Evaluation Suite | shipped | `quality eval + standards/EVAL.md` |

Run:

```bash
uv run pytest -q tests/test_reviewer_coverage.py
```

