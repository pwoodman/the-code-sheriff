# Changelog

## 1.15.0

- Clean-code craft checks on the diff and in audit (check 48): swallowed
  exceptions, bare `except:`, repeated unnamed literals, long functions, and
  nests five or more levels deep. Thresholds are evidence-backed, not 4-line
  dogma. Default review rule: `.quality/rules/clean-code.md`.
- Oracle returns a **playbook** (one Next action, autofix first) and a
  **merge certificate**. `quality certify` / MCP `quality_certify` is the
  auto-merge signal: `auto_merge: ready` only when every required gate is
  green and no review threads remain.
- `quality fix` (MCP `quality_fix`) applies format `--write`, `ruff --fix`,
  and finding patches. `quality apply --id` applies one patch. Agents should
  autofix before hand-editing.
- Setup writes Copilot / VS Code / Gemini / Claude instruction files plus the
  clean-code rule. `quality setup --auto-merge` enables GitHub repo auto-merge
  so a required Sheriff check can land the PR.

## 1.14.0

- `quality setup` writes Cursor/Claude MCP (`.cursor/mcp.json`, `.mcp.json`),
  an always-on Cursor rule, and a project skill so coding agents loop on
  `quality oracle` before commit. Use `--no-agents` to skip.
- Review ingests `AGENTS.md`, `CLAUDE.md`, `.cursorrules`, and `.cursor/rules`
  as the same markdown rules as `.quality/rules/` (`ingest_agent_files`, on by
  default). The files the agent reads are the files enforcement checks.
- `quality merge` dry-merges HEAD into the base branch with `git merge-tree`
  (no working-tree mutation). Textual conflicts fail the merge gate. Locally,
  a clean merge then compile/impact-checks the merged tree (`verify = "auto"`).
  `--siblings` also merge-trees other open PR heads.
- `quality comments` and MCP `quality_pr_comments` list unresolved GitHub
  review threads (Greptile, BugBot, humans). The oracle treats them as remaining
  work. Resolved Sheriff comments are remembered so review does not re-raise them.
- GitHub check annotations pin to the failing source file (and a job
  summary table) instead of `.github:N Process completed with exit code 1`.
- Format reports the path from ruff's `--> file:line` diagnostic (and older
  `Would reformat:` lines), not the `File would be reformatted` title. DRY
  ignores generated Cursor/Claude skill copies (same template, two IDE paths).
- Repository is public MIT: https://github.com/pwoodman/the-code-sheriff

## 1.13.0

- Cheap AI review by default: skip LLM on lockfiles/docs/generated, Haiku/GPT-4.1-mini
  on typical PRs, Sonnet only on risky diffs. Incremental hunk review on later commits.
- Regex gate (`quality regex`) with built-in unsafe-API rules plus `[[quality.regex.rules]]`.
- Package gate (`quality packages`): known-risky imports/deps (typosquats, malware
  incidents, abandoned crypto) and undeclared third-party imports, for languages
  that actually import packages. CVE lockfiles stay with osv-scanner.
- Source changes require a test file (`[quality.test] require_for_source`); ignore with
  `# quality:ignore` or `quality ignore add`.
- Last-run findings persist in `.quality-reports/findings-last.json` and reopen if the
  snippet is still in the tree.
- Test timing: compare touched tests to the last recorded duration (default 15% slower)
  and accept a new baseline with `quality timing accept`.


## 1.12.0

- GitHub repository is **pwoodman/the-code-sheriff** to match The Code Sheriff.
- Security gate now covers CodeAnt-class PR defense: Trivy IaC/secrets, optional
  Checkov, CycloneDX/SPDX SBOM (`quality sbom`), OWASP/CWE, EPSS when present,
  and steps of reproduction. Default `github_gates` include **security**.
- Review `--post` writes the AI summary onto the pull request description.
- This repository dogfoods the same **The Code Sheriff** check consumers get
  (`sheriff.yml` calls the reusable `quality.yml`).

## 1.11.0

- Product name is **The Code Sheriff**. CLI remains `quality`; `codesheriff`
  is an alias. The durable required check is **The Code Sheriff**. Compute
  runs on each installed repo's Actions minutes.
- `quality setup` is the whole install: default config, pinned workflow, git
  hooks, required check via `gh`, and a first baseline. The GitHub App is
  optional (`quality github-app register`).

## 1.10.0

- MATLAB removed; Elixir (`mix` / Credo) added as the replacement language profile.
- Conformance fixtures, weekly Java/PHP/Ruby fixture jobs, and IaC/contract file kinds (Terraform, Kubernetes, Helm, protobuf, GraphQL).
- Typecheck (mypy/pyright when a project config exists), extra test runners, CMake/Meson compile, proto/GraphQL contract diffs, Trivy + optional license allow-list.
- Report history / `quality report --diff`, HTML filters, `quality watch`, Ollama review, ReviewBench cases, editor diagnostics, GitHub App-lite docs, and optional bwrap / plugin subprocess isolation.

## 1.9.0

- Delivery of the 50-task quality platform roadmap across 5 phases.
- Trust foundations: explicit execution states, unified decision evaluation, independent test gating, attributable coverage binding, and protected PR merge policies.
- Execution planning: immutable change manifest, dependency-aware task DAG, scoped adapter execution, incremental persistent impact graph, and workspace boundary support.
- Verification breadth: breaking schema contract checks, risk-triggered verification (migrations, authorization, resilience, mutation, performance), and new project smoke test onboarding.
- AI Review & Universal Integrations: specialist review routing, diff-context validation, review budget tracking, persistent finding ledger, transactional patch verification, and published capability support matrix.

## 1.8.0

- Findings now carry a full resolution contract (reason, snippet, suggestion,
  optional patch, verify command, docs) through console, HTML, SARIF, oracle,
  MCP, and GitHub. Inline comments emit apply-able `suggestion` fences when a
  patch is present. MCP adds `quality_finding_context` and `quality_apply_fix`.
- Rule help covers common ruff, ESLint, clippy, gitleaks, and osv-scanner ids
  in addition to yamllint/version. Generic "open the file" is last resort.
- ReviewBench: 15+ labeled positives, 8+ hard negatives, volume cap, and
  `quality eval --suite reviewbench` CI scorecard. Closed-loop apply-and-recheck
  for patches. Optional impact-selected test evidence and function-level
  neighbors around the diff.
- Third-party eval: Macroscope's 118-bug JSON is not public; we reconstruct
  their published commons-math GCD sample and fetch Martian's MIT Code Review
  Bench goldens (`quality eval --suite martian --download`) for an apples-to-apples
  comparison against the same PRs those vendors already scored.


## 1.7.2

- GitHub Models was retired on 2026-07-30. Auto review no longer calls
  `models.github.ai` with `GITHUB_TOKEN` (that produced HTTP 410 and fell
  back to heuristics). Set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` for LLM
  review; `github-models` in config now means heuristic-only.
- Default Anthropic model is `claude-sonnet-4-6` (`claude-sonnet-4-20250514`
  was retired 2026-06-15 and returned HTTP 404). Override with
  `ANTHROPIC_MODEL` or `quality.review.model`.
- Split HTML report rendering out of the formats module. Large-file review
  uses the same 800-line floor as the audit god-file check.

## 1.7.1

- Dogfood on this repo: skip unknown hidden/tool dirs, ignore function-level
  Python imports when reporting cycles, skip unsafe-API hits in detector
  catalogs/docs/tests/fixtures, and measure large-PR size on production source.
- Split the HTML/JSON report module under the god-file limit and break
  diagnostics/MCP import cycles that self-audit reported as P1.

## 1.7.0

- AI review now packs impact, audit, and security context plus related files
  from the import graph, instead of sending a truncated diff to a single LLM
  call. Findings are JSON, style nits are dropped, and `.quality/rules/*.md`
  custom rules (optional path globs) apply to the change set.
- PR posting writes inline review comments at path:line and a `quality-review`
  GitHub check run. `quality oracle` and `quality mcp` let coding agents loop
  until mechanical gates are green. Optional ensemble majority-vote and a
  validator pass; resolution rate is recorded vs the previous review.json.

## 1.6.0

- Failure reports now include what failed, where (path:line:column plus a source
  snippet), why, and a concrete fix, plus redacted command / working-directory /
  exit-code context across console, JSON, HTML, Markdown, SARIF, JUnit, and
  annotations. Common yamllint, ruff, and version rules get targeted help.

- Deterministic, atomic result cache for parse/format/lint profile adapters,
  bounded parallel profile execution, stable result ordering, and cache
  status/clean commands. Builds, tests, review, and security scans stay uncached.
- Versioned JSON report, audit, coverage, and baseline formats; bundled report,
  audit, and baseline schemas; SARIF 2.1.0 and JUnit XML exports.
- Cross-platform Python 3.11–3.14 CI, scheduled representative toolchain
  fixtures, wheel-content checks, SHA-pinned Actions, trusted PyPI publishing,
  GitHub release provenance, and open-source SPDX SBOM/license artifacts.
- Automatic downloads now require a manifest platform artifact with a verified
  SHA-256. Unverified binary and Python-package installers report unsupported;
  project-local Node tooling continues to use `npm ci` and its lockfile.
- Added security, privacy, contribution, conduct, third-party, compatibility,
  plugin, and troubleshooting policies; clarified that builds can execute
  project plugins and scripts and that broad registry support is experimental.

## 1.5.1

- Security gate skips (and therefore blocks compile) when gitleaks, osv-scanner,
  and semgrep are all missing — language notes no longer turn that into a pass.
- `--only` / `--skip` reject unknown gate names instead of dropping them.
- `tools.run` decodes subprocess output with replacement so non-UTF8 stdout
  cannot crash a gate.
- Audit check 68 is runtime (not a silent pattern pass). JWT `algorithms=`
  allowlists are no longer flagged; long-running work matches on word boundaries.
- Surface needles no longer treat `select =`, `password`, `zipfile`, or scanner
  source as an auth/SQL/upload app. Self-scan on this toolkit stays `ci`/`deps`.
- Pin GitHub Actions to commit SHAs; drop unused `master` workflow triggers;
  unit-test CI fails under 50% combined coverage; this repo’s line floor is 55.
- Scorecard report after every run: performance (coverage, duplication, impact,
  audit, gate timings), issues, and recommended next commands. Writes
  `.quality-reports/quality-report.md` + `.html`. Reprint with `quality report`.
- HTML/markdown reports nest skip reasons, issues-by-gate, and recommendations;
  coverage gets a meter vs the 80% industry floor.
- Local-mode GitHub Actions no longer lists the ten heavy jobs as skipped —
  they live in `quality-full.yml` and only run when opted in.
- Default `github_gates` now include **format** and **lint** (cheap, should
  always run on PRs). This toolkit’s `quality.toml` uses `ci.mode = "both"` so
  detect / DRY / security / compile / coverage run on GitHub too. Compile and
  UI still self-skip when they do not apply (Python-only / no Playwright).

## 1.5.0

- Policy layer so old repos are not blocked on first install:
  `observe` (report only), `adopt` (fail on new fingerprints / coverage drop vs
  a committed `.quality-baseline.json`), `enforce` (current fail_on behavior).
- `quality baseline` / `quality baseline --ratchet`, `quality init --policy`,
  `QUALITY_POLICY` / `--policy`, optional PR digest comment.
- Consumer `quality init` writes an adopt-mode toml instead of copying this
  toolkit's strict config.

## 1.4.1

- Version gate no longer crashes when a binary file (for example `.coverage`)
  sits in the tree. Only version candidates are read, and decode errors are skipped.
- Self-scan: ignore the audit package when classifying HTTP/API surfaces; do not
  treat `subprocess.run` or a `todo` rule name as long-running work / placeholders.

## 1.4.0

- Coverage gate: configurable line/branch floors. Default **80% line coverage**
  (industry / ISTQB-style baseline); branch coverage off unless set. Collects
  pytest-cov, Jest/Vitest summary, Go coverprofile, or existing XML/LCOV.
  Skip ≠ fail when there are no tests or no tool. Heavy — stays off default
  GitHub `github_gates`.
- Audit gate: 120-point evidence-backed inspection (security, API, architecture,
  incomplete AI implementations, persistence, performance hints, frontend, UX).
  Only HIGH-confidence static evidence becomes a defect. Default fail-on is P0.
  Not applicable when the repo has no HTTP/frontend surface. Cheap — included
  in default `github_gates`.
- Gate order: format → lint → DRY → security → compile → impact → coverage →
  audit → UI → version → review.

## 1.3.0

- Impact gate: upstream (imports) and downstream (importers) analysis on the
  git diff. Fails when a downstream consumer was not updated and no test covers
  the change. Broken in-repo imports fail. Report: `.quality-reports/impact.json`.
- UI selection now expands the diff with downstream importers, so a util change
  still runs specs that visit pages that consume it.
- Cheap GitHub Actions path includes `impact` (no browsers).

## 1.2.1

- UI selection is **touch-scoped**: a spec runs only if the diff hits the spec,
  its imports, a page it visits (and that page's imports), or a coverage map
  entry. Filename guesses like `checkout.spec.ts` ↔ `Checkout.tsx` no longer
  pull in unrelated tests. Root `app/layout` / `_app` still runs the full suite.

## 1.2.0

- UI gate: selective Playwright/Cypress. Only specs that cover added or changed
  files run (spec itself, imports, route `goto`/`visit`, name/path, optional
  coverage map). Shared config changes run the full suite; unrelated diffs skip.
- UI stays **off GitHub Actions** by default even when `ci.mode` is `github` /
  `both` — browser installs are the expensive part. Opt in with
  `[quality.ui] on_github = true` or `QUALITY_UI_ON_GITHUB=1`.
- Pre-push now includes `ui` after compile. Skip ≠ fail when no UI project exists.

## 1.1.0

- Version gate: semver consistency, required bumps on source changes, `quality bump`.
- Compile gate for C#, Rust, Go, Java, and TypeScript — only after a clean security scan.
- Local-first CI (`[quality.ci] mode = "local"`): heavy gates run on developer machines; GitHub Actions stays cheap unless you set `github` / `both` or dispatch `full_suite`.

## 1.0.0

- Initial format, lint, DRY, security, and AI review gates.
