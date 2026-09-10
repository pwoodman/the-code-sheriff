# Start here

One command, in the repo you want scanned:

```bash
uvx --from git+https://github.com/pwoodman/the-code-sheriff.git quality setup
```

That writes defaults, pins the GitHub workflow, installs git hooks, requires
**The Code Sheriff** if `gh` is logged in, and records a baseline. Commit the
new files. You do not need a GitHub App.

No `uv`? `pip install "git+https://github.com/pwoodman/the-code-sheriff.git"` then
`quality setup`.

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
