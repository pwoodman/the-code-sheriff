# Poly-check: 50 changes for an automatic, change-aware quality platform

Review target: local checkout `272cf7e`, September 4, 2026.

## Product direction

Make the promise: **One entry point that discovers the project, understands the change, runs the necessary checks, explains the evidence, and produces one trustworthy merge decision.** Users should not need to know which skills, scanners, reviewers, or test runners to invoke.

Build on `quality run`, the capability registry, impact analysis, UI selection, policy baselines, reports, AI review, oracle, and MCP interface already present. The main opportunity is connecting these features through one execution plan and making their conclusions reliable.

“Only run based on changes” should mean **changed files plus their affected dependencies, consumers, contracts, configuration, and tests**. Checking only edited lines misses regressions. Initial onboarding may need one inventory/baseline operation; subsequent runs should update that knowledge incrementally. A shared configuration change can legitimately affect the entire repository. If impact cannot be established, expand to the smallest safe scope or report incomplete verification.

No reviewer can guarantee that all accepted code is correct. The enforceable promise is that every required check for the assessed change has fresh, successful evidence, with no unresolved blockers or unexplained verification gaps.

## What the review established

The code already provides substantial breadth. These recommendations distinguish **Fix** (observed behavior that undermines the goal), **Extend** (strengthen an existing capability), and **Add** (a proposed capability).

The focused policy, impact, coverage, review, and phase-three tests passed. Additional isolated Python probes reproduced baseline fingerprint collisions, ratchet absorption of new findings, false-green oracle results, acceptance of coverage after a nonzero pytest result, and a passing review gate containing an error. Those probes used temporary directories and mocked execution; they are not end-to-end deployment tests. Source inspection covered orchestration, configuration, caching, reporting, patch application, and CI. A temporary structural graph mapped 65 source files to 741 nodes and 2,419 edges; its traversal was navigation assistance, not proof of runtime behavior.

Priorities: **P0** = correctness/trust blocker; **P1** = core product requirement; **P2** = breadth and differentiation. Sequence within a priority should follow dependencies, not just item number.

## Make the merge decision trustworthy

1. **P0 · Fix — Give every execution state an explicit merge meaning.**
   `cli._emit` blocks only `status == "fail"`; the broader adapter vocabulary includes unsupported and tool-error states. Define a typed state model separating passed, failed, not applicable, unsupported, blocked, errored, and cancelled. **Done when:** a missing required compiler or crashed scanner prevents approval, while a genuinely irrelevant gate does not.

2. **P0 · Fix — Make the oracle evaluate plan completeness.**
   `oracle.remaining_from_results` derives green from error findings attached to failed gates. A skipped coverage gate or failed compile gate without findings can therefore produce green. Use the same decision evaluator as the CLI and CI. **Done when:** partial, failed, stale, or missing required results cannot produce green through any interface.

3. **P0 · Fix — Separate test success from coverage percentage.**
   `gates.coverage._pytest_cov` can parse a coverage file after pytest exits nonzero, and the gate subsequently evaluates the percentage. Record execution outcome independently and enforce it for every runner. **Done when:** a failing assertion blocks even at 100% coverage; collection failures, timeouts, and zero discovered tests remain distinct outcomes.

4. **P0 · Fix — Require fresh, attributable coverage artifacts.**
   `gates.coverage._collect` can fall back to existing reports without proving they describe the current tree. Store artifacts per run with source, configuration, test selection, and environment digests. **Done when:** an old coverage file cannot satisfy a changed tree, and aggregation cannot mix unrelated runs or silently double-count overlapping reports.

5. **P0 · Fix — Make configured AI review blockers actually block.**
   `review.engine.run_review` always returns a passing gate, including when it contains error findings; adding review to `fail_on` does not fix that CLI result. Derive its decision from the configured evidence/severity policy. **Done when:** an eligible blocking finding fails CLI, oracle, and hosted checks consistently; advisory review remains an explicit supported mode.

6. **P0 · Fix — Identify individual baseline defects.**
   `policy.fingerprint` uses only gate, rule, and path, so a second defect under the same rule in the same file can be grandfathered. Add a stable symbol/context identity and occurrence matching resilient to line shifts. **Done when:** moving an old finding preserves its identity, but introducing another occurrence still blocks.

7. **P0 · Fix — Make baseline ratcheting remove debt.**
   `policy.write_baseline(..., ratchet=True)` unions old and current fingerprints, retaining repaired defects and absorbing new ones. Ratchet only previously accepted findings that are still present; never automatically accept new findings. **Done when:** fixing a defect removes its exemption, reintroducing it blocks, and a new defect cannot enter through a ratchet operation.

8. **P0 · Fix — Distinguish adoption setup from successful enforcement.**
   `policy.apply_policy` demotes failures when adopt mode has no readable baseline; malformed JSON also loads as no baseline. Represent onboarding as report-only and treat a damaged expected baseline as a configuration error. **Done when:** deleting or corrupting the baseline cannot turn a blocking PR green, while intentional first-time onboarding remains usable.

9. **P0 · Extend — Protect the policy that approves the change.**
   Evaluate merge-critical trust settings, required gates, baseline changes, exclusions, and suppressions against policy from the trusted base or organization control plane. Let a PR propose changes without authorizing itself. **Done when:** a PR cannot disable its own security check, promote itself to trusted execution, or grandfather its new defects through configuration edits.

10. **P0 · Fix — Require actual consumer validation.**
    `impact_graph.analyze` treats a changed consumer or a matching/importing test as sufficient validation. Test existence is useful selection evidence but does not establish execution or correctness. **Done when:** affected consumers have current successful tests, compatible contract evidence, or an explicit approved exception; editing a consumer alone never counts as validation.

11. **P0 · Fix — Enforce trust in every execution path.**
    `review.evidence.collect_test_evidence` can run pytest/Vitest when enabled without checking `config.trust`, unlike the coverage runner. Centralize execution authorization and enforce it below CLI, MCP, review evidence, and plugins. **Done when:** enabling an optional reviewer cannot execute an untrusted repository's tests or install packages outside the authorized environment.

12. **P0 · Fix — Make the required CI summary reject missing work.**
    `.github/workflows/quality.yml` accepts `skipped` for jobs in its selected blocking set. Require success from jobs the plan actually selected, and distinguish intentionally unselected jobs. Add merge-queue event support and bind the decision to the tested merge candidate. **Done when:** a skipped required job or superseded commit cannot satisfy the required check.

## Make execution automatic and genuinely incremental

13. **P1 · Extend — Turn `quality run` into the universal automatic entry point.**
    Discover capabilities, calculate impact, choose checks, execute them, reconcile findings, and emit the decision without requiring users to select skills or gates. Keep individual commands for diagnosis. **Done when:** the same ordinary command handles a new Python app, an existing web service, and a mixed-language repository with appropriate plans.

14. **P1 · Add — Create one immutable change manifest.**
    Replace divergent diff collection in `gitutil`, `detect`, and `review.context` with a shared manifest containing base SHA, target SHA/tree digest, changed hunks, old/new paths, and change kinds. **Done when:** CLI, impact, tests, review, and reports all assess precisely the same snapshot.

15. **P0 · Fix — Include deletions, untracked additions, and first commits.**
    Explicit-base diff filters in `gitutil` and `review.context` exclude deletions; default collection strategies also differ. Handle deleted symbols, renames, staged/unstaged/untracked files, and repositories without `HEAD~1`. **Done when:** deleting an imported module or adding an untracked source file triggers relevant checks before commit.

16. **P0 · Fix — Distinguish an empty diff from failed diff discovery.**
    Some paths collapse missing bases, Git failures, or missing upstream state into absent change data; impact/UI can then skip. Return structured discovery states, and handle shallow clones and invalid references explicitly. **Done when:** a genuine no-op does no work, while an unknown comparison cannot masquerade as a safe no-op.

17. **P1 · Add — Build one dependency-aware execution planner.**
    Replace orchestration decisions scattered across CLI branches with a DAG whose nodes declare inputs, prerequisites, applicability, outputs, trust, and requiredness. Schedule independent work concurrently within resource limits. **Done when:** selecting compile automatically includes required prerequisites, and each check has a machine-readable explanation of why it runs.

18. **P1 · Fix — Pass actual changed scopes into every adapter.**
    `quality run --changed` influences language resolution, while format/lint enumerate project files internally. Carry explicit file, package, and target scopes through `AdapterContext` and mature handlers. **Done when:** changing one isolated Python file does not reformat or relint every Python file, except where the tool requires a documented broader scope.

19. **P1 · Extend — Persist and incrementally update the impact graph.**
    Reuse parsed files and update edges for changed/deleted/renamed files instead of rebuilding the graph independently for impact, UI, and review. Version the index with parser and resolver inputs. **Done when:** unchanged source is not repeatedly parsed, and deleted edges disappear without requiring a manual reset.

20. **P1 · Extend — Add symbol and contract edges.**
    Extend import-level impact with callers, exports, inheritance, public types, schemas, and generated-client relationships where language tooling supports them. Track confidence and unresolved edges. **Done when:** changing a public parameter or return shape selects affected callers, including consumers that did not themselves change.

21. **P1 · Add — Treat configuration as an impact source.**
    Map compiler flags, lockfiles, dependency manifests, environment schemas, test fixtures, code generators, and shared CI settings to affected targets. Extend the existing UI shared-configuration rule across the pipeline. **Done when:** changing a dependency or compiler option rechecks its consumers despite unchanged source files.

22. **P1 · Add — Plan at workspace and package boundaries.**
    Discover nested projects, package-manager workspaces, build roots, and cross-package dependencies. Resolve tools and configuration per package instead of assuming one root-level project. **Done when:** a JavaScript frontend change avoids unrelated Python jobs, while a shared API schema change schedules both producer and consumer checks.

23. **P0 · Fix — Complete deterministic cache invalidation.**
    `result_cache.cache_key` hashes input files, `config.raw`, profile, capability, and tool version, but does not independently include every external tool configuration or runtime input. Include effective config contents, relevant lockfiles/plugins, executable identity, engine version, and declared environment inputs. **Done when:** editing only an applicable linter configuration invalidates the previous pass.

24. **P1 · Add — Make uncertainty and incremental savings visible.**
    Report selected targets, exclusion reasons, reused evidence, impact uncertainty, fallback scope, and actual execution counts. Offer a dry-run explanation of the plan. **Done when:** users can inspect why a shared change widened execution, and measurement demonstrates reduced work without unexplained gaps in required coverage.

## Verify behavior across new and existing projects

25. **P1 · Add — Introduce a first-class test execution gate.**
    Coverage currently carries much of the test-running responsibility. Model unit, integration, contract, and end-to-end results independently, then consume coverage as a separate measurement. **Done when:** a project without a coverage plugin can still prove its affected tests pass, and test failures remain blocking under baseline policies.

26. **P1 · Add — Select tests across all supported runners.**
    Generalize selective UI execution to unit and integration tests using native affected-test features, import/call graphs, fixtures, and collected runtime mappings. Respect adapter granularity: some runners require an affected package or suite. **Done when:** a small change runs the smallest justified test set, with no-match uncertainty triggering a documented fallback rather than silent success.

27. **P1 · Add — Measure coverage of changed behavior.**
    Add changed-line and changed-branch coverage, including newly added files, alongside repository baselines. Treat aggregate coverage as supporting information, not the sole acceptance criterion. **Done when:** a large well-covered codebase cannot conceal an untested new authentication branch behind its overall percentage.

28. **P1 · Extend — Give new repositories an automatic readiness path.**
    When there is no history or test setup, detect the stack, identify required tooling, and propose the minimal smoke test and verification configuration as a patch. Installation remains a deliberate setup action. **Done when:** an empty/new project gets clear first-run requirements and executable checks, instead of a collection of passing skips.

29. **P1 · Extend — Adopt legacy projects without accepting new defects.**
    Inventory existing debt once, baseline attributable static findings, and require fresh execution success plus change-specific checks afterward. Avoid repository-wide coverage/version/style requirements unrelated to the patch. **Done when:** a small safe fix can merge in a legacy repository, while a newly introduced bug cannot hide behind historical debt.

30. **P1 · Add — Check API and schema compatibility.**
    Diff public APIs, OpenAPI/GraphQL/protobuf contracts, exported types, and package interfaces; test affected consumers or require a declared migration. **Trigger:** public-contract changes. **Done when:** removing a required response field catches a dependent client failure even when the server's own tests still pass.

31. **P1 · Add — Verify database migrations in disposable environments.**
    Evaluate affected migrations for destructive operations, lock risk, compatibility with old/new application versions, and forward recovery. Run against representative schemas when authorized. **Trigger:** migrations or persistence-model changes. **Done when:** a migration that breaks the currently deployed application blocks with reproducible evidence.

32. **P1 · Add — Verify authorization and tenant boundaries.**
    Select negative tests for changed permissions, authentication middleware, resource ownership, and tenant filters. Test denied operations and cross-tenant access as well as happy paths. **Done when:** removing an ownership check fails an executable negative test rather than depending only on a reviewer's suspicion.

33. **P2 · Add — Verify failure handling and state transitions.**
    For affected payment, queue, persistence, and async paths, select tests for retries, idempotency, partial failure, cancellation, timeout, and concurrent updates. Use explicit project contracts to decide expected behavior. **Done when:** duplicate delivery or a failed intermediate operation cannot silently produce duplicate effects or invalid state.

34. **P2 · Add — Support risk-selected property and mutation testing.**
    Use these checks for changed parsers, validation logic, algorithms, and critical invariants where configured budgets justify them. Restrict mutations to changed/affected behavior. **Done when:** tests must detect representative broken variants; merely executing the changed line is insufficient evidence of assertion quality.

35. **P2 · Extend — Select UI behavior, accessibility, and visual checks together.**
    Build on existing Playwright/Cypress selection to choose affected routes, components, keyboard flows, accessibility assertions, and visual snapshots. Separate expected appearance changes from functional failures. **Done when:** a shared component change exercises its affected screens, while an unrelated backend patch schedules no browser work.

36. **P2 · Add — Gate measurable performance regressions.**
    Map changed hot paths to project-defined latency, allocation, query-count, bundle-size, or startup budgets. Use comparable environments and repeated measurements with explicit variance handling. **Done when:** a relevant regression blocks with a reproducible comparison, and timing noise does not create flaky merge failures.

## Make AI review evidence-driven and fixes verifiable

37. **P1 · Add — Automatically select specialized review checks.**
    Use change classification to choose correctness, security, API, database, concurrency, frontend, or infrastructure reviewers behind the same entry point. These are internal capabilities, not skills users must invoke. **Done when:** a migration activates database review automatically and a documentation edit avoids unrelated specialists.

38. **P1 · Extend — Verify findings with code context and reproducible evidence.**
    `review.llm.validate_findings` currently receives finding summaries rather than the relevant source/diff evidence. Give validation the actual changed context and use compiler results, counterexamples, or targeted reproducers where possible. **Done when:** blocking claims identify a trigger, consequence, location, and verification basis; reviewer agreement alone is not treated as proof.

39. **P1 · Fix — Account for every changed hunk under review budgets.**
    `review.context.compact_diff` truncates data to fit limits. Partition large changes into tracked review units and report which units were assessed. **Done when:** exceeding a token/file budget yields an explicit partial review or scheduled remainder, never an apparently complete review of only the first portion.

40. **P1 · Extend — Separate repository content from review authority.**
    Treat comments, docs, retrieved files, and PR-added rules as untrusted evidence; source merge policy from trusted configuration. Apply source allowlists and secret redaction before provider transmission, with configurable local/private execution. **Done when:** a source comment telling the reviewer to ignore a bug cannot change policy or authorize extra tools.

41. **P1 · Add — Maintain one finding ledger across tools and commits.**
    Correlate equivalent scanner/reviewer findings by defect identity, retain supporting evidence, and track open, verified-fixed, suppressed, and not-rechecked states. Replace disappearance-based resolution in `review.resolve`. **Done when:** an issue omitted from a later model response stays open until its relevant verification establishes resolution.

42. **P0 · Fix — Apply patches transactionally against expected source.**
    `review.apply` replaces matching text incrementally and can apply some hunks before others fail. Validate the full patch against an expected tree digest, stage it in isolation, and apply atomically only when all hunks match. **Done when:** stale or ambiguous patches leave the original tree untouched, including multi-file and repeated-text cases.

43. **P1 · Extend — Make fix verification run automatically.**
    `apply_and_check` compares against a caller-provided finding list; it does not itself run verification. After an authorized fix, invalidate affected evidence and execute the new plan. **Done when:** “verified fixed” requires fresh relevant checks, the original defect's verification, and no new blocking regressions; the loop has bounded attempts and a clear unresolved outcome.

## Deliver a universal product and prove its quality

44. **P1 · Extend — Certify adapter capabilities rather than counting languages.**
    Publish tested support by language, framework, platform, and capability: parsing, formatting, linting, security, build, tests, coverage, and impact. Add conformance fixtures for failure propagation and change selection. **Done when:** an experimental syntax checker cannot be mistaken for complete behavioral verification of that language.

45. **P1 · Extend — Make plugins declare enough information for safe orchestration.**
    Extend the existing adapter API with input scope, prerequisite graph, tool/config identity, output schema, execution permissions, applicability, and cacheability. Run third-party adapters in isolated worker processes where feasible. **Done when:** adding a plugin integrates automatically into planning and reporting without letting a crash terminate or falsify the entire run.

46. **P1 · Add — Use managed, isolated execution for untrusted changes.**
    Provide ephemeral workers with pinned tools, restricted secrets/network access, resource limits, and controlled artifact export. Keep analysis credentials outside project execution. Remove opportunistic `npx --yes` installation from verification paths in favor of resolved tools. **Done when:** fork PRs can obtain real test evidence without running their code inside a credential-bearing reviewer process.

47. **P1 · Add — Provide one-click installation and one durable PR check.**
    Package automatic onboarding, webhook-driven review, and a stable required check through a GitHub App; keep CLI/MCP parity and define a provider interface for other Git hosts. **Done when:** connecting a repository starts automatic change-aware checks without users assembling workflows or manually chaining commands.

48. **P1 · Add — Verify local evidence before accepting it remotely.**
    Preserve local-first cost savings, but bind reusable results to source, policy, tools, environment, and an authenticated approved runner identity. Plain local report files are not sufficient merge evidence. **Done when:** CI either verifies suitable attestations or reruns the required work on a trusted worker; bypassing a local hook cannot satisfy the gate.

49. **P1 · Extend — Make policy flexible through explicit, auditable exceptions.**
    Support organization defaults, repository/package overrides, ownership, suppression reasons, expiration, and approval rules without allowing PR authors to relax their own requirements. Show the effective policy and every exception in the report. **Done when:** teams can handle legacy or unsupported situations deliberately, while exceptions expire and cannot silently expand to future defects.

50. **P1 · Extend — Prove competitive quality with reproducible evaluations.**
    Expand `quality eval` with real regressions, hard negatives, multi-language changes, deletions, configuration-only changes, faulty caches, and misleading execution results. Measure confirmed-bug precision/recall, false-green rate, selection misses, false blocking, time, cost, and verified fix success. **Done when:** superiority claims are supported by matched, versioned comparisons on held-out tasks with documented settings and uncertainty.

## Suggested delivery sequence

**First: make green trustworthy.** Address the P0 items, starting with test exit propagation, oracle completeness, review status, baseline semantics, and fresh evidence. Add focused regression cases for the reproduced failures before changing behavior.

**Next: unify change understanding.** Deliver the shared change manifest, planner, scoped adapter contract, configuration impact, and persistent graph. Every interface should consume the same plan and decision model.

**Then: make behavioral verification automatic.** Add affected test execution, changed-branch coverage, new/legacy onboarding, and risk-selected contract/security checks. Extend capability breadth only with conformance evidence.

**Finally: scale distribution and differentiation.** Add hosted installation, verified local execution, broader adapters, advanced reviewers, and measured competitive evaluations. Keep the user-facing interaction centered on one command or one PR check throughout.

## Competitive context and positioning

Greptile documents whole-codebase review context and repository understanding. CodeRabbit documents automatic review and incremental reviews on subsequent commits. Cursor documents automated Bugbot review and manual/API triggers. These capabilities are competitive expectations, not sufficient differentiation by themselves. Sources: [Greptile introduction](https://www.greptile.com/docs/introduction), [CodeRabbit review overview](https://docs.coderabbit.ai/guides/code-review-overview), [Cursor Bugbot documentation](https://prod.cursor.com/docs/bugbot).

The recommended positioning is **automatic, evidence-backed verification of the affected system, from local development through merge**. That is a proposed direction, not a finding that competitors lack execution features or that Poly-check already outperforms them. The reviewed checkout has not established that comparative result.

The strongest success criterion is: **a small change causes a small justified verification plan; a risky shared change expands the plan appropriately; and no missing, stale, failed, or unverified required work is described as a pass.**
