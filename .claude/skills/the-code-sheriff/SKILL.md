---
name: the-code-sheriff
description: Run The Code Sheriff quality gates and iterate until the oracle is green. Use when finishing a change, before commit or PR, when lint/security/review fails, or when the user mentions quality, sheriff, gates, MCP, or vibe-coding quality.
---

<!-- the-code-sheriff:agent-loop -->

# The Code Sheriff

The gates are the oracle. Do not treat the chat transcript as a passing review.

## Loop

```bash
quality oracle --run --prompt
# fix remaining blockers
quality oracle --run
```

Or MCP: `quality_run` → `quality_oracle` → `quality_finding_context` /
`quality_apply_fix` → repeat until `green` is true. `quality_merge` dry-merges
into main; `quality_pr_comments` lists unresolved review threads.

## Rules

- Mechanical gates (format, lint, regex, packages, DRY, security, compile,
  impact, tests, coverage, audit, UI, version, merge) beat model self-assessment.
- Custom markdown in `.quality/rules/` is enforced on the change set.
- `AGENTS.md`, `CLAUDE.md`, and `.cursor/rules` are ingested as review rules.
- Never skip the oracle because unit tests "looked fine" in conversation.
- Rebase when merge reports `textual-conflict`. Do not invent a merge.
