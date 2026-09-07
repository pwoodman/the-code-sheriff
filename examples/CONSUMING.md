# How to consume this toolkit from another repository

After this repo lives on GitHub as `pwoodman/poly-check`, pick one path.

Heavy gates (DRY, security, compile, coverage, UI) default to **developer
machines**. GitHub Actions always runs format, lint, impact, audit, version,
and PR review. Set `ci.mode` to `github` or `both` for the rest.

## Path A — CLI (recommended)

Copy `quality.toml` (keep `ci.mode = "local"`). Add this workflow:

See [`consumer-cli.yml`](consumer-cli.yml). On Actions, `quality run` is cheap.
On your machine:

```bash
uvx --from git+https://github.com/pwoodman/poly-check.git quality setup
```

Coding agents can loop on `quality oracle --run` (or `quality mcp`) until the
oracle reports green.

Existing/legacy repos should stay on **adopt** (`quality setup` default) and commit `.quality-baseline.json` so
PRs are not blocked by yesterday's backlog. New repos can use `--policy enforce`.
See [`standards/POLICY.md`](../standards/POLICY.md).

To spend GitHub minutes on the full suite, either:

```toml
[quality.ci]
mode = "both"
```

or re-run the workflow with **full_suite**, or `QUALITY_CI_FULL=1 quality run --full`.

## Path B — multi-job reusable workflow

Vendor `.github/workflows/quality.yml`, `.github/workflows/quality-full.yml`,
and `.github/actions/` if you want the Detect → Format → … UI matrix.
With `ci.mode = "local"` that matrix is not scheduled, so PRs do not show
ten skipped heavy jobs.

## Path C — hooks only

```bash
pre-commit install --hook-type pre-commit --hook-type pre-push
```

Commit: format, lint, version. Push: DRY, security, compile, impact, coverage, audit,
selective UI (compile is refused until security is clean; coverage uses the 80% line
floor; audit fails on HIGH-confidence P0 findings; impact requires downstream callers
to be updated or tested; UI only runs specs that cover the diff). Playwright/Cypress
stay off GitHub unless `[quality.ui] on_github = true`.
