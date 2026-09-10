# The Code Sheriff

Project home: https://github.com/pwoodman/the-code-sheriff

Polyglot **format → lint → DRY → security → compile → impact → coverage → audit → UI → version → merge → AI review**
gates. CLI: `quality` (alias: `codesheriff`). Heavy work defaults to **your machine**. GitHub Actions stays cheap unless
you opt in. One command on a new repo:

```bash
uvx --from git+https://github.com/pwoodman/the-code-sheriff.git quality setup
```

That also drops Cursor/Claude MCP, an always-on rule, and a skill so the agent
loops on `quality oracle` until green. `--no-agents` skips those files.

The GitHub App is optional; see [`docs/GITHUB_APP.md`](docs/GITHUB_APP.md).
PR comment commands use the `/sheriff` prefix (`/sheriff review`, `/sheriff help`).
The 100-item reviewer checklist is in [`standards/REVIEWER_COVERAGE.md`](standards/REVIEWER_COVERAGE.md).

| When | What | Where |
| --- | --- | --- |
| `git commit` | format, lint, version | your device |
| `git push` | DRY, security, compile, impact, coverage, audit, selective UI | your device |
| Push / PR on GitHub | format, lint, regex, packages, security, impact, audit, version, merge, PR review | Actions |
| Optional | full suite on Actions | `ci.mode = "both"` / `"github"`, or workflow **full_suite** |
| Optional | Playwright/Cypress on Actions | `[quality.ui] on_github = true` |

That split saves runner minutes. Hooks are the contract; Actions in `local` mode
runs the cheap PR gates (format, lint, regex, packages, security, impact, audit, version, merge, review, comments).
Browser UI tests stay off GitHub even in `github`/`both` mode unless you turn them on.

## Vibe coding / agent loop

Pandorian-class tools govern **after** a PR exists, for leadership. The Code
Sheriff sits **in the agent loop**, on your machine, before commit:

```bash
quality oracle --run --prompt   # or MCP quality_run → quality_oracle
# fix remaining blockers (including merge conflicts and PR review comments)
quality oracle --run            # until green is true
```

`quality merge` is in that loop: `git merge-tree` against origin/main before
push. GitHub already paints textual conflicts on the PR; Sheriff fails them
locally for the agent, and locally verifies compile/impact on a clean merge.
`quality comments` pulls unresolved GitHub review threads (external bots and
humans) into the same oracle.

`quality setup` writes:

| Surface | File |
| --- | --- |
| Cursor MCP | `.cursor/mcp.json` |
| Claude Code / generic MCP | `.mcp.json` |
| Always-on Cursor rule | `.cursor/rules/the-code-sheriff.mdc` |
| Project skill | `.cursor/skills/the-code-sheriff/SKILL.md` and `.claude/skills/the-code-sheriff/SKILL.md` |
| Agent readme (if missing) | `AGENTS.md` |

The same files the agent already follows (`AGENTS.md`, `CLAUDE.md`,
`.cursor/rules`) are ingested as review rules. Put team standards in those
files **or** `.quality/rules/*.md` — one source of truth, no Confluence
re-entry.

Put `quality` on PATH so MCP can spawn:

```bash
uv tool install git+https://github.com/pwoodman/the-code-sheriff.git
```

## What is enforced

| Gate | Tools | Notes |
| --- | --- | --- |
| **Format** | csharpier, Prettier, rustfmt, gofmt, ruff, google-java-format, SQLFluff | C#, JS/TS/React, Rust, Go, Python, Java, SQL |
| **Lint** | Roslyn, ESLint + react-hooks + jsx-a11y, clippy, golangci-lint, ruff, Checkstyle, SQLFluff | same |
| **DRY** | jscpd | copy-paste |
| **Security** | gitleaks, osv-scanner, Trivy, optional semgrep/Checkov | secrets + SCA + SAST + IaC + SBOM |
| **Compile** | `dotnet build`, `cargo build`, `go build`, `mvn`/`javac`, `tsc --noEmit` | **only after security passes**; build plugins and package scripts may execute |
| **Impact** | import graph | upstream deps + downstream consumers; fail if callers weren’t updated or tested |
| **Test** | pytest / Jest / Vitest / go test / … | source diffs need a test file; touched tests >15% slower must be accepted |
| **Coverage** | pytest-cov / Jest / Go cover / LCOV | default **80% line** floor (industry baseline); skip if no tests |
| **Audit** | 120-point static inspection | HIGH-confidence evidence only; fail on P0; N/A when no API/UI |
| **UI** | Playwright / Cypress | **only specs whose touch set hits the diff** (plus downstream files) |
| **Version** | semver files + changelog | bump required when source changes |
| **Merge** | `git merge-tree` | textual conflicts vs base; local verify compile/impact on the merged tree |
| **Comments** | GitHub review threads | unresolved external and human threads stay in the oracle; does not fail CI |
| **AI review** | heuristic + optional LLM (impact/audit context, custom rules) | PRs; risk-routed cheap/full models; incremental hunks; inline comments; does not fail the build |
| **Regex** | configurable + default unsafe-API patterns | change set; `# quality:ignore` / `.quality/ignore.toml` |
| **Packages** | import + manifest names vs a local risk catalog | typosquats/malware/abandoned libs; undeclared third-party imports |

Languages and structured file kinds are auto-detected from a declarative
capability registry. C#, JavaScript/TypeScript, Java, C/C++, Go, Rust, Python,
PHP, Ruby, Swift, Kotlin, Dart, Scala, Lua, R, Elixir, Shell, PowerShell, and SQL
have registry-driven tool adapters. The original Python, JS/TS, Go, Rust, Java,
C#, and SQL handlers remain the mature, fully tested tier. Other language
adapters are **experimental/best-effort**: they use established project or PATH
tools, pass argument arrays without a shell, and report missing tools as skip.

JSON, TOML, XML, INI, dotenv, properties, and batch files have non-executing
built-in validation. YAML, Markdown, CSS, Dockerfiles, Makefiles, GitHub
workflows/composite actions, and git configuration use specialized external
validators when installed. XML declarations/entities are rejected by the
built-in parser, `xmllint` uses `--nonet`, and workflow paths take precedence
over generic YAML. XML, INI, properties, dotenv, Makefile, and batch support is
validation-only. Zsh formatting is preserve/opt-in.

Missing compilers skip compile; a **failed or skipped
security scan blocks compile** so a tree with known vulns or no scanners is not
built. Non-executing C/C++, PHP, Ruby, Dart, Lua, and PowerShell syntax checks
remain available without running project code; project builds require trusted
mode. UI is skipped when compile failed, and when the diff does not touch a
spec, its imports, a matching route, or a coverage-map hit.

Standards: [`standards/`](standards/FORMATTING.md) · [`VERSIONING`](standards/VERSIONING.md) · [`COMPILE`](standards/COMPILE.md) · [`IMPACT`](standards/IMPACT.md) · [`COVERAGE`](standards/COVERAGE.md) · [`AUDIT`](standards/AUDIT.md) · [`POLICY`](standards/POLICY.md) · [`UI`](standards/UI.md) · [`CI`](standards/CI.md) · [`SUPPORT`](standards/SUPPORT.md) · [`PLUGINS`](standards/PLUGINS.md) · [`TROUBLESHOOTING`](standards/TROUBLESHOOTING.md).

## Quick start

```bash
python3 -m pip install -e ".[dev]"
quality doctor
quality run --skip review          # full suite on your machine
pre-commit install --hook-type pre-commit --hook-type pre-push
```

```bash
quality bump auto                  # feat/fix/breaking → minor/patch/major
quality compile                    # runs security first, then builds
quality ui --list                  # which Playwright/Cypress specs the diff selects
quality impact                     # who is upstream/downstream of the diff
quality coverage                   # line coverage vs 80% floor
quality audit                      # 120-point evidence-backed inspection
quality report                     # scorecard, performance, issues, recommendations
```

## GitHub cost knob

```toml
[quality.ci]
mode = "local"                     # default: cheap Actions
# mode = "github"                  # full suite on runners
# mode = "both"                    # hooks + full Actions
github_gates = ["format", "lint", "regex", "packages", "security", "impact", "audit", "version", "merge", "review", "comments"]

[quality.ui]
select = "changed"                 # only specs that touch added/changed files
on_github = false                  # keep browsers off Actions
```

`quality run` on Actions with `mode = "local"` only runs `github_gates`
(format, lint, regex, packages, security, impact, audit, version, merge, review, comments). Format, lint, and
security belong on PRs so secrets, CVEs, SAST, and IaC do not wait for a
hosted scanner. Force the rest with `quality run --full`,
`QUALITY_CI_FULL=1`, `[quality.ci] mode = "both"`, or Actions → **Quality gates
(full suite)**. Playwright/Cypress still skip on GitHub unless `on_github = true`
or `QUALITY_UI_ON_GITHUB=1`.

This toolkit’s own PRs run that same **The Code Sheriff** check via
[`.github/workflows/sheriff.yml`](.github/workflows/sheriff.yml). `quality.toml`
uses `mode = "both"` so detect / format / lint / DRY / security / compile /
coverage actually run on GitHub instead of looking skipped. Compile still reports skip on a Python-only tree (there is nothing to
build). UI still reports skip when there is no Playwright/Cypress project.

Unit tests run on Linux, macOS, and Windows across Python 3.11–3.14 in
[`.github/workflows/ci.yml`](.github/workflows/ci.yml). Scheduled toolchain
fixtures cover representative ecosystem setup without adding that cost to PRs.

Consumers: [`examples/CONSUMING.md`](examples/CONSUMING.md). Golden paths: [`docs/START.md`](docs/START.md). Required-check setup: [`docs/GITHUB_APP.md`](docs/GITHUB_APP.md).

## Configuration

```toml
[quality]
config_version = 1
languages = ["auto"]
fail_on = ["format", "lint", "dry", "security", "compile", "impact", "coverage", "audit", "ui", "version"]
ai_review = "pr-only"
policy = "adopt"                   # observe | adopt | enforce — see standards/POLICY.md
baseline = ".quality-baseline.json"
trust = "trusted"                  # trusted | prompt | untrusted
offline = false
jobs = 4                             # bounded parallel profile adapters
required_tools = []                # doctor fails when a listed tool is missing

[quality.cache]
enabled = true                      # deterministic format/lint adapters only

[quality.ci]
mode = "local"

[quality.compile]
require_security = true

[quality.coverage]
line = 80                          # industry-standard statement-coverage floor
branch = 0                         # 0 = do not enforce branch coverage
tool = "auto"

[quality.audit]
fail_on_priority = ["P0"]
min_confidence = "HIGH"

[quality.impact]
depth = 4
require_downstream = true

[quality.ui]
select = "changed"                 # changed | all
framework = "auto"                 # auto | playwright | cypress
on_github = false

[quality.version]
require_changelog = "if-present"   # if-present | always | never

[quality.review]
ingest_agent_files = true          # AGENTS.md, CLAUDE.md, .cursor/rules

[quality.merge]
verify = "auto"                    # auto | always | never
siblings = false

[quality.comments]
in_oracle = true                   # unresolved GitHub threads stay in quality oracle
fail = false                       # report only unless --fail / comments.fail = true

[quality.sql]
dialect = "postgres"
```

Project Prettier/ESLint/Ruff configs win over bundled files in `configs/`.
`configs/quality.schema.json` describes the configuration representation.
Unknown keys directly under `[quality]` are rejected. Gates never install
tools; installation is only performed by an explicit `quality doctor --install`.

### AI review keys

Heuristic review always runs. For JSON findings on the PR: `ANTHROPIC_API_KEY`
or `OPENAI_API_KEY`. Docs, lockfiles, and generated paths skip the LLM. Typical
PRs use a cheap model (Haiku / GPT-4.1-mini); auth/SQL/high-fan-out diffs use
Sonnet. Later commits on the same PR only review new hunks. Custom rules live
in `.quality/rules/*.md`. `AGENTS.md`, `CLAUDE.md`, and `.cursor/rules` are
ingested too (`ingest_agent_files = true`). Inline `# quality:ignore eval` or
`.quality/ignore.toml` (via `quality ignore add`) suppress a hit. Last findings
are stored in `.quality-reports/findings-last.json` and reopen if the snippet
is still in the tree. `quality eval` writes `.quality-reports/eval/SCORECARD.md`.
See [`standards/AI_REVIEW.md`](standards/AI_REVIEW.md).

## CLI

```
quality detect
quality doctor [--install]
quality format [--check | --write]
quality lint
quality regex [--base origin/main]
quality packages [--base origin/main]
quality dry
quality security
quality sbom [--format all|cyclonedx|spdx]
quality compile [--force]
quality impact [--base origin/main]
quality merge [--base origin/main] [--verify] [--siblings]
quality comments [--fail]
quality coverage
quality test
quality audit
quality baseline [--ratchet]
quality ui [--list] [--all] [--base origin/main]
quality version [--base origin/main]
quality bump auto|major|minor|patch
quality review [--base origin/main] [--post]
quality ignore add --rule eval --path src/app.py --reason "demo" --owner you
quality timing accept --test tests/test_app.py::test_ok
quality oracle [--run] [--prompt]
quality eval [--suite reviewbench|martian|macroscope|all] [--download] [--llm]
quality mcp
quality run [--only security,compile,impact,coverage,audit,ui] [--skip review] [--full]
quality report [--format console|markdown|html|json|sarif|junit] [--diff]
quality watch [--interval 1.5]
quality cache [status|clean]
quality setup
quality init [--policy adopt]
quality github-app register|serve|manifest
codesheriff github-app register|serve|manifest
quality --policy observe run --skip review
```

After `quality run`, `.quality-reports/` holds a scorecard you can print or share:

- `quality-report.md` — performance, issues, and recommended next commands
- `quality-report.html` — same report, print-friendly in a browser
- `quality-report.json` — machine-readable digest
- `diagnostics.json` — editor problem-matcher list
- `history.json` — last 20 run verdicts (`quality report --diff` vs previous)

`quality report` reprints the last run without re-executing gates. Every run
writes JSON, Markdown, HTML, SARIF 2.1.0, and JUnit XML. JSON report, audit,
coverage, and baseline documents carry `schema_version`; bundled schemas live
in `configs/`.

Failures include the tool and rule, normalized `path:line:column`, why the
command failed, and a copyable local reproduction command when available.
Structured reports also retain a redacted command, working directory, return
code, and bounded output excerpt; likely secret values are replaced with
`<redacted>`.

The deterministic cache is limited to parse/format/lint profile adapters and is
keyed by file content, effective configuration, profile/capability, and tool
version. Builds, tests, AI review, and security/network scans are never cached.
Use `quality cache status`, `quality cache clean`, or set
`QUALITY_GATES_CACHE_ENABLED=0`.

Exit `1` = a gate in `fail_on` reported errors. Skip ≠ fail.

## Covering a hosted scanner

The Code Sheriff is meant to replace a second PR-time security/review product
(CodeAnt-class SAST, secrets, SCA, IaC, SBOM, AI review, quality gates). It
does **not** run live pentests, DAST against a deployed app, or cloud CSPM of
AWS/GCP/Azure accounts — those are a different job.

| Need | How The Code Sheriff covers it |
| --- | --- |
| SAST | Semgrep + 120-point audit + AI review |
| Secrets | gitleaks + Trivy secret + heuristic |
| SCA / CVEs | osv-scanner + Trivy filesystem |
| IaC | Trivy misconfig + Checkov (if installed) + kubeconform/hadolint/tflint |
| SBOM | `quality sbom` (CycloneDX + SPDX); also written during the security gate |
| Duplicate code | jscpd (`quality dry`) |
| Coverage | line floor (default 80%) |
| Dead code / complexity | audit |
| AI PR review | inline comments, apply-able patches, OWASP/CWE, steps of reproduction |
| PR summary | review posts a summary onto the pull request description |
| IDE | `.quality-reports/diagnostics.json` problem matcher |
| Auto-fix | suggestion fences, MCP `quality_apply_fix`, `quality oracle` |

## License

[MIT](LICENSE). Public at https://github.com/pwoodman/the-code-sheriff
