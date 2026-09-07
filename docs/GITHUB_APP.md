# The Code Sheriff

Install **The Code Sheriff** on a repository, add the workflow, and require
**The Code Sheriff** as a status check. Gates run on **that repo’s** GitHub
Actions minutes. This project does not host a worker and does not pay for
other people’s runs.

GitHub slugifies the App name (typically `the-code-sheriff`). Checks and
branch protection still use **The Code Sheriff**. CLI is `quality` or
`codesheriff`.

## One command

In the repo you want to scan:

```bash
uvx --from git+https://github.com/pwoodman/the-code-sheriff.git quality setup
```

That writes a default `quality.toml`, pins `.github/workflows/quality.yml`,
adds git hooks, creates a ruleset requiring **The Code Sheriff** when `gh` is
logged in, and records a baseline. Commit those files. **You do not need the
GitHub App** for checks to run.

`quality init` writes the files without running gates or touching GitHub rules.

Fork PRs stay `untrusted`. LLM keys stay in that repo’s secrets if you want
review.

## Register the App

```bash
quality github-app register
```

Open the printed URL if a browser did not. Credentials land in `.quality-app/`
(gitignored). Permissions: checks write, pull requests write, contents read,
metadata read, security events write.

Optional: store `QUALITY_APP_ID` and `QUALITY_APP_PRIVATE_KEY` as org secrets
if you want checks posted as the App bot instead of
`github-actions[bot]`. The required check name is still **The Code Sheriff**.

## Optional hosted webhook

Only if you want this repo to run other people’s PRs (you pay those minutes):
`.github/workflows/github-app.yml` plus `github-app/worker`. Default is off
(`hook_attributes.active = false`). Pass `--webhook-url` when registering.

## Telemetry

Off.
