"""Annotate GitHub Actions with the failing test, not the workflow YAML line."""

from __future__ import annotations

import os
from pathlib import Path

_FAILURES: list[tuple[str, str, int | None, str]] = []


def pytest_runtest_logreport(report) -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true" or not report.failed:
        return
    if report.when not in {"setup", "call"}:
        return
    path = _relpath(getattr(report, "path", None) or getattr(report, "fspath", None))
    lineno = report.location[1] if report.location else None
    line = (lineno + 1) if isinstance(lineno, int) else None
    detail = (
        getattr(report, "longreprtext", None) or str(report.longrepr or "")
    ).strip()
    headline = _headline(detail) or report.nodeid
    _FAILURES.append((report.nodeid, path, line, headline))
    from quality_gates.github_annotate import emit_github_annotation

    emit_github_annotation(
        f"{report.nodeid}: {headline}"[:65000],
        title="pytest",
        path=path or None,
        line=line,
    )


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true" or not _FAILURES:
        return
    from quality_gates.github_annotate import write_github_summary

    lines = [
        "## Pytest failures",
        "",
        "The `.github:N Process completed with exit code 1` annotation is the "
        "workflow step. These are the tests:",
        "",
    ]
    for nodeid, path, line, headline in _FAILURES[:20]:
        where = f"{path}:{line}" if path and line else path or nodeid
        lines.append(f"- `{where}` — {headline[:200]}")
    write_github_summary("\n".join(lines) + "\n")


def _relpath(value: object) -> str:
    if value is None:
        return ""
    raw = str(value)
    try:
        return Path(raw).resolve().relative_to(Path.cwd().resolve()).as_posix()
    except (OSError, ValueError):
        return raw.replace("\\", "/")


def _headline(detail: str) -> str:
    rows = [row.strip() for row in detail.splitlines() if row.strip()]
    for row in reversed(rows):
        if row.startswith("E ") or "Error" in row or "assert " in row:
            return row.lstrip("E ").strip()
    return rows[-1] if rows else ""
