# Evaluation methodology

`quality eval --suite reviewbench` scores labeled diffs:

- **Must-catch** fixtures must produce a finding (recall).
- **Hard negatives** must stay quiet (precision).
- Volume is capped so a noisy reviewer cannot game recall.

Optional suites:

- `martian` — MIT Code Review Bench goldens (`--download`).
- `macroscope` — reconstructed commons-math GCD sample.

The scorecard is written to `.quality-reports/eval/SCORECARD.md`. Settings,
suite versions, and uncertainty belong in that file. Marketing claims must
cite a held-out run of this harness, not chat transcripts.
