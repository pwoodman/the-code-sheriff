# Contributing

Use Python 3.11 or newer, create a virtual environment, then run:

```bash
python -m pip install -e ".[dev]"
pytest
ruff check src tests
ruff format --check src tests
python -m build
quality run --skip review
```

Add tests for behavior changes and update `CHANGELOG.md`. Keep adapters
deterministic where possible, never invoke commands through a shell, and do not
add an automatic download without a pinned version, platform selector, license,
and verified SHA-256 in `configs/tool-manifest.json`.
