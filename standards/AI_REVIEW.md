# AI code review

Review is a **pull-request** step, not a merge blocker, unless you add
`review` to `quality.fail_on`. Format/lint/DRY/security already own the
mechanical bar; review is for judgment.

## What runs

1. A heuristic pass over the diff (unsafe APIs, TODO/FIXME, huge files, source
   changed with no tests, prior DRY/security findings).
2. If a key is present, a model writes a narrative review using the same
   standards listed in `standards/`.
3. The comment is posted on the PR (`--post` / the GitHub Actions review job).

## Providers (`quality.review.provider = "auto"`)

| Provider | Env | Default model |
| --- | --- | --- |
| Anthropic | `ANTHROPIC_API_KEY` | `claude-sonnet-4-20250514` |
| OpenAI | `OPENAI_API_KEY` | `gpt-4.1` |
| GitHub Models | `GITHUB_TOKEN` on Actions | `openai/gpt-4.1-mini` |
| Heuristic only | none of the above | — |

Set `ai_review = "always"` in `quality.toml` to run on branch pushes as well.
Set `ai_review = "never"` to disable the job.

The prompt tells the model **not** to nibble at Prettier/gofmt/ruff nits.
Without a key, you still get the heuristic review as `.quality-reports/review.md`.
