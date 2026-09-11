---
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
