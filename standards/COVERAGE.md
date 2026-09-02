# Test coverage gate

The `coverage` gate fails when measured **line** coverage is below a configurable floor.

## Default: 80% lines

80% statement/line coverage is the common contractual floor in industry QA practice
(ISTQB-style targets, Coveralls/Codecov defaults, many engineering handbooks). It is
a **starting** bar, not a proof of quality.

Branch coverage is **not** enforced unless you set it:

```toml
[quality.coverage]
line = 80          # fail below this percent
branch = 0         # 0 = do not fail on branch coverage
tool = "auto"      # auto | pytest | jest | vitest | go | existing
enabled = true
```

Raise or lower `line` for the repo. Do not change the package default unless the
product standard changes.

## How it collects numbers

1. `pytest --cov` when pytest-cov is installed and Python tests exist.
2. Jest / Vitest `--coverage` (`coverage/coverage-summary.json`).
3. `go test ./... -coverprofile`.
4. Existing `coverage.xml`, `lcov.info`, or Istanbul summary files.

No tests, or no tool and no report → **skip**. Skip ≠ fail.

Coverage **runs the test suite**, so it stays on developer machines in
`ci.mode = local`. It is not in default `github_gates`.

Report: `.quality-reports/coverage.json` (and `coverage.xml` when pytest-cov ran).
