<!-- the-code-sheriff:agent-loop -->

# Agent loop

This repo uses [The Code Sheriff](https://github.com/pwoodman/the-code-sheriff).
After edits: `quality fix` then `quality oracle --run --prompt`. Do only the
Next action. Loop until `green` and `certificate.ready`. Do not commit on chat
confidence. Works with Cursor, Claude Code, Copilot, Codex, OpenCode, Qwen,
DeepSeek harness, and VS Code.
