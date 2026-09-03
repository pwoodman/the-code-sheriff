# 120-point repository audit

The `audit` gate runs a **static** 120-point inspection aimed at weaknesses common
in AI-generated code: security, API authorization, architecture, incomplete
implementations, persistence, performance hints, frontend, UX, and supply chain.

The catalog lives in `src/quality_gates/audit/catalog.py` (ids 1–120). This page
does not copy the checklist.

## What “finding” means

A check is a **confirmed defect** only with HIGH-confidence evidence: a file, line,
and snippet. The gate does **not** attempt exploits, drive a browser, or invent
theoretical issues.

Each check ends as one of:

| Status | Meaning |
| --- | --- |
| `finding` | Evidence-backed defect (see `.quality-reports/audit.md`) |
| `pass` | Scanner ran on this repo; no evidence |
| `not_applicable` | Required surface missing (no HTTP API, no frontend, …) |
| `not_statically_provable` | Needs runtime, product review, or a human (LCP, a11y, workflow) |
| `skipped` | Listed in `[quality.audit] skip` |

Duplicate hits at the same file:line are grouped. Low-confidence guesses are not
reported as defects.

The static incomplete/dead-code checks include production TODO/FIXME markers
for all source kinds plus parser-backed empty bodies, unused imports, and
unreachable statements for Python. Intentional Python interfaces declared with
`Protocol`, `@abstractmethod`, or `@overload` are excluded.

Narrow lexical detectors recognize explicit empty callable bodies across the
registered C-style, Ruby, Lua, R, MATLAB, shell, and PowerShell syntax families.
Same-block unreachable checks are limited to C-style brace languages where an
unconditional terminator, indentation, and following statement align.
Unreachable detection remains explicitly unsupported for Ruby, Lua, R, MATLAB,
shell, and PowerShell; native/project linters can supply those diagnostics when
installed. The audit does not label these lexical checks as AST precision.
These P1 findings are warnings under the default policy.

## Defaults

```toml
[quality.audit]
fail_on_priority = ["P0"]     # CRITICAL / P0 findings fail the gate
min_confidence = "HIGH"
# skip = [88]                 # optional check ids
enabled = true
```

P1+ HIGH findings are **warnings** unless you add those priorities to
`fail_on_priority`. Authentication, cryptography, and migrations are never
auto-fixed.

## Where it runs

Audit is cheap (no test suite, no browsers). Default `github_gates` includes it.

Findings use the inspection format (ID, severity, confidence, evidence, scenario,
fix, auto-fix = No, regression test). Reports:

- `.quality-reports/audit.json`
- `.quality-reports/audit.md`
