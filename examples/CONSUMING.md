# How to consume this toolkit from another repository

After this repo lives on GitHub as `YOUR_ORG/quality-gates`, pick one path.

Heavy gates default to **developer machines**. GitHub Actions only does version
+ PR review unless you set `ci.mode` to `github` or `both`.

## Path A — CLI (recommended)

Copy `quality.toml` (keep `ci.mode = "local"`). Add this workflow:

See [`consumer-cli.yml`](consumer-cli.yml). On Actions, `quality run` is cheap.
On laptops:

```bash
pip install "git+https://github.com/YOUR_ORG/quality-gates.git@v1"
pre-commit install --hook-type pre-commit --hook-type pre-push
quality run --skip review
```

To spend GitHub minutes on the full suite, either:

```toml
[quality.ci]
mode = "both"
```

or re-run the workflow with **full_suite**, or `QUALITY_CI_FULL=1 quality run --full`.

## Path B — multi-job reusable workflow

Vendor `.github/workflows/quality.yml` and `.github/actions/` if you want the
Detect → Format → … UI. With `ci.mode = "local"` those heavy jobs stay skipped.

## Path C — hooks only

```bash
pre-commit install --hook-type pre-commit --hook-type pre-push
```

Commit: format, lint, version. Push: DRY, security, compile (compile is refused
until security is clean).
