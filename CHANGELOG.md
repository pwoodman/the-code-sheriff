# Changelog

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
