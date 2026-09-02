# Where gates run

Default is **your machine**, not GitHub-hosted runners.

```toml
[quality.ci]
mode = "local"                 # local | github | both
github_gates = ["version", "review"]
```

| Mode | Developer PC (hooks + `quality run`) | GitHub Actions |
| --- | --- | --- |
| `local` (default) | format, lint, DRY, security, compile, UI, version | version + PR review only |
| `github` | optional hooks | full suite including compile-after-security; UI still off |
| `both` | full hooks | full suite; UI still off unless opted in |

On Actions, `quality run` sees `GITHUB_ACTIONS=true` and `ci.mode=local` and
**automatically skips** the heavy gates. Force them with:

```bash
quality run --full
# or
QUALITY_CI_FULL=1 quality run
```

or Actions → Run workflow → **full_suite**.

Install the local contract:

```bash
pre-commit install --hook-type pre-commit --hook-type pre-push
```

- commit: format, lint, version
- push: DRY, security, compile, selective UI (compile runs only if security passed;
  UI runs only the Playwright/Cypress specs that cover the diff)

Playwright/Cypress stay **off GitHub** by default even when `mode` is `github`
or `both`. Browser installs are the expensive part. Opt in:

```toml
[quality.ui]
on_github = true
```

or `QUALITY_UI_ON_GITHUB=1`. See [`UI.md`](UI.md).
