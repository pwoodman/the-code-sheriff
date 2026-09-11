"""Write Cursor / Claude Code / Copilot / Codex surfaces so agents treat gates as the oracle."""

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

LOOP_BODY = """Chat is not proof. After edits, loop until the oracle is green and
`certificate.ready` is true:

1. `quality fix` (format / safe lint autofix / finding patches)
2. `quality oracle --run --prompt` (or MCP `quality_run` then `quality_oracle`)
3. Do **only** the playbook `next` action (`quality_finding_context` / `quality_apply_fix`)
4. Re-run until `green` is true and `certificate.auto_merge` is `ready`
5. If `quality merge` reports textual-conflict, rebase onto the base branch
6. Unresolved GitHub review comments are remaining work
7. Only then commit, open a PR, or auto-merge

Custom standards: `.quality/rules/*.md`. `AGENTS.md`, `CLAUDE.md`,
`.github/copilot-instructions.md`, and `.cursor/rules` are enforced as review
rules automatically.
"""

CURSOR_RULE = f"""---
description: Treat The Code Sheriff as the merge oracle. Run quality gates before claiming work is done.
alwaysApply: true
---

<!-- {LOOP_MARKER} -->

# The Code Sheriff

{LOOP_BODY}
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
"""

AGENTS_MD = f"""<!-- {LOOP_MARKER} -->

# Agent loop

This repo uses [The Code Sheriff](https://github.com/pwoodman/the-code-sheriff).
After edits: `quality fix` then `quality oracle --run --prompt`. Do only the
Next action. Loop until `green` and `certificate.ready`. Do not commit on chat
confidence. Works with Cursor, Claude Code, Copilot, Codex, OpenCode, Qwen,
DeepSeek harness, and VS Code.
"""

CLEAN_CODE_RULE = """---
name: clean-code
paths: ["**/*.py", "**/*.js", "**/*.ts", "**/*.tsx", "**/*.jsx", "**/*.go", "**/*.rs"]
severity: warning
---

Write code that a human and an agent can safely auto-merge.

- Keep it simple (KISS). Do not add abstractions that do not pay for themselves.
- One job per function (SRP). Extract validate / compute / format; do not
  chase 4-line functions.
- DRY: extract a shared helper when the same logic appears twice.
- Names reveal intent. If a name needs a comment, rename it.
- Comments explain why, never what the name already says.
- No unexplained literals used more than once — name the policy
  (timeout, rate, limit).
- Encapsulate nests deeper than four levels into a named predicate.
- Handle errors: never `except: pass`, empty `catch`, or fake success.
- New production behavior needs a unit test in the same change.
- Follow the language's standard style (the format/lint gates already own it).
- Leave the touched code better than you found it (Boy Scout), without
  rewriting unrelated architecture.
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
        (root / "CLAUDE.md", AGENTS_MD),
        (root / "GEMINI.md", AGENTS_MD),
        (root / ".github" / "copilot-instructions.md", AGENTS_MD),
        (
            root / ".github" / "instructions" / "the-code-sheriff.instructions.md",
            AGENTS_MD,
        ),
        (root / ".quality" / "rules" / "clean-code.md", CLEAN_CODE_RULE),
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
