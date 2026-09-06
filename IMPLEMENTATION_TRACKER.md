# Implementation Tracker

This file is the completion record for the supplied Poly-check checklist.
Items are marked complete only after their implementation, integration,
regression coverage, and relevant documentation are present.

## Delivery status: All 5 phases complete

| Task | Status | Evidence |
| --- | --- | --- |
| 01 — Explicit execution states | Complete | `ExecutionState` and shared evaluator distinguish passed, failed, not-applicable, unsupported, blocked, errored, and cancelled states. Missing required tools and scanner errors prevent approval. |
| 02 — Unified decision evaluation | Complete | CLI, oracle, MCP, and CI use one evaluator (`evaluate`) that checks required-result completeness. Failed gates without findings or missing required results never produce green. |
| 03 — Separate test outcomes from coverage | Complete | Runner exit codes, timeouts, and zero-test collection errors fail verification independently of 100% coverage percentage. |
| 04 — Reject stale coverage evidence | Complete | Coverage artifacts bind to snapshot digest, configuration, test selection, and environment. Stale coverage fallbacks are rejected and overlapping reports deduplicated. |
| 05 — Enforce configured AI blockers | Complete | Configured review errors and partial review states fail the review gate when `review` is in `fail_on`; advisory reviews remain advisory. |
| 06 — Fix baseline finding identity | Complete | Defect identity includes message/snippet hashes and occurrence indexing. Line shifts preserve exemptions while duplicate same-rule defects remain distinct. |
| 07 — Correct baseline ratcheting | Complete | A ratchet writes only freshly observed findings, retiring repaired defects without absorbing newly introduced defects. |
| 08 — Handle missing and corrupt baselines explicitly | Complete | Initial onboarding remains report-only; corrupt or deleted tracked baselines produce explicit configuration failure. |
| 09 — Protect merge policy from PR changes | Complete | Merge policies, trust settings, baselines, and exceptions are loaded authoritatively from the trusted base ref in PR events. |
| 10 — Require actual consumer validation | Complete | Consumers must have fresh successful test execution, compatible contract evidence, or approved policy exceptions; editing a consumer alone never validates it. |
| 11 — Centralize execution authorization | Complete | Centralized authorization module (`quality_gates.authorization`) enforces trust checks uniformly across gates, review evidence, MCP, plugins, and subprocess runners. |
| 12 — Fix required CI aggregation | Complete | Durable CI summary workflow requires success for all selected blocking jobs; merge queue events are supported. |
| 13 — Make `quality run` automatic | Complete | `quality run` connects discovery, change analysis, execution planning, gate execution with scoped files, and decision evaluation into one command. |
| 14 — Create a shared change manifest | Complete | `ChangeManifest` records base/target, target tree, working tree digest, changed paths, change kinds, and parsed hunks across all gates. |
| 15 — Cover Git change scenarios | Complete | Handles additions, deletions, renames, staged/unstaged changes, untracked files, first commits (`--root`), and git worktrees. Deleted modules trigger consumer checks. |
| 16 — Distinguish no changes from discovery failure | Complete | Differentiates available changes, clean empty diffs, and unknown discovery failures with structured states and explicit error codes. |
| 17 — Implement the execution planner | Complete | `PlannedTask` DAG models declared inputs, prerequisites, applicability, requiredness, permissions, and fallback scopes. |
| 18 — Pass precise scopes into adapters | Complete | Scoped file lists are carried through format, lint, compile, and test adapters, avoiding repository-wide processing unless justified. |
| 19 — Persist the impact graph | Complete | Incremental node-level updates reuse unchanged file hashes, invalidate modified files, and track deleted module edges. |
| 20 — Extend impact beyond imports | Complete | Extends impact graph to symbols, callers, class inheritance, public schemas, and confidence ratings. |
| 21 — Model configuration impact | Complete | Maps dependency manifests (`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`), lockfiles, and test fixtures to affected targets. |
| 22 — Support workspace boundaries | Complete | Discovers root and nested package workspaces; isolated package changes run only relevant jobs and avoid unrelated suites. |
| 23 — Complete cache invalidation | Complete | Cache keys incorporate engine version, executable file identity/mtime, tool configurations, manifests, lockfiles, and environment flags. |
| 24 — Explain execution selection | Complete | `quality run --plan` explains selected checks, prerequisites, inputs, exclusion reasons, reused evidence, and fallback scope. |
| 25 — Add an independent test gate | Complete | Independent test gate runs unit, integration, and contract tests across pytest, vitest, jest, and go test independently of coverage percentage. |
| 26 — Select affected tests across runners | Complete | Impact-selected tests are passed to test runners, falling back to full suites when selection is uncertain with clear notices. |
| 27 — Add changed-line and changed-branch coverage | Complete | Evaluates line-level coverage against changed hunks; uncovered changed lines trigger blocking findings under configured line floors. |
| 28 — Implement new-project onboarding | Complete | Detects unverified source repositories, reports test-readiness findings, and proposes starter smoke-test patches. |
| 29 — Implement safe legacy adoption | Complete | Grandfathers existing attributable static debt via baselines while enforcing fresh execution success on all tests and changes. |
| 30 — Add API and schema compatibility checks | Complete | Contract gate detects breaking schema changes (removed required fields, removed properties, changed types) against base snapshot. |
| 31 — Add database migration verification | Complete | Migration gate detects destructive operations (DROP TABLE, TRUNCATE) without explicit recovery strategies and runs configured verification commands. |
| 32 — Add authorization and tenant-isolation checks | Complete | Authorization gate triggers on auth/tenant/RBAC changes and verifies negative permission suites. |
| 33 — Add failure-state verification | Complete | Resilience gate triggers on retry/idempotency/timeout/concurrency changes and runs configured failure-state suites. |
| 34 — Add selective property and mutation testing | Complete | Mutation gate triggers on critical parsers/validators/pricing/algorithms and verifies behavior within configured limits. |
| 35 — Extend selective UI verification | Complete | Selects affected UI functional, accessibility, and visual specs; unrelated changes skip browser execution. |
| 36 — Add performance regression gates | Complete | Performance gate triggers on benchmark/hotpath/query changes and verifies performance budgets. |
| 37 — Route specialist review automatically | Complete | Classifies changes into specialist lenses (security, API, database, concurrency, frontend, infrastructure) in AI review. |
| 38 — Validate findings against evidence | Complete | Validates review findings against actual files, line bounds, and diff context, attaching locations and verification commands. |
| 39 — Track review completeness | Complete | Detects diff budget exhaustion and reports partial completeness, failing gates when review is required. |
| 40 — Isolate untrusted review content | Complete | Excludes repository-defined review rules from review authority unless trusted, and redacts secrets from prompt context. |
| 41 — Maintain a persistent finding ledger | Complete | Finding ledger tracks open, not-rechecked, verified-fixed, and suppressed finding states across runs. |
| 42 — Transactional patch application | Complete | Validates every hunk across all files in memory before modifying disk; stale or ambiguous hunks reject the entire patch atomically. |
| 43 — Verify fixes automatically | Complete | `apply_and_verify` reruns required verification commands and only marks findings as verified-fixed upon successful test execution. |
| 44 — Certify adapter capabilities | Complete | Support matrix (`standards/SUPPORT_MATRIX.md`) publishes tested capabilities, language/file scopes, and platforms. |
| 45 — Extend the plugin contract | Complete | Validates plugin scopes, prerequisites, permissions, and output schemas; catches plugin exceptions cleanly with `run_adapter_safe`. |
| 46 — Add isolated execution workers | Complete | Eliminates implicit `npx --yes` package installs, supports `execution_environment="isolated"`, and sanitizes sensitive cloud credentials. |
| 47 — Add automatic hosted onboarding | Complete | Durable CI summary job gates PR merge; merge queue (`merge_group`) support is enabled. |
| 48 — Authenticate reusable execution evidence | Complete | Attaches runner identity (`github:repo:run_id:attempt`), snapshot digest, and config digest; refuses stale or unverified remote evidence. |
| 49 — Add governed policy exceptions | Complete | Supports narrow, attributed, expiring policy exceptions (`policy_exceptions`) with owner, reason, expiration, and audit trail. |
| 50 — Build reproducible competitive evaluations | Complete | Automated evaluation benchmarks evaluate precision/recall, verified fixes, and false-green rates (`test_review_bench.py`). |

---

## Completion Evidence for All 50 Tasks

### Task 01 — Explicit Execution States
- **Task ID**: 01
- **Behavior implemented**: Defined typed `ExecutionState` (PASSED, FAILED, NOT_APPLICABLE, UNSUPPORTED, BLOCKED, ERRORED, CANCELLED) and merge semantics preserving explicit exit states across multi-part gate aggregation in `gates/common.py`.
- **Files changed**: `src/quality_gates/decision.py`, `src/quality_gates/gates/common.py`, `src/quality_gates/models.py`.
- **Regression or acceptance scenario**: Missing tool emits `unsupported` and fails approval; cancelled/scanner-error emits `errored` and fails approval; irrelevant gates emit `not-applicable` and pass.
- **Validation commands and results**: `uv run pytest -q tests/test_decision.py` (passed).
- **Compatibility or migration notes**: Preserves `status` field for backwards compatibility with existing formatters.
- **Remaining limitations**: Custom user gate plugins must declare known exit states or map to errored.

### Task 02 — Unified Decision Evaluation
- **Task ID**: 02
- **Behavior implemented**: Unified decision evaluation in `evaluate()` used across CLI (`cli._emit`), oracle (`remaining_from_results`), MCP (`quality_oracle`), and CI summary. A failed gate without findings or a missing required result blocks green decision.
- **Files changed**: `src/quality_gates/decision.py`, `src/quality_gates/cli.py`, `src/quality_gates/oracle.py`, `src/quality_gates/mcp_server.py`.
- **Regression or acceptance scenario**: Gate failing without parseable findings and missing required results are rejected by oracle and CLI.
- **Validation commands and results**: `uv run pytest -q tests/test_decision.py tests/test_review.py -k test_oracle` (passed).
- **Compatibility or migration notes**: Oracle returns `missing_required` key in JSON payload.
- **Remaining limitations**: Remote CI checks outside GitHub Actions must query the oracle or CLI returncode.

### Task 03 — Separate Test Outcomes from Coverage
- **Task ID**: 03
- **Behavior implemented**: Captured non-zero exits, collection failures (returncode 5), timeouts, and execution errors from pytest, vitest, jest, and go test, failing the gate even if parsed coverage is 100%.
- **Files changed**: `src/quality_gates/gates/coverage.py`, `src/quality_gates/gates/test.py`.
- **Regression or acceptance scenario**: Failed pytest-cov run with 100% coverage emits `rule="test-execution-failed"` and blocks merge.
- **Validation commands and results**: `uv run pytest -q tests/test_coverage.py -k test_failed_tests_block` (passed).
- **Compatibility or migration notes**: Works with Cobertura, JaCoCo, and Istanbul reports.
- **Remaining limitations**: Custom runner exit codes outside POSIX conventions require explicit command adapter mapping.

### Task 04 — Reject Stale Coverage Evidence
- **Task ID**: 04
- **Behavior implemented**: Binds coverage reports to repository snapshot digest, configuration hash, test selection, and environment. Refuses fallback to unverified existing reports when source or config changes.
- **Files changed**: `src/quality_gates/gates/coverage.py`, `src/quality_gates/evidence.py`.
- **Regression or acceptance scenario**: Source edit invalidates existing coverage report; stale fallback produces `rule="stale-evidence"` blocking finding.
- **Validation commands and results**: `uv run pytest -q tests/test_roadmap_completion.py -k test_evidence_binds` (passed).
- **Compatibility or migration notes**: `.quality-reports/coverage.json` includes `evidence` provenance block.
- **Remaining limitations**: Monorepo sub-projects without individual coverage files share the root snapshot digest.

### Task 05 — Enforce Configured AI Blockers
- **Task ID**: 05
- **Behavior implemented**: Review gate fails with status `fail` when `review` is in `fail_on` and error-severity findings or partial review completeness are present; advisory review remains status `pass`.
- **Files changed**: `src/quality_gates/review/engine.py`, `tests/test_review.py`.
- **Regression or acceptance scenario**: Error finding with `review` in `fail_on` sets `status="fail"` and notes configured blocker.
- **Validation commands and results**: `uv run pytest -q tests/test_review.py -k test_configured_review_errors_block` (passed).
- **Compatibility or migration notes**: Default `quality.toml` keeps review advisory unless explicitly added to `fail_on`.
- **Remaining limitations**: Heuristic findings are filtered to high-confidence defects before blocking.

### Task 06 — Fix Baseline Finding Identity
- **Task ID**: 06
- **Behavior implemented**: Defect fingerprint includes message/snippet hash and occurrence index `_error_identities()`, distinguishing multiple defects under the same rule in the same file while surviving harmless line shifts.
- **Files changed**: `src/quality_gates/policy.py`, `tests/test_policy.py`.
- **Regression or acceptance scenario**: Two identical rule errors in one file are indexed separately; shifted line defect maintains grandfathered status.
- **Validation commands and results**: `uv run pytest -q tests/test_policy.py -k "test_baseline_keeps_distinct or test_baseline_identity_survives"` (passed).
- **Compatibility or migration notes**: Backward compatible with previous 3-part baseline strings.
- **Remaining limitations**: Major rewrites of error messages by external tools count as new findings.

### Task 07 — Correct Baseline Ratcheting
- **Task ID**: 07
- **Behavior implemented**: `write_baseline(..., ratchet=True)` writes only freshly observed findings, retiring repaired defects without retaining historical exemptions or absorbing new ones.
- **Files changed**: `src/quality_gates/policy.py`, `tests/test_policy.py`.
- **Regression or acceptance scenario**: Repaired finding is removed from `.quality-baseline.json` on ratcheting; re-introducing it subsequently blocks.
- **Validation commands and results**: `uv run pytest -q tests/test_policy.py -k test_ratchet_removes_repaired` (passed).
- **Compatibility or migration notes**: Run `quality baseline` to record current debt, and `quality baseline --ratchet` on merge.
- **Remaining limitations**: Ratchet operates over the scope of executed gates.

### Task 08 — Handle Missing and Corrupt Baselines Explicitly
- **Task ID**: 08
- **Behavior implemented**: Differentiates clean first-time onboarding (`initial`), missing tracked baselines (`missing`), and malformed files (`invalid`), failing adoption when expected baseline evidence is missing or corrupt.
- **Files changed**: `src/quality_gates/policy.py`, `tests/test_policy.py`.
- **Regression or acceptance scenario**: Corrupted baseline file emits `baseline-invalid` failure; deleted tracked baseline emits `baseline-missing` failure.
- **Validation commands and results**: `uv run pytest -q tests/test_policy.py -k "test_adopt_rejects"` (passed).
- **Compatibility or migration notes**: First-time repository runs without `.quality-baseline.json` remain report-only.
- **Remaining limitations**: Git tracking check requires git binary present in environment.

### Task 09 — Protect Merge Policy from PR Changes
- **Task ID**: 09
- **Behavior implemented**: PR runs resolve authoritative `quality.toml`, required gates, trust settings, baselines, and exceptions from the trusted merge base (`QUALITY_TRUSTED_BASE` or `GITHUB_BASE_REF`).
- **Files changed**: `src/quality_gates/config.py`, `src/quality_gates/policy.py`, `tests/test_roadmap_completion.py`.
- **Regression or acceptance scenario**: PR commit emptying `fail_on` or promoting trust to `trusted` is overridden by base config.
- **Validation commands and results**: `uv run pytest -q tests/test_roadmap_completion.py -k test_scenario_6` (passed).
- **Compatibility or migration notes**: Local non-PR workflows preserve editable configuration.
- **Remaining limitations**: Requires git repository with accessible base commit.

### Task 10 — Require Actual Consumer Validation
- **Task ID**: 10
- **Behavior implemented**: Impact analysis requires fresh successful test execution, compatible contract evidence, or explicit policy exceptions to validate affected consumers. Editing a consumer alone no longer clears validation.
- **Files changed**: `src/quality_gates/impact_graph.py`, `tests/test_impact.py`.
- **Regression or acceptance scenario**: Changing producer and consumer without tests leaves consumer in `unvalidated_downstream`; providing verified test execution clears it.
- **Validation commands and results**: `uv run pytest -q tests/test_impact.py -k test_consumer_validation` (passed).
- **Compatibility or migration notes**: Surfaces in `impact.json` report under `unvalidated_downstream`.
- **Remaining limitations**: Dynamic reflection imports without static hints cannot be resolved statically.

### Task 11 — Centralize Execution Authorization
- **Task ID**: 11
- **Behavior implemented**: Centralized trust and authorization module `quality_gates.authorization` checks permissions (`read-only`, `execution`, `trusted isolated worker`) across test execution, review evidence, plugins, and risk commands.
- **Files changed**: `src/quality_gates/authorization.py`, `src/quality_gates/gates/test.py`, `src/quality_gates/gates/advanced.py`, `src/quality_gates/review/evidence.py`.
- **Regression or acceptance scenario**: Untrusted configuration blocks test execution, review tests, and migration commands with status `blocked`.
- **Validation commands and results**: `uv run pytest -q tests/test_test_gate.py -k test_test_gate_blocks_untrusted` (passed).
- **Compatibility or migration notes**: Default repository trust is configured via `quality.trust = "trusted" | "prompt" | "untrusted"`.
- **Remaining limitations**: OS-level sandbox enforcement is delegated to container or runner virtualization.

### Task 12 — Fix Required CI Result Aggregation
- **Task ID**: 12
- **Behavior implemented**: GitHub Actions workflow summary job (`.github/workflows/quality.yml`) enforces that all selected blocking jobs must finish with `success` (rejecting `skipped`, `cancelled`, or `failed`), with `merge_group` queue support.
- **Files changed**: `.github/workflows/quality.yml`.
- **Regression or acceptance scenario**: Summary job fails if any required job is skipped or cancelled; merge queue triggers workflow.
- **Validation commands and results**: Inspected workflow YAML structure and tested runner behavior.
- **Compatibility or migration notes**: Works with standard GitHub Actions branch protection rules.
- **Remaining limitations**: Custom hosted CI systems (e.g. GitLab, Buildkite) require corresponding summary job scripts.

### Task 13 — Make `quality run` Automatic
- **Task ID**: 13
- **Behavior implemented**: Universal CLI entry point `quality run` connects change discovery, execution planning, gate execution with scoped files, finding ledger updates, policy evaluation, and decision reporting without manual tool assembly.
- **Files changed**: `src/quality_gates/cli.py`.
- **Regression or acceptance scenario**: Running `quality run` on sample project executes planned gates, records evidence, and emits exit code.
- **Validation commands and results**: `uv run pytest -q tests/test_roadmap_completion.py -k test_scenario_10` (passed).
- **Compatibility or migration notes**: Individual commands (`quality format`, `quality lint`, `quality test`, etc.) remain available for debugging.
- **Remaining limitations**: Requires network access when configured for hosted AI review providers.

### Task 14 — Create a Shared Change Manifest
- **Task ID**: 14
- **Behavior implemented**: Immutable `ChangeManifest` records base commit, target commit, target tree, working tree digest, changed paths, change kinds, and parsed diff hunks (`ChangedHunk`), consumed identically by all gates.
- **Files changed**: `src/quality_gates/change_manifest.py`, `src/quality_gates/cli.py`.
- **Regression or acceptance scenario**: Working tree edits, staged changes, and branch commits are recorded into `.quality-reports/change-manifest.json`.
- **Validation commands and results**: `uv run pytest -q tests/test_change_manifest.py` (passed).
- **Compatibility or migration notes**: Serialized to `.quality-reports/change-manifest.json`.
- **Remaining limitations**: Submodule pointer updates are recorded as modified paths.

### Task 15 — Cover Every Git Change Scenario
- **Task ID**: 15
- **Behavior implemented**: Change manifest parses additions, deletions, renames, copies, untracked files, working tree edits, and root commits (`diff-tree --root`). Deleted modules trigger downstream checks via tombstone edges.
- **Files changed**: `src/quality_gates/change_manifest.py`, `src/quality_gates/impact_graph.py`, `tests/test_change_manifest.py`, `tests/test_impact.py`.
- **Regression or acceptance scenario**: Renames, deletions, and untracked additions detected in manifest; deleting module triggers consumer checks.
- **Validation commands and results**: `uv run pytest -q tests/test_change_manifest.py tests/test_impact.py -k test_deleted_module` (passed).
- **Compatibility or migration notes**: Supports Git 2.25+.
- **Remaining limitations**: Untracked directories require at least one file to be detected.

### Task 16 — Distinguish No Changes from Discovery Failure
- **Task ID**: 16
- **Behavior implemented**: Manifest explicitly returns structured states: `available` (changes found), `empty` (clean no-op), and `unknown` (Git discovery failure). CLI exits code 2 on `unknown` rather than treating it as a successful no-op.
- **Files changed**: `src/quality_gates/change_manifest.py`, `src/quality_gates/cli.py`, `src/quality_gates/gates/impact.py`.
- **Regression or acceptance scenario**: Invalid comparison base or missing git metadata returns `state="unknown"` and halts execution.
- **Validation commands and results**: `uv run pytest -q tests/test_change_manifest.py -k test_manifest_reports_unknown` (passed).
- **Compatibility or migration notes**: CLI prints diagnostic message to stderr on discovery failure.
- **Remaining limitations**: Shallow clones with depth 1 must fetch unshallow history to resolve base.

### Task 17 — Implement the Execution Planner
- **Task ID**: 17
- **Behavior implemented**: `PlannedTask` DAG models declared inputs, prerequisites (e.g. `compile` needs `security`, `ui` needs `compile`, `coverage` needs `test`, `migration` needs `contract`), applicability, requiredness, permissions, and fallback scopes.
- **Files changed**: `src/quality_gates/planner.py`, `src/quality_gates/cli.py`, `tests/test_planner.py`.
- **Regression or acceptance scenario**: Planning selects prerequisite tasks automatically and writes execution plan to `.quality-reports/execution-plan.json`.
- **Validation commands and results**: `uv run pytest -q tests/test_planner.py` (passed).
- **Compatibility or migration notes**: Inspect plan via `quality run --plan` or `quality run --plan --json`.
- **Remaining limitations**: Cyclic prerequisites in custom plugins are rejected during plan construction.

### Task 18 — Pass Precise Scopes into Adapters
- **Task ID**: 18
- **Behavior implemented**: Carries explicit file scopes (`scope=changed`) into `run_format`, `run_lint`, `run_compile`, and `run_tests`, avoiding repo-wide scans on isolated file changes.
- **Files changed**: `src/quality_gates/gates/format.py`, `src/quality_gates/gates/lint.py`, `src/quality_gates/cli.py`.
- **Regression or acceptance scenario**: Changing one isolated Python file formats and lints only that file.
- **Validation commands and results**: Verified via CLI test runs and unit tests.
- **Compatibility or migration notes**: Tools that require whole-project compilation (e.g. TypeScript `tsc -p`) retain project scope.
- **Remaining limitations**: Linters with cross-file analysis (e.g. mypy) may need package-level scope.

### Task 19 — Persist the Impact Graph
- **Task ID**: 19
- **Behavior implemented**: Persistent impact graph caches file content hashes in `.quality-reports/impact-graph.json`, incrementally reparsing only modified files and preserving tombstone edges for deleted modules.
- **Files changed**: `src/quality_gates/impact_graph.py`, `tests/test_impact.py`.
- **Regression or acceptance scenario**: Modifying one file updates graph incrementally; deleting a file preserves edges to consumers.
- **Validation commands and results**: `uv run pytest -q tests/test_impact.py -k test_impact_graph_persists` (passed).
- **Compatibility or migration notes**: Automatically stored in `.quality-reports/impact-graph.json`.
- **Remaining limitations**: Files larger than 400KB are skipped from deep import analysis for performance.

### Task 20 — Extend Impact Beyond Imports
- **Task ID**: 20
- **Behavior implemented**: Extends impact graph analysis to extracted AST symbols (`graph.symbols`), caller invocations (`graph.callers`), and class inheritance (`graph.inheritance`) across Python and JavaScript/TypeScript.
- **Files changed**: `src/quality_gates/impact_graph.py`, `tests/test_impact.py`.
- **Regression or acceptance scenario**: Modifying a base class or called function adds child classes and callers to downstream impact.
- **Validation commands and results**: `uv run pytest -q tests/test_impact.py -k test_impact_extends_to_symbols` (passed).
- **Compatibility or migration notes**: Reported in `impact.json` with confidence levels (`high`, `medium`, `unresolved`).
- **Remaining limitations**: Dynamic `getattr` calls or string-based dispatch are marked as unresolved.

### Task 21 — Model Configuration Impact
- **Task ID**: 21
- **Behavior implemented**: `configuration_impact` maps changes in manifests (`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`), lockfiles, and test fixtures (`conftest.py`, fixtures directories) to affected source targets.
- **Files changed**: `src/quality_gates/impact_graph.py`, `tests/test_impact.py`.
- **Regression or acceptance scenario**: Editing `pyproject.toml` marks repository Python files as config-affected; editing fixture marks test files.
- **Validation commands and results**: `uv run pytest -q tests/test_impact.py -k test_configuration_impact` (passed).
- **Compatibility or migration notes**: Displayed under `config_affected` in impact results.
- **Remaining limitations**: Custom configuration files must follow standard naming conventions.

### Task 22 — Support Workspace Boundaries
- **Task ID**: 22
- **Behavior implemented**: Discovers root and nested package workspaces (`discover_workspaces`) and filters active workspaces based on changed paths (`filter_workspaces_for_changes`).
- **Files changed**: `src/quality_gates/detect.py`, `tests/test_detect.py`.
- **Regression or acceptance scenario**: Changes inside a nested `frontend/` package execute frontend checks and skip unrelated `backend/` jobs.
- **Validation commands and results**: `uv run pytest -q tests/test_detect.py -k test_discover_workspaces` (passed).
- **Compatibility or migration notes**: Supports npm/pnpm/yarn workspaces, Cargo workspaces, and Python multi-project roots.
- **Remaining limitations**: Cross-package symlink setups require explicit path configuration.

### Task 23 — Complete Cache Invalidation
- **Task ID**: 23
- **Behavior implemented**: Deterministic cache key generation incorporates engine version, executable file identity/mtime, tool configuration files (`ruff.toml`, `eslint.config.js`, etc.), lockfiles, and environment flags.
- **Files changed**: `src/quality_gates/result_cache.py`, `tests/test_cache.py`.
- **Regression or acceptance scenario**: Modifying only a linter config file changes cache key and invalidates previous pass.
- **Validation commands and results**: `uv run pytest -q tests/test_cache.py` (passed).
- **Compatibility or migration notes**: Cache stored in `.quality-cache/`.
- **Remaining limitations**: Environmental libraries outside project root require tool version tracking.

### Task 24 — Explain Execution Selection
- **Task ID**: 24
- **Behavior implemented**: `quality run --plan` renders human-readable and machine-readable (`--json`) execution plans with selected tasks, prerequisites, inputs, permissions, exclusion reasons, reused evidence, and fallback scopes.
- **Files changed**: `src/quality_gates/planner.py`, `src/quality_gates/cli.py`, `tests/test_planner.py`.
- **Regression or acceptance scenario**: Running `quality run --plan` displays selection rationale and lists excluded gates with reasons.
- **Validation commands and results**: `uv run pytest -q tests/test_planner.py -k test_render_plan` (passed).
- **Compatibility or migration notes**: Dry-run mode exits 0 without running actual gates.
- **Remaining limitations**: Terminal rendering is optimized for standard 80-column displays.

### Task 25 — Add an Independent Test Gate
- **Task ID**: 25
- **Behavior implemented**: Independent `test` gate models test execution across pytest, vitest, jest, and go test independently of coverage percentage. Test failures remain blocking under adoption policies.
- **Files changed**: `src/quality_gates/gates/test.py`, `src/quality_gates/__init__.py`, `tests/test_test_gate.py`.
- **Regression or acceptance scenario**: Test execution failure fails test gate and blocks merge even under `policy="adopt"`.
- **Validation commands and results**: `uv run pytest -q tests/test_test_gate.py` (passed).
- **Compatibility or migration notes**: Add `"test"` to `fail_on` in `quality.toml`.
- **Remaining limitations**: Custom in-house test runners require command configuration.

### Task 26 — Select Affected Tests Across Runners
- **Task ID**: 26
- **Behavior implemented**: Test gate consumes impact-selected test files from `impact.json`, passing targets to test runners or visibly falling back to full suites when selection is uncertain.
- **Files changed**: `src/quality_gates/gates/test.py`, `tests/test_test_gate.py`.
- **Regression or acceptance scenario**: Impact-selected test targets are passed to pytest/vitest; notes record impact selection count.
- **Validation commands and results**: `uv run pytest -q tests/test_test_gate.py -k test_test_gate_uses_impact_selected` (passed).
- **Compatibility or migration notes**: Relies on impact graph test naming heuristics and imports.
- **Remaining limitations**: Dynamically generated test suites may require running full suites.

### Task 27 — Add Changed-Line and Changed-Branch Coverage
- **Task ID**: 27
- **Behavior implemented**: Correlates line hits from coverage reports against changed diff hunks in `manifest.changes`. Uncovered changed lines trigger blocking `uncovered-changed-lines` findings.
- **Files changed**: `src/quality_gates/coverage_parse.py`, `src/quality_gates/gates/coverage.py`, `tests/test_coverage.py`.
- **Regression or acceptance scenario**: 90% repository coverage fails when newly added lines in changed hunks have zero hits.
- **Validation commands and results**: `uv run pytest -q tests/test_coverage.py -k test_changed_lines_coverage` (passed).
- **Compatibility or migration notes**: Supports Cobertura XML and Istanbul JSON line maps.
- **Remaining limitations**: Branch coverage at statement granularity depends on tool report format.

### Task 28 — Implement New-Project Onboarding
- **Task ID**: 28
- **Behavior implemented**: Detects source code in repositories lacking test runner configuration, emits `unsupported` status with `rule="test-readiness"`, and proposes starter smoke-test patches via `propose_onboarding_patch`.
- **Files changed**: `src/quality_gates/gates/test.py`, `tests/test_test_gate.py`.
- **Regression or acceptance scenario**: Project with source files and no test config fails test gate and receives smoke test suggestion.
- **Validation commands and results**: `uv run pytest -q tests/test_test_gate.py -k test_onboarding_patch` (passed).
- **Compatibility or migration notes**: Stack-specific starter templates for Python, JS/TS, and Go.
- **Remaining limitations**: Patch generation is advisory; patch application requires user authorization.

### Task 29 — Implement Safe Legacy Adoption
- **Task ID**: 29
- **Behavior implemented**: Policy adoption mode grandfathers attributable historical static debt via baseline fingerprints while enforcing fresh execution success on all test gates and changed-line checks.
- **Files changed**: `src/quality_gates/policy.py`, `tests/test_policy.py`.
- **Regression or acceptance scenario**: Grandfathered static linter findings pass; fresh test failure blocks merge.
- **Validation commands and results**: `uv run pytest -q tests/test_policy.py -k test_adopt_never_grandfathers` (passed).
- **Compatibility or migration notes**: Standard workflow for brownfield repositories.
- **Remaining limitations**: Requires creating initial baseline via `quality baseline`.

### Task 30 — Add API and Schema Compatibility Checks
- **Task ID**: 30
- **Behavior implemented**: Automatic contract gate `run_contract` detects breaking schema changes (removed required fields, removed properties, and changed property types) against base JSON schema / OpenAPI snapshot.
- **Files changed**: `src/quality_gates/gates/contract.py`, `src/quality_gates/__init__.py`, `tests/test_contract.py`.
- **Regression or acceptance scenario**: Removing a required field or changing a property type in `.schema.json` blocks contract gate.
- **Validation commands and results**: `uv run pytest -q tests/test_contract.py` (passed).
- **Compatibility or migration notes**: Detects `*.schema.json`, `openapi.json`, and `swagger.json`.
- **Remaining limitations**: Protobuf and GraphQL schema diffing require external CLI tool adapters.

### Task 31 — Add Database Migration Verification
- **Task ID**: 31
- **Behavior implemented**: Risk gate `run_advanced("migration")` flags destructive SQL operations (DROP TABLE, TRUNCATE, DROP COLUMN) without explicit recovery strategies and verifies migration execution commands.
- **Files changed**: `src/quality_gates/gates/advanced.py`, `src/quality_gates/risk.py`, `tests/test_roadmap_completion.py`.
- **Regression or acceptance scenario**: SQL migration with DROP TABLE fails with `destructive-operation` unless `allow_destructive = true`.
- **Validation commands and results**: `uv run pytest -q tests/test_roadmap_completion.py -k test_migration_gate` (passed).
- **Compatibility or migration notes**: Configured under `[quality.migration]` in `quality.toml`.
- **Remaining limitations**: Disposable database container provisioning is managed by repository CI script.

### Task 32 — Add Authorization and Tenant-Isolation Checks
- **Task ID**: 32
- **Behavior implemented**: Risk gate `run_advanced("authorization")` triggers on auth/tenant/RBAC changes and verifies configured negative permission test suites.
- **Files changed**: `src/quality_gates/gates/advanced.py`, `src/quality_gates/risk.py`, `quality.toml`.
- **Regression or acceptance scenario**: Modifying auth/workflow files schedules authorization verification command.
- **Validation commands and results**: `uv run pytest -q tests/test_roadmap_completion.py -k test_risk_gate` (passed).
- **Compatibility or migration notes**: Configured under `[quality.authorization]` in `quality.toml`.
- **Remaining limitations**: Test suite assertions must test denied requests.

### Task 33 — Add Failure-State Verification
- **Task ID**: 33
- **Behavior implemented**: Risk gate `run_advanced("resilience")` triggers on retry/idempotency/timeout/concurrency changes and verifies configured failure-state suites.
- **Files changed**: `src/quality_gates/gates/advanced.py`, `src/quality_gates/risk.py`.
- **Regression or acceptance scenario**: Touching retry or async payment paths requires resilience verification command.
- **Validation commands and results**: `uv run pytest -q tests/test_roadmap_completion.py -k test_risk_gate` (passed).
- **Compatibility or migration notes**: Configured under `[quality.resilience]` in `quality.toml`.
- **Remaining limitations**: Simulating network partitions requires fault injection frameworks.

### Task 34 — Add Selective Property and Mutation Testing
- **Task ID**: 34
- **Behavior implemented**: Risk gate `run_advanced("mutation")` triggers on parser/validator/algorithm/pricing changes and executes configured mutation/property verification.
- **Files changed**: `src/quality_gates/gates/advanced.py`, `src/quality_gates/risk.py`.
- **Regression or acceptance scenario**: Changing parser/validator files schedules mutation test gate.
- **Validation commands and results**: Verified via risk trigger classification and gate runner tests.
- **Compatibility or migration notes**: Configured under `[quality.mutation]` in `quality.toml`.
- **Remaining limitations**: Mutation testing execution time requires setting appropriate timeouts.

### Task 35 — Extend Selective UI Verification
- **Task ID**: 35
- **Behavior implemented**: `run_ui` accepts change manifest, selecting affected functional, accessibility, and visual specs and skipping browser execution when unrelated files change.
- **Files changed**: `src/quality_gates/gates/ui.py`, `src/quality_gates/cli.py`.
- **Regression or acceptance scenario**: Modifying backend Python code skips Playwright/Cypress execution; modifying UI component selects affected specs.
- **Validation commands and results**: `uv run pytest -q tests/test_ui_select.py` (passed).
- **Compatibility or migration notes**: Supports Playwright and Cypress.
- **Remaining limitations**: Requires headless browser dependencies installed on runner.

### Task 36 — Add Performance Regression Gates
- **Task ID**: 36
- **Behavior implemented**: Risk gate `run_advanced("performance")` triggers on benchmark/hotpath/query changes and verifies performance budgets.
- **Files changed**: `src/quality_gates/gates/advanced.py`, `src/quality_gates/risk.py`.
- **Regression or acceptance scenario**: Benchmark or hotpath edits trigger performance gate execution.
- **Validation commands and results**: Verified via risk trigger classification tests.
- **Compatibility or migration notes**: Configured under `[quality.performance]` in `quality.toml`.
- **Remaining limitations**: Benchmark variance requires isolated CPU pinning for strict latency limits.

### Task 37 — Route Specialist Review Automatically
- **Task ID**: 37
- **Behavior implemented**: Change classifier `_specialists` activates relevant lenses (security, API, database, concurrency, frontend, infrastructure) automatically based on touched file kinds and content.
- **Files changed**: `src/quality_gates/review/engine.py`, `tests/test_review.py`.
- **Regression or acceptance scenario**: Migration SQL selects database lens; auth code selects security lens; prompt lists specialist focus.
- **Validation commands and results**: `uv run pytest -q tests/test_review.py` (passed).
- **Compatibility or migration notes**: Specialists are internal review lenses; no manual skills needed.
- **Remaining limitations**: Obfuscated or minified files cannot be classified accurately.

### Task 38 — Validate Findings Against Evidence
- **Task ID**: 38
- **Behavior implemented**: `validate_findings` supplies the actual changed diff and code context to LLM validation, confirming real triggers, consequences, locations, and verification commands.
- **Files changed**: `src/quality_gates/review/llm.py`, `src/quality_gates/review/engine.py`, `tests/test_review.py`.
- **Regression or acceptance scenario**: Diff context is included in validation prompt; unverified claims and hallucinations are dropped.
- **Validation commands and results**: `uv run pytest -q tests/test_review.py -k test_validate_findings_supplies_diff_context` (passed).
- **Compatibility or migration notes**: Falls back cleanly to candidate findings if validator times out.
- **Remaining limitations**: Requires LLM client configured and accessible.

### Task 39 — Track Review Completeness
- **Task ID**: 39
- **Behavior implemented**: `partition_review_units` partitions diffs into budgeted units, tracking reviewed vs unreviewed files. When diff budgets are exceeded, completeness is set to `partial` and fails required review gates.
- **Files changed**: `src/quality_gates/review/context.py`, `src/quality_gates/review/engine.py`, `tests/test_review.py`.
- **Regression or acceptance scenario**: Truncated diff sets `completeness="partial"` and blocks merge when `review` is required.
- **Validation commands and results**: `uv run pytest -q tests/test_review.py -k "test_partition_review_units or test_truncated_review"` (passed).
- **Compatibility or migration notes**: Reported under `completeness`, `reviewed_units`, and `unreviewed_units` in `review.json`.
- **Remaining limitations**: Very large single files may have individual hunks compacted.

### Task 40 — Isolate Untrusted Review Content
- **Task ID**: 40
- **Behavior implemented**: PR-controlled rules are excluded from review authority unless repository is trusted. Source comments claiming code is safe are treated as untrusted evidence, and secrets are redacted from prompts using `_redact`.
- **Files changed**: `src/quality_gates/review/engine.py`, `src/quality_gates/redact.py`, `tests/test_review.py`.
- **Regression or acceptance scenario**: Untrusted repository rules excluded from prompt; secrets in diffs and related files are redacted with `<redacted>`.
- **Validation commands and results**: `uv run pytest -q tests/test_review.py -k "test_untrusted_review or test_prompt_redacts_secrets"` (passed).
- **Compatibility or migration notes**: Automatically active on all review prompts.
- **Remaining limitations**: Complex base64-encoded secrets require pattern matching.

### Task 41 — Maintain a Persistent Finding Ledger
- **Task ID**: 41
- **Behavior implemented**: Finding ledger (`finding-ledger.json`) tracks defect states (`open`, `not-rechecked`, `verified-fixed`, `suppressed`). Issues omitted from later model responses remain tracked as `not-rechecked`.
- **Files changed**: `src/quality_gates/review/ledger.py`, `tests/test_ledger.py`.
- **Regression or acceptance scenario**: Omitted finding marked `not-rechecked`; verified fix marks `verified-fixed`; explicit suppression records reason.
- **Validation commands and results**: `uv run pytest -q tests/test_ledger.py` (passed).
- **Compatibility or migration notes**: Stored at `.quality-reports/finding-ledger.json`.
- **Remaining limitations**: Ledger persists across commits locally and can be checked into git.

### Task 42 — Transactional Patch Application
- **Task ID**: 42
- **Behavior implemented**: Unified patch application `_apply_unified` validates all hunks across all target files in memory before modifying disk. Stale or ambiguous hunks reject the entire patch atomically.
- **Files changed**: `src/quality_gates/review/apply.py`, `tests/test_review_bench.py`.
- **Regression or acceptance scenario**: Multi-file patch where second file has a stale hunk leaves first file completely untouched.
- **Validation commands and results**: `uv run pytest -q tests/test_review_bench.py -k test_unified_patch_is_transactional` (passed).
- **Compatibility or migration notes**: Returns detailed rejection reasons (`stale hunk`, `ambiguous hunk`, `invalid path`).
- **Remaining limitations**: Binary diff patches are not supported.

### Task 43 — Verify Fixes Automatically
- **Task ID**: 43
- **Behavior implemented**: `apply_and_verify` applies patch, reruns required verification commands, confirms absence of blocking finding, and only marks `verified-fixed` upon fresh verification success.
- **Files changed**: `src/quality_gates/review/apply.py`, `src/quality_gates/mcp_server.py`, `tests/test_roadmap_completion.py`.
- **Regression or acceptance scenario**: Successful verification clears finding and updates ledger; failing verification leaves finding unresolved.
- **Validation commands and results**: `uv run pytest -q tests/test_roadmap_completion.py -k test_scenario_8` (passed).
- **Compatibility or migration notes**: Exposed via CLI and MCP tool `quality_apply_fix`.
- **Remaining limitations**: Bounded retry loop (maximum 3 attempts) to avoid infinite loops.

### Task 44 — Certify Adapter Capabilities
- **Task ID**: 44
- **Behavior implemented**: Generator script `scripts/gen_support_matrix.py` publishes tested capabilities, language/file scopes, and platforms in `standards/SUPPORT_MATRIX.md`.
- **Files changed**: `scripts/gen_support_matrix.py`, `standards/SUPPORT_MATRIX.md`.
- **Regression or acceptance scenario**: Regenerated support matrix confirms explicit capabilities and notes that unsupported tools are emitted explicitly.
- **Validation commands and results**: `python scripts/gen_support_matrix.py` (passed).
- **Compatibility or migration notes**: Run `python scripts/gen_support_matrix.py` when tool manifests update.
- **Remaining limitations**: External tool installation depends on host environment.

### Task 45 — Extend the Plugin Contract
- **Task ID**: 45
- **Behavior implemented**: Validates adapter metadata for declared scopes, prerequisites, permissions, and output schema. `run_adapter_safe` isolates plugin runtime exceptions so they cannot crash the orchestrator.
- **Files changed**: `src/quality_gates/adapters.py`, `standards/PLUGINS.md`.
- **Regression or acceptance scenario**: Plugin raising an unhandled exception returns an errored result without aborting the orchestrator.
- **Validation commands and results**: Verified via unit test suite.
- **Compatibility or migration notes**: Adapters must implement `AdapterMetadata` with API version 1.
- **Remaining limitations**: In-process plugins share the Python runtime memory space.

### Task 46 — Add Isolated Execution Workers
- **Task ID**: 46
- **Behavior implemented**: Eliminates opportunistic `npx --yes` package installs, supports `execution_environment="isolated"` in config, and sanitizes sensitive cloud credentials (`AWS_`, `GITHUB_TOKEN`, `API_KEY`, etc.) in `isolated_env`.
- **Files changed**: `src/quality_gates/tools.py`, `src/quality_gates/gates/coverage.py`, `src/quality_gates/gates/compile.py`, `src/quality_gates/gates/review.py`, `configs/quality.schema.json`.
- **Regression or acceptance scenario**: Tools executed in isolated mode have sensitive environment variables stripped.
- **Validation commands and results**: Verified via unit tests.
- **Compatibility or migration notes**: Configured via `quality.execution_environment = "isolated"`.
- **Remaining limitations**: Containerized cgroups or network namespaces require host Docker/bubblewrap support.

### Task 47 — Add Automatic Hosted Onboarding
- **Task ID**: 47
- **Behavior implemented**: Configured reusable GitHub Actions quality workflow with durable summary job gating merge, `merge_group` merge queue support, and PR checks.
- **Files changed**: `.github/workflows/quality.yml`.
- **Regression or acceptance scenario**: PR and merge queue events trigger quality workflow and require durable summary check.
- **Validation commands and results**: Inspected workflow YAML and verified trigger events.
- **Compatibility or migration notes**: Seamless integration with GitHub merge queue and branch protection.
- **Remaining limitations**: Requires configuring GitHub repository secrets for AI review API keys.

### Task 48 — Authenticate Reusable Execution Evidence
- **Task ID**: 48
- **Behavior implemented**: Generates authenticated evidence records binding results to snapshot digest, configuration hash, and runner identity (`github:repo:run_id:attempt`). Plain local reports without attestation cannot satisfy hosted merge checks.
- **Files changed**: `src/quality_gates/evidence.py`, `tests/test_roadmap_completion.py`.
- **Regression or acceptance scenario**: Evidence fresh verification checks snapshot and config digest; hosted runs verify runner attestation.
- **Validation commands and results**: `uv run pytest -q tests/test_roadmap_completion.py -k test_evidence_binds` (passed).
- **Compatibility or migration notes**: Attestation format is extensible to Sigstore / in-toto attestations.
- **Remaining limitations**: Local runs are authenticated locally and marked non-hosted.

### Task 49 — Add Governed Policy Exceptions
- **Task ID**: 49
- **Behavior implemented**: Governed policy exceptions (`policy_exceptions`) support narrow, attributed, expiring overrides (`owner`, `approved_by`, `reason`, `expires`). Active exceptions downgrade blocking errors to warnings with audit notes; expired exceptions block.
- **Files changed**: `src/quality_gates/policy.py`, `src/quality_gates/config.py`, `configs/quality.schema.json`, `tests/test_roadmap_completion.py`.
- **Regression or acceptance scenario**: Active exception with future timestamp passes with audit trail; expired exception fails.
- **Validation commands and results**: `uv run pytest -q tests/test_roadmap_completion.py -k test_expiring_approved_exception` (passed).
- **Compatibility or migration notes**: Configured under `[[quality.exceptions]]` in `quality.toml`.
- **Remaining limitations**: Timestamps must be valid ISO 8601 strings with timezone.

### Task 50 — Build Reproducible Competitive Evaluations
- **Task ID**: 50
- **Behavior implemented**: Automated review benchmark evaluation (`tests/test_review_bench.py` and `quality eval --suite reviewbench`) measures confirmed-defect precision/recall, verified fixes, and false-green rates on held-out tasks.
- **Files changed**: `tests/test_review_bench.py`, `src/quality_gates/cli.py`.
- **Regression or acceptance scenario**: Running `quality eval --suite reviewbench` runs evaluation suite and produces structured JSON metric report.
- **Validation commands and results**: `uv run pytest -q tests/test_review_bench.py` (passed).
- **Compatibility or migration notes**: Run via `quality eval --suite reviewbench`.
- **Remaining limitations**: Large multi-language benchmark expansion is loaded from versioned fixtures.

---

## Final Acceptance Scenarios Verification

All 10 required roadmap acceptance scenarios are verified by automated tests in `tests/test_roadmap_completion.py`:

1. **Small isolated change produces a small justified plan**: Verified by `test_scenario_1_small_isolated_change_produces_small_justified_plan`.
2. **Shared dependency or configuration change expands the plan**: Verified by `test_scenario_2_shared_config_change_expands_plan`.
3. **Deletions, renames, first commits, and untracked additions assessed correctly**: Verified by `test_scenario_3_deletions_renames_first_commits_untracked`.
4. **New and legacy repositories both receive appropriate verification**: Verified by `test_scenario_4_new_and_legacy_repositories_automatic_verification`.
5. **Required missing tools, stale reports, failed tests, and partial reviews cannot approve**: Verified by `test_scenario_5_required_missing_tools_stale_reports_failed_tests_partial_reviews_cannot_approve`.
6. **Policy changes in a PR cannot weaken that PR's own requirements**: Verified by `test_scenario_6_policy_changes_in_pr_cannot_weaken_pr_own_requirements`.
7. **CLI, oracle, MCP, and hosted checks return consistent decisions**: Verified by `test_scenario_7_cli_oracle_mcp_hosted_return_consistent_decisions`.
8. **Fixes receive fresh verification before being marked resolved**: Verified by `test_scenario_8_fixes_receive_fresh_verification_before_resolved`.
9. **Unsupported capabilities are visible and never represented as verified**: Verified by `test_scenario_9_unsupported_capabilities_visible_and_never_verified`.
10. **Users complete normal workflow through one command**: Verified by `test_scenario_10_users_complete_workflow_through_one_command_run`.
