# Policy: call it out without blocking old PRs

Three modes. Same scanners. Different **exit codes**.

| Policy | Job fails when | Use for |
| --- | --- | --- |
| `observe` | never | Week 1 on a brownfield repo, or a 100-repo org rollout |
| `adopt` | **new** findings vs `.quality-baseline.json`, or **coverage drop** | Default for existing codebases |
| `enforce` | anything in `fail_on` (industry floors, P0 audit, …) | New repos and this toolkit |

```toml
[quality]
policy = "adopt"                       # observe | adopt | enforce
baseline = ".quality-baseline.json"    # committed; not .quality-reports/
comment_on_pr = true
```

Override for one run or a whole org:

```bash
quality --policy observe run --skip review
QUALITY_POLICY=observe quality run     # fleet mute / first week
```

## Old repo (do not stir a mess)

```bash
pip install "git+https://github.com/YOUR_ORG/quality-gates.git@v1"
quality init --org YOUR_ORG --policy adopt
quality run --skip review              # reports everything; does not fail yet
quality baseline                       # grandfather today's findings + coverage
git add quality.toml .quality-baseline.json .github/workflows/quality-cli.yml
```

The next PR:

- Still **posts a comment** (warnings, grandfathered hits, coverage).
- **Fails** only if you add a new fingerprint (`gate|rule|path`) or coverage drops more than 1 point below the baseline.
- Does **not** demand 80% coverage, a version bump for the backlog, or fixing 16 unpinned Actions on day one.

After you fix a class of issues:

```bash
quality run --skip review
quality baseline --ratchet             # union fingerprints; raise coverage floor if it went up
```

Never shrink the baseline to hide a new defect.

## Ignore a single finding

Inline, next-line, or file header:

```python
eval(sample)  # quality:ignore eval
# quality:ignore-next-line eval
eval(sample)
# quality:ignore-file missing-tests
```

Durable (expires, attributed):

```bash
quality ignore add --rule eval --path src/app.py --reason "test fixture" --owner you --days 90
```

That appends `.quality/ignore.toml`. For merge-policy exceptions with `approved_by`, keep using `[[quality.exceptions]]`.

Last-run errors live in `.quality-reports/findings-last.json` (previous copy in `findings-previous.json`). If the snippet is still in the file, the next run reopens the finding even when the current scanner missed it.

## Test timing

Touched tests that run **15% slower** (and at least 50ms slower) than the last good duration fail with `timing-regression`. Thresholds:

```toml
[quality.test]
require_for_source = true
timing = true
timing_regression_pct = 15
timing_min_delta_ms = 50
```

Accept a slower duration on purpose:

```bash
quality timing accept --test tests/test_app.py::test_ok
quality timing accept --all-regressed
```

Or ignore with `# quality:ignore-file timing-regression` / `quality ignore add --rule timing-regression`.

## New repo

```bash
quality init --org YOUR_ORG --policy enforce
```

Industry 80% line floor and P0 audit failures block the PR. Skip ≠ fail when a gate does not apply.

## One repo vs 100 repos

**One repo:** hooks on the laptop (`ci.mode = local`), cheap Actions job (impact + audit + version + review comment). Baseline committed. Promote `adopt` → `enforce` when the backlog is gone.

**Ten to a hundred repos:**

1. Pin **one** quality-gates version in an org reusable workflow (`@v1` or a SHA).
2. Add the same cheap workflow to every repo (Path A in `examples/CONSUMING.md`). Do **not** turn on `ci.mode = github` org-wide — that is how you burn runner minutes.
3. Ship `policy = observe` (or `QUALITY_POLICY=observe` on the org workflow) for a few days: comments only, green checks, people see the report.
4. Flip to `adopt` and land a baseline PR per repo (`quality baseline`). That PR should stay green.
5. Enforce **per repo** when that team is ready. Do not flip 100 repos to `enforce` on the same Monday.
6. Keep Playwright/Cypress off Actions unless a repo opts in.

Heavy work (format, lint, DRY, tests/coverage, compile, UI) stays on developer machines. GitHub stays the ratchet + comment. That is the only shape that stays cheap at 100 repos.

Secrets and new P0s are still **called out** in observe/adopt (annotations + PR comment). They only **block** in adopt once they are *new* vs the baseline, or in enforce always.
