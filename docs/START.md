# Start here

## Five-minute setup

```bash
uvx --from git+https://github.com/pwoodman/the-code-sheriff.git quality setup
```

Run it from the repository you want to protect. The command detects the
project, writes a pinned workflow and safe defaults, runs an initial baseline,
and (when `gh` is logged in) offers to require **The Code Sheriff** as a
repository check. Review and commit the generated files, then open a pull
request. You do not need a GitHub App.

The only files required for GitHub are:

```text
quality.toml
.github/workflows/quality.yml
.quality-baseline.json
```

Hooks and coding-agent integrations are optional local conveniences. Use
`quality setup --no-hooks --no-agents` when you want the smallest possible
installation.

No `uv`? `pip install "git+https://github.com/pwoodman/the-code-sheriff.git"` then
`quality setup`.

## What users see

Every pull request gets one check named **The Code Sheriff**. It summarizes
blocking findings, links to the full report, and can publish security findings
to GitHub Code Scanning. Start in the default `adopt` policy for an existing
repository; old findings are recorded in the baseline while new regressions
still surface. Move to `enforce` after the team has seen a few real pull
requests pass.

GitHub Copilot is the default AI reviewer. If your organization has GitHub
Copilot enabled, no AI API key is needed:

```bash
quality setup
```

This requests `copilot-pull-request-reviewer[bot]` asynchronously on each pull
request. GitHub owns model access and billing; The Code Sheriff remains
responsible for deterministic gates and the required check.

If you prefer a direct provider, an API key overrides the default automatically:
`ANTHROPIC_API_KEY` selects Anthropic and `OPENAI_API_KEY` selects OpenAI.

If a check is confusing, run:

```bash
quality doctor
quality report
```

`doctor` explains missing tools and `report` explains the last run in plain
language. For a disposable open-source beta test, use
[BETA_TESTING.md](BETA_TESTING.md).

The default gate set also includes `dead`, a conservative Python unused-code
scan powered by Vulture. Its result is included in every JSON/Markdown/HTML
report; if Vulture is unavailable the gate is explicitly marked skipped rather
than silently passing.

Share this poster: [getting-started.png](getting-started.png)
([HTML source](getting-started.html) if you want to print or tweak it).

Coding agents get MCP + Cursor/Claude/Copilot/Gemini instruction files that
loop on `quality fix` then `quality oracle --run --prompt` until
`certificate.ready`. `quality merge` dry-merges vs main. Unresolved GitHub
review comments stay in the oracle. `quality setup --auto-merge` turns on
GitHub repo auto-merge so a required Sheriff check can land the PR.
Skip agent files with `--no-agents`.

## New Python app

```bash
python3 -m pip install -e ".[dev]"
quality setup
```

Expect format/lint/coverage to run. Compile skips on a Python-only tree.

## Existing JavaScript monorepo

Keep `languages = ["auto"]`. A change under `frontend/` should plan frontend jobs and skip unrelated Python packages. Check with:

```bash
quality run --changed --plan
quality ui --list
```

Install project ESLint/Prettier; the gate uses them when present.

## Brownfield polyglot (`policy = adopt`)

`quality setup` already uses adopt and writes `.quality-baseline.json`. Old lint
debt is grandfathered. New findings and failed tests still block.

See [CONSUMING.md](../examples/CONSUMING.md) for the full config surface.
