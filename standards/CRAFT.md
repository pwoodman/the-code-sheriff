# Clean-code craft (not dogma)

Sheriff checks the clean-code ideas that make AI-generated changes safe to
auto-merge. It does **not** enforce four-line functions or clever indirection.

Sources: [KISS / DRY / SRP / POLA / Boy Scout](https://www.reddit.com/r/cleancode/comments/15erwmq/clean_code_guide_that_will_help_you_understand/),
[Codacy clean-code practices](https://blog.codacy.com/what-is-clean-code),
[Pandorian: governance confidence, not model quality](https://pandorian.ai/thesis/).

## What is evidence-backed

| Smell | Where | Severity | Why it blocks trust |
| --- | --- | --- | --- |
| Swallowed exception / empty catch | review + audit 59 | error | Failures vanish |
| Bare `except:` | review | error | Cancels and bugs become success |
| Same unnamed literal twice | review | warning | Hidden policy (rate, timeout) |
| Function ≥ 80 lines | review | warning | Mixed jobs, hard to test |
| Nest depth ≥ 5 | review + audit 48 | warning | Hidden decision |
| God file ≥ 800 lines | audit 41 | HIGH | Mixed-concern dump |
| Source without a test | review / test gate | error when required | Unverified behavior |
| Copy-paste | DRY gate | error | Two places to forget |

Format, lint, and language style guides already own spacing and names. Craft
does not re-raise those.

## Agent loop

```bash
quality fix
quality oracle --run --prompt   # one Next action
quality certify                 # auto_merge: ready
```

Auto-merge is a governance decision. Machines do not need to be perfect; the
certificate says the **system around them** passed. Enable GitHub auto-merge
only after **The Code Sheriff** is a required check (`quality setup --auto-merge`).
