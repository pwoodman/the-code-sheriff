# Quality gates

A reusable **format → lint → DRY → security → AI review** pipeline for mixed-language
teams. It is meant to run **after commits land** (push CI) **and** on pull
requests. That split is intentional, not redundant.

| When | What | Why |
| --- | --- | --- |
| `git commit` (pre-commit) | format + lint on the worktree | seconds, no network, keeps the tree readable |
| `git push` (pre-push) | secrets scan | stop a key from ever leaving the laptop |
| Push to a branch | full suite except AI review | the server is the source of truth; skipped hooks cannot bypass it |
| Pull request | full suite **plus** AI review | humans + model look at the diff; mechanical gates already went green |

Local hooks are a courtesy. CI is the contract.

## What is enforced

| Gate | Tools | Languages |
| --- | --- | --- |
| **Format** | csharpier, Prettier, rustfmt, gofmt, ruff, google-java-format, SQLFluff | C#, JS/TS/React, Rust, Go, Python, Java, SQL |
| **Lint** | Roslyn analyzers, ESLint + react-hooks + jsx-a11y, clippy, golangci-lint, ruff, Checkstyle, SQLFluff | same |
| **DRY** | jscpd | all of the above |
| **Security** | gitleaks, osv-scanner, optional semgrep | secrets, lockfile CVEs, common RCE/XSS sinks |
| **AI review** | heuristic diff review + optional Anthropic / OpenAI / GitHub Models | pull requests |

Languages are **auto-detected** from the tree. A Go service is not failed for
missing `rustc`. Missing tools are skipped with a doctor note; missing findings
are not.

Standards (the actual rules, not just tool names) live in [`standards/`](standards/FORMATTING.md).
Bundled configs live in [`configs/`](configs/).

## Quick start

```bash
python3 -m pip install -e ".[dev]"
quality doctor          # what is installed
quality detect          # what this repo contains
quality run --skip review
```

Apply formatters:

```bash
quality format --write
```

Install git hooks (commit = format/lint, push = security):

```bash
python3 -m pip install pre-commit
pre-commit install --hook-type pre-commit --hook-type pre-push
```

### On GitHub

This repository already runs [`.github/workflows/quality.yml`](.github/workflows/quality.yml)
on `push` and `pull_request` as six jobs: detect, format, lint, DRY, security,
AI review (PRs only).

Other repos should follow [`examples/CONSUMING.md`](examples/CONSUMING.md). The
smallest integration is `pip install git+https://github.com/<org>/quality-gates.git`
and `quality run`.

## Configuration

`quality.toml` at the project root:

```toml
[quality]
languages = ["auto"]                       # or ["python", "go", ...]
fail_on = ["format", "lint", "dry", "security"]
ai_review = "pr-only"                      # pr-only | always | never

[quality.sql]
dialect = "postgres"                       # sqlfluff dialect

[quality.dry]
min_lines = 6
min_tokens = 50
threshold = 0                              # raise for legacy code, then ratchet down

[quality.review]
provider = "auto"                          # anthropic | openai | github-models | off
```

If the project already has `.prettierrc`, `eslint.config.js`, `ruff.toml`,
`.golangci.yml`, or `.sqlfluff`, those files win. Otherwise the bundled
standards are used.

### AI review keys

Heuristic review always runs. For a narrative PR comment, set one of:

- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- GitHub Actions `GITHUB_TOKEN` (GitHub Models, no extra secret)

Without a key the job still publishes `.quality-reports/review.md` (unsafe APIs,
missing tests, oversized diffs, DRY/security fallout).

## CLI

```
quality detect
quality doctor [--install]
quality format [--check | --write] [--language python]
quality lint
quality dry
quality security
quality review [--base origin/main] [--post]
quality run [--only format,lint] [--skip review]
quality init --org YOUR_ORG
```

Exit code `1` means a gate in `fail_on` reported errors. Skipped tools do not
fail the build.

`quality doctor --install` (and CI) pin-download gitleaks, osv-scanner,
golangci-lint, google-java-format, and Checkstyle into
`~/.cache/quality-gates/`. Compilers (Go, Rust, JDK, .NET, Node) still need to
be on the machine or provided by `actions/setup-*`.

## Layout

```
configs/          formatter + linter + security rule files
standards/        human-readable rules the AI reviewer also reads
src/quality_gates CLI used by local hooks and CI
.github/workflows multi-job gates (this repo) + unit tests
examples/         copy-paste consumer workflow
```

## License

MIT
