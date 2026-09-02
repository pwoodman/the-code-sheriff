# Upstream / downstream impact

The **impact** gate answers: if this change ships, **what else is affected**,
and **was that blast radius updated or covered by tests?**

It is static (imports only). It does not execute code.

## Direction

| Direction | Meaning | Validation |
| --- | --- | --- |
| **Upstream** | Files the change **depends on** (imports) | Import still resolves in-repo; missing local module = fail |
| **Downstream** | Files that **depend on** the change (importers, transitive) | Consumer was **updated in this diff**, or a **test imports** the changed file or the consumer |

If a downstream consumer was not touched and no test covers either side, the
gate **fails**: the change can break callers that nobody re-checked.

Changed test files are not treated as production roots. Skip ≠ fail when the
diff is docs-only.

## Example

`core.py` changes. `service.py` imports it. `api.py` imports `service.py`.

- `service.py` + `api.py` also in the diff → consumers updated → pass
- `tests/test_core.py` imports `core.py` → existing test covers it → pass
- neither → fail `unvalidated-downstream`

UI tests use the same graph: downstream files are added to Playwright/Cypress
selection, so a util change still runs the spec that visits the page that
imports it.

## Commands

```bash
quality impact --base origin/main
quality impact --json
```

Writes `.quality-reports/impact.json`.

```toml
[quality.impact]
depth = 4
require_downstream = true   # fail when a consumer is neither updated nor tested
require_own_tests = false   # warning (not fail) if the changed file has no test
```

`impact` is cheap, so default `github_gates` includes it on PRs even when
`ci.mode = local`. Browser UI tests stay off GitHub.
