# Where gates run

Default is **your machine**, not GitHub-hosted runners.

```toml
[quality.ci]
mode = "local"                 # local | github | both
github_gates = ["version", "review"]
```

| Mode | Developer PC (hooks + `quality run`) | GitHub Actions |
| --- | --- | --- |
| `local` (default) | format, lint, DRY, security, compile, version | version + PR review only |
| `github` | optional hooks | full suite including compile-after-security |
| `both` | full hooks | full suite |

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
- push: DRY, security, compile (compile runs only if security passed)
