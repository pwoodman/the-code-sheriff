# Selective UI tests

The **ui** gate runs Playwright or Cypress, but **only specs that touch a
file you added or changed**. A full browser suite on every commit is slow;
this gate starts a browser only when the diff intersects a spec's touch set.

Filename similarity is ignored. `checkout.spec.ts` does **not** run just
because you edited `Checkout.tsx`. It runs if that spec imports it, visits a
page that imports it, or a coverage map says it covered it.

## When it runs

Order in `quality run`: format → lint → DRY → security → compile → **ui** →
version → review.

| Situation | What happens |
| --- | --- |
| No `playwright.config.*` / `cypress.config.*` / those packages | **skip** |
| Compile in this run **failed** | **skip** (fix the build first) |
| Compile **skipped** (Python-only, etc.) | UI still runs |
| Diff does not intersect any spec's touch set | **skip** (no browser) |
| Shared config, global-setup, Cypress support, or root `app/layout` / `_app` | **all** specs |
| Spec file itself added or changed | that spec |
| GitHub Actions, default | **skip** even in `ci.mode=github\|both` |

Skip does **not** fail the build.

## Touch set (narrow scope)

Changed files come from `git diff` vs `--base`. A spec runs when the diff
hits any of:

1. **The spec**
2. **Its import graph** — relative imports and `@/` → `src/` (configurable)
3. **Visited routes** — `page.goto` / `cy.visit` mapped to App Router / Pages /
   SvelteKit files, **then that page's imports**. `/checkout` →
   `src/app/checkout/page.tsx` → `Cart.tsx` it imports.
4. **Coverage invert** — optional map of test → source files

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
`QUALITY_UI_ALL=1`. `select = "changed"` (aliases `touched`, `narrow`) is
the default.

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
