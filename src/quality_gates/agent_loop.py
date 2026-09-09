"""Write Cursor / Claude Code surfaces so agents treat gates as the oracle."""

from __future__ import annotations

import json
from pathlib import Path

LOOP_MARKER = "the-code-sheriff:agent-loop"

MCP_CONFIG = {
    "mcpServers": {
        "the-code-sheriff": {
            "command": "quality",
            "args": ["mcp"],
        }
    }
}

CURSOR_RULE = f"""---
description: Treat The Code Sheriff as the merge oracle. Run quality gates before claiming work is done.
alwaysApply: true
---

<!-- {LOOP_MARKER} -->

# The Code Sheriff

Chat is not proof. After edits, loop until the oracle is green:

1. `quality oracle --run --prompt` (or MCP `quality_run` then `quality_oracle`)
2. Fix every remaining blocker (`quality_finding_context` / `quality_apply_fix`)
3. Re-run until `green` is true
4. If `quality merge` reports textual-conflict, rebase onto the base branch
5. Unresolved GitHub review comments (Greptile, BugBot, humans) are remaining work — apply suggestion patches
6. Only then commit or open a PR

Custom standards: `.quality/rules/*.md`. `AGENTS.md`, `CLAUDE.md`, and
`.cursor/rules` are enforced as review rules automatically.
"""

SKILL_MD = f"""---
name: the-code-sheriff
description: Run The Code Sheriff quality gates and iterate until the oracle is green. Use when finishing a change, before commit or PR, when lint/security/review fails, or when the user mentions quality, sheriff, gates, MCP, or vibe-coding quality.
---

<!-- {LOOP_MARKER} -->

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
"""

AGENTS_MD = f"""<!-- {LOOP_MARKER} -->

# Agent loop

This repo uses [The Code Sheriff](https://github.com/pwoodman/the-code-sheriff).
After edits, run `quality oracle --run --prompt` (or MCP `quality_oracle`) and
fix blockers until it reports green. Do not commit on chat confidence.
"""


def write_agent_integrations(root: Path, *, force: bool = False) -> list[str]:
    notes: list[str] = []
    mcp_json = json.dumps(MCP_CONFIG, indent=2) + "\n"
    files = (
        (root / ".cursor" / "mcp.json", mcp_json),
        (root / ".mcp.json", mcp_json),
        (root / ".cursor" / "rules" / "the-code-sheriff.mdc", CURSOR_RULE),
        (root / ".cursor" / "skills" / "the-code-sheriff" / "SKILL.md", SKILL_MD),
        (root / ".claude" / "skills" / "the-code-sheriff" / "SKILL.md", SKILL_MD),
        (root / "AGENTS.md", AGENTS_MD),
    )
    for path, content in files:
        notes.append(_write_if_allowed(path, content, force=force))
    return [line for line in notes if line]


def _write_if_allowed(path: Path, content: str, *, force: bool) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        return f"kept existing {path}"
    path.write_text(content, encoding="utf-8")
    return f"wrote {path}"
