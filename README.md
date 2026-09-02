# Quality gates

A reusable **format → lint → DRY → security → compile → version → AI review**
pipeline. Heavy work defaults to **your PC**. GitHub Actions stays cheap unless
you opt in.

| When | What | Where |
| --- | --- | --- |
| `git commit` | format, lint, version | laptop |
| `git push` | DRY, security, compile (compile only if security passed) | laptop |
| Push / PR on GitHub | version + PR review | Actions (seconds) |
| Optional | full suite on Actions | `ci.mode = "both"` / `"github"`, or workflow **full_suite** |

That split saves runner minutes. Hooks are the contract; Actions in `local` mode
only checks versioning and (on PRs) posts a review.

## What is enforced

| Gate | Tools | Notes |
| --- | --- | --- |
| **Format** | csharpier, Prettier, rustfmt, gofmt, ruff, google-java-format, SQLFluff | C#, JS/TS/React, Rust, Go, Python, Java, SQL |
| **Lint** | Roslyn, ESLint + react-hooks + jsx-a11y, clippy, golangci-lint, ruff, Checkstyle, SQLFluff | same |
| **DRY** | jscpd | copy-paste |
| **Security** | gitleaks, osv-scanner, optional semgrep | secrets + CVEs + SAST |
| **Compile** | `dotnet build`, `cargo build`, `go build`, `mvn`/`javac`, `tsc --noEmit` | **only after security passes**; never executes the program |
| **Version** | semver files + changelog | bump required when source changes |
| **AI review** | heuristic + optional LLM | PRs; does not fail the build |

Languages are auto-detected. Missing compilers skip compile; a **failed or skipped
security scan blocks compile** so a tree with known vulns or no scanners is not
built.

Standards: [`standards/`](standards/FORMATTING.md) · [`VERSIONING`](standards/VERSIONING.md) · [`COMPILE`](standards/COMPILE.md) · [`CI`](standards/CI.md).

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
```

## GitHub cost knob

```toml
[quality.ci]
mode = "local"                     # default: cheap Actions
# mode = "github"                  # full suite on runners
# mode = "both"                    # hooks + full Actions
github_gates = ["version", "review"]
```

`quality run` on Actions with `mode = "local"` only runs `github_gates`. Force
the heavy suite with `quality run --full`, `QUALITY_CI_FULL=1`, or Actions →
Run workflow → **full_suite**.

Unit tests for this toolkit still run in [`.github/workflows/ci.yml`](.github/workflows/ci.yml)
(pytest + ruff, no language matrix).

Consumers: [`examples/CONSUMING.md`](examples/CONSUMING.md).

## Configuration

```toml
[quality]
languages = ["auto"]
fail_on = ["format", "lint", "dry", "security", "compile", "version"]
ai_review = "pr-only"

[quality.ci]
mode = "local"

[quality.compile]
require_security = true

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
quality version [--base origin/main]
quality bump auto|major|minor|patch
quality review [--base origin/main] [--post]
quality run [--only security,compile] [--skip review] [--full]
quality init --org YOUR_ORG
```

Exit `1` = a gate in `fail_on` reported errors. Skip ≠ fail.

## License

MIT
