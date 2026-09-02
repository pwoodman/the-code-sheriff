# Changelog

## 1.3.0

- Impact gate: upstream (imports) and downstream (importers) analysis on the
  git diff. Fails when a downstream consumer was not updated and no test covers
  the change. Broken in-repo imports fail. Report: `.quality-reports/impact.json`.
- UI selection now expands the diff with downstream importers, so a util change
  still runs specs that visit pages that consume it.
- Cheap GitHub Actions path includes `impact` (no browsers).

## 1.2.1

- UI selection is **touch-scoped**: a spec runs only if the diff hits the spec,
  its imports, a page it visits (and that page's imports), or a coverage map
  entry. Filename guesses like `checkout.spec.ts` ↔ `Checkout.tsx` no longer
  pull in unrelated tests. Root `app/layout` / `_app` still runs the full suite.

## 1.2.0

- UI gate: selective Playwright/Cypress. Only specs that cover added or changed
  files run (spec itself, imports, route `goto`/`visit`, name/path, optional
  coverage map). Shared config changes run the full suite; unrelated diffs skip.
- UI stays **off GitHub Actions** by default even when `ci.mode` is `github` /
  `both` — browser installs are the expensive part. Opt in with
  `[quality.ui] on_github = true` or `QUALITY_UI_ON_GITHUB=1`.
- Pre-push now includes `ui` after compile. Skip ≠ fail when no UI project exists.

## 1.1.0

- Version gate: semver consistency, required bumps on source changes, `quality bump`.
- Compile gate for C#, Rust, Go, Java, and TypeScript — only after a clean security scan.
- Local-first CI (`[quality.ci] mode = "local"`): heavy gates run on developer machines; GitHub Actions stays cheap unless you set `github` / `both` or dispatch `full_suite`.

## 1.0.0

- Initial format, lint, DRY, security, and AI review gates.
