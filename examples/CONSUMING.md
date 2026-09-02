# How to consume this toolkit from another repository

After this repo lives on GitHub as `YOUR_ORG/quality-gates`, pick one path.

## Path A — CLI only (smallest diff)

```yaml
# .github/workflows/quality.yml
name: Quality gates
on:
  pull_request:
  push:
    branches: [main]
permissions:
  contents: read
  pull-requests: write
jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install "git+https://github.com/YOUR_ORG/quality-gates.git@v1"
      - run: quality doctor --install
        env:
          QUALITY_GATES_AUTO_INSTALL: "1"
      - run: quality run
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

Copy `quality.toml` from this repo and trim `fail_on` / SQL dialect as needed.

## Path B — multi-job reusable workflow

Vendor `.github/workflows/quality.yml` and `.github/actions/` from this repo
into the consumer (GitHub resolves `uses: ./...` against the *caller*). Then
the PR checks UI shows Detect → Format → Lint → DRY → Security → Review as
separate jobs.

```yaml
jobs:
  quality:
    uses: YOUR_ORG/quality-gates/.github/workflows/quality.yml@v1
    secrets: inherit
```

only works if the caller also has the composite actions, or is this repository.

## Path C — local hooks after every commit

```bash
pip install -e git+https://github.com/YOUR_ORG/quality-gates.git#egg=quality-gates
pre-commit install --hook-type pre-commit --hook-type pre-push
```

Format and lint run on commit; secrets scan on `git push`. CI still runs the
full DRY + security + AI review suite so a skipped hook cannot bypass the bar.
