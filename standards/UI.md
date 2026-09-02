# Selective UI tests

The **ui** gate runs Playwright or Cypress, but **only the specs that cover
what changed**. A full browser suite on every commit is slow and burns CI
minutes; this gate pays for browsers only when the diff actually touches a
test, a page it visits, or a module it imports.

## When it runs

Order in `quality run`: format → lint → DRY → security → compile → **ui** →
version → review.

| Situation | What happens |
| --- | --- |
| No `playwright.config.*` / `cypress.config.*` / those packages | **skip** |
| Compile in this run **failed** | **skip** (fix the build first) |
| Compile **skipped** (Python-only, etc.) | UI still runs |
| Diff does not touch any spec, import, route, or coverage hit | **skip** (no browser) |
| Shared config / global-setup / Cypress support changed | **all** specs |
| Spec file itself changed | that spec |
| GitHub Actions, default | **skip** even in `ci.mode=github\|both` |

Skip does **not** fail the build.

## How a spec is selected

Changed files come from `git diff` vs `--base` (or `QUALITY_REVIEW_BASE` /
`GITHUB_BASE_REF`). A spec is included when any of these match:

1. **The spec changed**
2. **Import graph** — relative imports and `@/` → `src/` (configurable aliases)
3. **Name / path** — `checkout.spec.ts` ↔ `Checkout.tsx` or `app/checkout/`
   (stems shorter than 4 characters are ignored to avoid noise)
4. **`page.goto` / `cy.visit`** vs App Router / Pages routes
   (`/checkout` → `app/checkout/page.tsx`, `pages/checkout.tsx`, …)
5. **Coverage invert** — optional map of test → source files

```json
{
  "e2e/checkout.spec.ts": [
    "src/app/checkout/page.tsx",
    "src/components/Cart.tsx"
  ]
}
```

Default path: `.quality-reports/ui-coverage.json`. Override with
`[quality.ui] coverage_map`.

Unit tests named `*.test.ts` under `src/` are ignored unless they import
Playwright/Cypress or live under `e2e` / `playwright` / `cypress`.

## Commands

```bash
quality ui                 # select from the diff, then run
quality ui --list          # print the selection, no browser
quality ui --all           # every spec
quality ui --base origin/main
quality run --only ui
```

Force every spec via config or env: `[quality.ui] select = "all"` or
`QUALITY_UI_ALL=1`.

## Stay off GitHub (default)

Installing browsers on hosted runners is the expensive part. The gate stays
local-first:

```toml
[quality.ui]
select = "changed"          # changed | all
framework = "auto"          # auto | playwright | cypress
on_github = false
# spec_dirs = ["e2e"]       # optional: only look here
# coverage_map = ".quality-reports/ui-coverage.json"

[quality.ui.path_aliases]
"@/" = "src/"
```

Opt into Actions with `on_github = true` or `QUALITY_UI_ON_GITHUB=1`. Pre-push
already runs `dry,security,compile,ui` on the developer machine.

## Runners

- Playwright: `playwright test --reporter=list <specs>` (project binary or `npx`)
- Cypress: `cypress run --spec a,b,c`

Missing browsers/tools → skip with an install hint, not a red build.
