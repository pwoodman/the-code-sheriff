# AI code review

Review is a **pull-request** step, not a merge blocker, unless you add
`review` to `quality.fail_on`. Format/lint/DRY/security already own the
mechanical bar; review is for bugs those gates cannot statically prove.

## What runs

1. A heuristic pass over the diff (unsafe APIs, TODO/FIXME, huge files, source
   changed with no tests). Format and lint findings are not re-raised.
2. Context packing: impact graph neighbors, `.quality-reports/impact.json` and
   `audit.json` when present, prior gate errors, and `.quality/rules/*.md`.
3. If a key is present, a model reviews that bundle. Default mode is **agentic**
   (the model may request extra files or greps, then must submit JSON findings).
   `ensemble` runs shuffled-diff passes and keeps majority-vote issues.
   `single` is one shot. `heuristic` skips the model.
4. Style-nit findings are dropped. A validator pass (same model) can drop false
   positives. Output is `.quality-reports/review.json` plus `review.md`.
5. `--post` / the GitHub Actions review job writes **inline** pull-request
   comments at `path:line` and a `quality-review` check run (not only an issue
   comment). Resolution rate vs the previous `review.json` is recorded.

## Custom rules

Put markdown files in `.quality/rules/` (override with `rules_dir`):

```markdown
---
name: no-eval
paths: ["**/*.py", "src/**"]
severity: error
---
Do not introduce eval() or equivalent dynamic execution of untrusted strings.
```

Rules whose `paths` globs miss every changed file are omitted from the prompt.
See `examples/review-rules/`.

## Providers (`quality.review.provider = "auto"`)

| Provider | Env | Default model |
| --- | --- | --- |
| Anthropic | `ANTHROPIC_API_KEY` | `claude-sonnet-4-6` |
| OpenAI | `OPENAI_API_KEY` | `gpt-4.1` |
| Heuristic only | no key, `provider = "github-models"` (retired), `mode = "heuristic"`, or `offline` | — |

GitHub Models (`models.github.ai`) was retired on 2026-07-30. A `GITHUB_TOKEN`
on Actions is not an inference credential. `provider = "github-models"` is
accepted for old configs and runs the heuristic pass only.

```toml
[quality.review]
provider = "auto"
mode = "auto"          # auto | agentic | ensemble | single | heuristic
passes = 3             # ensemble only
tool_rounds = 4
rules_dir = ".quality/rules"
inline_comments = true
check_run = true
validate = true
verify_tests = false
symbol_neighbors = true
```

Set `ai_review = "always"` in `quality.toml` to run on branch pushes as well.
Set `ai_review = "never"` to disable the job.

## Agent loop

Coding agents should treat gates as the oracle, not the chat transcript:

```bash
quality oracle --run --prompt
# fix blocking findings
quality oracle --run
```

`quality mcp` exposes `quality_oracle`, `quality_run`, `quality_review`,
`quality_finding_context`, and `quality_apply_fix` over MCP stdio so Cursor /
Claude Code can iterate until `green` is true. Inline GitHub comments include
why / fix / verify and an apply-able suggestion fence when a patch is present.

`quality eval --suite reviewbench` scores labeled diffs (must-catch bugs and
must-stay-quiet hard negatives). Macroscope's 118-bug JSON is not public; use
`quality eval --suite martian --download` for the MIT Code Review Bench goldens
those vendors already scored, and `quality eval --suite macroscope` for the
reconstructed commons-math GCD sample they published.

Without a key, you still get the heuristic review as `.quality-reports/review.md`.
