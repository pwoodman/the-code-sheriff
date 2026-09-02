# Quality gates

A reusable **format → lint → DRY → security → compile → impact → coverage → audit → UI → version → AI review**
pipeline. Heavy work defaults to **your PC**. GitHub Actions stays cheap unless
you opt in.

| When | What | Where |
| --- | --- | --- |
| `git commit` | format, lint, version | laptop |
| `git push` | DRY, security, compile, impact, coverage, audit, selective UI | laptop |
| Push / PR on GitHub | impact + audit + version + PR review | Actions (seconds) |
| Optional | full suite on Actions | `ci.mode = "both"` / `"github"`, or workflow **full_suite** |
| Optional | Playwright/Cypress on Actions | `[quality.ui] on_github = true` |

That split saves runner minutes. Hooks are the contract; Actions in `local` mode
only checks versioning and (on PRs) posts a review. Browser UI tests stay off
GitHub even in `github`/`both` mode unless you turn them on.

## What is enforced

| Gate | Tools | Notes |
| --- | --- | --- |
| **Format** | csharpier, Prettier, rustfmt, gofmt, ruff, google-java-format, SQLFluff | C#, JS/TS/React, Rust, Go, Python, Java, SQL |
| **Lint** | Roslyn, ESLint + react-hooks + jsx-a11y, clippy, golangci-lint, ruff, Checkstyle, SQLFluff | same |
| **DRY** | jscpd | copy-paste |
| **Security** | gitleaks, osv-scanner, optional semgrep | secrets + CVEs + SAST |
| **Compile** | `dotnet build`, `cargo build`, `go build`, `mvn`/`javac`, `tsc --noEmit` | **only after security passes**; never executes the program |
| **Impact** | import graph | upstream deps + downstream consumers; fail if callers weren’t updated or tested |
| **Coverage** | pytest-cov / Jest / Go cover / LCOV | default **80% line** floor (industry baseline); skip if no tests |
| **Audit** | 120-point static inspection | HIGH-confidence evidence only; fail on P0; N/A when no API/UI |
| **UI** | Playwright / Cypress | **only specs whose touch set hits the diff** (plus downstream files) |
| **Version** | semver files + changelog | bump required when source changes |
| **AI review** | heuristic + optional LLM | PRs; does not fail the build |

Languages are auto-detected. Missing compilers skip compile; a **failed or skipped
security scan blocks compile** so a tree with known vulns or no scanners is not
built. UI is skipped when compile failed, and when the diff does not touch a
spec, its imports, a matching route, or a coverage-map hit.

Standards: [`standards/`](standards/FORMATTING.md) · [`VERSIONING`](standards/VERSIONING.md) · [`COMPILE`](standards/COMPILE.md) · [`IMPACT`](standards/IMPACT.md) · [`COVERAGE`](standards/COVERAGE.md) · [`AUDIT`](standards/AUDIT.md) · [`UI`](standards/UI.md) · [`CI`](standards/CI.md).

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
```

## GitHub cost knob

```toml
[quality.ci]
mode = "local"                     # default: cheap Actions
# mode = "github"                  # full suite on runners
# mode = "both"                    # hooks + full Actions
github_gates = ["impact", "audit", "version", "review"]

[quality.ui]
select = "changed"                 # only specs that touch added/changed files
on_github = false                  # keep browsers off Actions
```

`quality run` on Actions with `mode = "local"` only runs `github_gates`. Force
the heavy suite with `quality run --full`, `QUALITY_CI_FULL=1`, or Actions →
Run workflow → **full_suite**. Playwright/Cypress still skip on GitHub unless
`on_github = true` or `QUALITY_UI_ON_GITHUB=1`.

Unit tests for this toolkit still run in [`.github/workflows/ci.yml`](.github/workflows/ci.yml)
(pytest + ruff, no language matrix).

Consumers: [`examples/CONSUMING.md`](examples/CONSUMING.md).

## Configuration

```toml
[quality]
languages = ["auto"]
fail_on = ["format", "lint", "dry", "security", "compile", "impact", "coverage", "audit", "ui", "version"]
ai_review = "pr-only"

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

[quality.sql]
dialect = "postgres"
```

Project Prettier/ESLint/Ruff configs win over bundled files in `configs/`.

### AI review keys

Heuristic review always runs. For a narrative PR comment: `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, or GitHub Models via `GITHUB_TOKEN`.

## CLI

```
quality detect
quality doctor [--install]
quality format [--check | --write]
quality lint
quality dry
quality security
quality compile [--force]
quality impact [--base origin/main]
quality coverage
quality audit
quality ui [--list] [--all] [--base origin/main]
quality version [--base origin/main]
quality bump auto|major|minor|patch
quality review [--base origin/main] [--post]
quality run [--only security,compile,impact,coverage,audit,ui] [--skip review] [--full]
quality init --org YOUR_ORG
```

Exit `1` = a gate in `fail_on` reported errors. Skip ≠ fail.

## License

MIT
