# Risk-triggered verification

`quality run --changed` selects the smallest ordinary verification plan, then
adds a required gate only when executable production paths indicate a risk:
database migrations, authorization/tenant boundaries, failure-state handling,
critical validation/algorithm logic, or performance-sensitive paths.

Each risk gate requires an approved repository command. For example:

```toml
[quality.migration]
command = ["./scripts/verify-migrations"]
timeout = 900

[quality.authorization]
command = ["pytest", "-q", "tests/auth"]

[quality.resilience]
command = ["pytest", "-q", "tests/retries"]

[quality.mutation]
command = ["mutmut", "run", "--paths-to-mutate", "src/critical"]

[quality.performance]
command = ["pytest", "-q", "benchmarks", "--benchmark-only"]
```

An absent command is reported as **unsupported** and blocks when the associated
surface changed; it is never a pass. Commands run only with trusted execution.
For pull requests, configure an isolated worker and keep repository credentials
out of the worker.

Every result carries the source snapshot, effective configuration, selection,
tool/environment details, and hosted runner identity when available. Existing
coverage reports require matching provenance, so stale artifacts cannot satisfy
a changed run.

Policy exceptions must be narrow and include `owner`, `approved_by`, `reason`,
and a timezone-qualified `expires` timestamp. They are read from the trusted
base policy for pull requests and appear on affected findings.
