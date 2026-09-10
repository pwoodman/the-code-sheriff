---
name: the-code-sheriff
description: Run The Code Sheriff quality gates and iterate until the oracle is green. Use when finishing a change, before commit or PR, when lint/security/review fails, or when the user mentions quality, sheriff, gates, MCP, or vibe-coding quality.
---

<!-- the-code-sheriff:agent-loop -->

# The Code Sheriff

The gates are the oracle. Do not treat the chat transcript as a passing review.

## Loop

```bash
quality fix
quality oracle --run --prompt
# do only the Next action
quality oracle --run
quality certify
```

Or MCP: `quality_fix` → `quality_run` → `quality_oracle` →
`quality_finding_context` / `quality_apply_fix` → `quality_certify` until
`green` and `certificate.ready` are true. `quality_merge` dry-merges into
main; `quality_pr_comments` lists unresolved review threads.

## Rules

- Mechanical gates (format, lint, regex, packages, DRY, security, compile,
  impact, tests, coverage, audit, UI, version, merge) beat model self-assessment.
- Prefer `quality fix` before hand-editing format/lint.
- Custom markdown in `.quality/rules/` is enforced on the change set.
- `AGENTS.md`, `CLAUDE.md`, and `.cursor/rules` are ingested as review rules.
- Never skip the oracle because unit tests "looked fine" in conversation.
- Rebase when merge reports `textual-conflict`. Do not invent a merge.
- Auto-merge only when `quality certify` says `auto_merge: ready`.
