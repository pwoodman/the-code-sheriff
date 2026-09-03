# Where gates run

Default is **your machine**, not GitHub-hosted runners.

```toml
[quality.ci]
mode = "local"                 # local | github | both
github_gates = ["format", "lint", "impact", "audit", "version", "review"]
```

| Mode | Developer PC (hooks + `quality run`) | GitHub Actions |
| --- | --- | --- |
| `local` (default) | format, lint, DRY, security, compile, impact, coverage, audit, UI, version | format, lint, impact, audit, version, PR review |
| `github` | optional hooks | full suite including compile-after-security; UI still off |
| `both` | full hooks | full suite; UI still off unless opted in |

On Actions, `quality run` sees `GITHUB_ACTIONS=true` and `ci.mode=local` and
**automatically skips** the heavy gates. Force them with:

```bash
quality run --full
# or
QUALITY_CI_FULL=1 quality run
```

or Actions → Run workflow → **Quality gates (full suite)**.

Install the local contract:

```bash
pre-commit install --hook-type pre-commit --hook-type pre-push
```

- commit: format, lint, version
- push: DRY, security, compile, impact, coverage, audit, selective UI (compile runs only if security
  passed; coverage uses the 80% line floor; audit fails on HIGH-confidence P0 evidence; impact
  requires downstream consumers to be updated or tested; UI only runs specs that cover the diff
  plus downstream importers)

Playwright/Cypress stay **off GitHub** by default even when `mode` is `github`
or `both`. Browser installs are the expensive part. Opt in:

```toml
[quality.ui]
on_github = true
```

or `QUALITY_UI_ON_GITHUB=1`. See [`UI.md`](UI.md).

How findings block PRs (observe / adopt / enforce) is in [`POLICY.md`](POLICY.md).
