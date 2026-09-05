# Third-party review eval sets

## Macroscope 118-bug set

Not published as a downloadable corpus. Methodology and one sample
(apache/commons-math GCD overflow, fix `dabf3a5`) are described at
https://macroscope.com/blog/code-review-benchmark

We reconstruct that sample as `tests/fixtures/review_bench/macroscope_gcd_overflow.*`.

## Martian Code Review Bench (MIT)

https://github.com/withmartian/code-review-benchmark

50 PRs with human-verified golden comments. The same set was used to score
Macroscope, Cursor Bugbot, Greptile, and Sourcery. Fetch locally:

```bash
quality eval --suite martian --download
```

Goldens land in `.quality-reports/eval/martian/` (gitignored via `.quality-reports`).
Citation: Zverianskii et al., Code Review Bench, 2026.
