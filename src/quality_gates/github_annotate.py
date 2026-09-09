"""GitHub Actions workflow commands so checks show the real failure, not the YAML line."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from quality_gates.models import Finding, GateResult

_UNFORMATTED = ("would reformat:", "unformatted:")


def github_annotation(
    message: str,
    *,
    level: str = "error",
    title: str | None = None,
    path: str | None = None,
    line: int | None = None,
    column: int | None = None,
) -> str:
    """Return one workflow command. Print it so Actions attaches it to a source file."""
    bits = [f"::{_level(level)}"]
    args: list[str] = []
    if path:
        args.append(f"file={_escape(path)}")
    if line:
        args.append(f"line={int(line)}")
    if column:
        args.append(f"col={int(column)}")
    if title:
        args.append(f"title={_escape(title)}")
    if args:
        bits.append(" " + ",".join(args))
    bits.append(f"::{_escape(message)}")
    return "".join(bits)


def emit_github_annotation(
    message: str,
    *,
    level: str = "error",
    title: str | None = None,
    path: str | None = None,
    line: int | None = None,
    column: int | None = None,
) -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    print(
        github_annotation(
            message, level=level, title=title, path=path, line=line, column=column
        ),
        flush=True,
    )


def write_github_summary(body: str) -> None:
    dest = os.environ.get("GITHUB_STEP_SUMMARY")
    if not dest:
        return
    text = body if body.endswith("\n") else body + "\n"
    with Path(dest).open("a", encoding="utf-8") as handle:
        handle.write(text)


def emit_result_annotations(results: list[GateResult]) -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    for result in results:
        findings = list(result.findings)
        if result.status == "fail" and not any(
            item.severity == "error" for item in findings
        ):
            findings.append(_fallback_finding(result))
        for finding in findings:
            print(_from_finding(finding), flush=True)


def summary_from_results(results: list[GateResult]) -> str:
    failed = [item for item in results if item.status == "fail"]
    errors = [
        finding
        for result in results
        for finding in result.findings
        if finding.severity == "error"
    ]
    lines = ["## The Code Sheriff", ""]
    if not failed and not errors:
        lines.append("Gates passed.")
        return "\n".join(lines) + "\n"
    lines.append(
        "GitHub's `.github:N Process completed with exit code 1` line is the "
        "workflow step, not the bug. The rows below are."
    )
    lines.extend(["", "| Gate | Where | What |", "| --- | --- | --- |"])
    rows = errors or [_fallback_finding(result) for result in failed]
    for finding in rows[:20]:
        where = finding.path or finding.gate
        if finding.line and finding.path:
            where = f"{finding.path}:{finding.line}"
        what = (finding.message or "").replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {finding.gate} | `{where}` | {what[:200]} |")
    return "\n".join(lines) + "\n"


def run_ruff_github(paths: list[str]) -> int:
    """Run ruff so each finding is a source-file annotation, not a workflow-line error."""
    from quality_gates.tools import run

    cwd = Path.cwd()
    if not paths:
        paths = ["src", "tests"]
    check = run(["ruff", "check", "--output-format=github", *paths], cwd=cwd)
    if check.skipped:
        print(
            github_annotation(
                check.skip_reason or "ruff is not installed", title="ruff"
            ),
            flush=True,
        )
        return 1
    if check.stdout:
        sys.stdout.write(check.stdout)
        if not check.stdout.endswith("\n"):
            sys.stdout.write("\n")
    if check.stderr:
        sys.stderr.write(check.stderr)
    fmt = run(["ruff", "format", "--check", *paths], cwd=cwd)
    combined = f"{fmt.stdout or ''}{fmt.stderr or ''}"
    if fmt.stdout:
        sys.stdout.write(fmt.stdout)
        if not fmt.stdout.endswith("\n"):
            sys.stdout.write("\n")
    if fmt.stderr:
        sys.stderr.write(fmt.stderr)
    unformatted: list[str] = []
    if fmt.returncode not in {0, None}:
        for raw in combined.splitlines():
            path = unformatted_path(raw)
            if path:
                unformatted.append(path)
                print(
                    github_annotation(
                        f"File is not formatted. Run: ruff format {path}",
                        title="ruff-format",
                        path=path,
                    ),
                    flush=True,
                )
        if not unformatted:
            print(
                github_annotation(
                    (fmt.stderr or fmt.stdout or "ruff format --check failed").strip()
                    or "ruff format --check failed",
                    title="ruff-format",
                ),
                flush=True,
            )
    failed = check.returncode not in {0, None} or fmt.returncode not in {0, None}
    if failed:
        rows = []
        if check.returncode not in {0, None}:
            rows.append("ruff check failed (annotations on the source files above).")
        for path in unformatted:
            rows.append(f"`{path}` needs `ruff format`")
        write_github_summary(
            "## Ruff\n\n" + "\n".join(f"- {row}" for row in rows) + "\n"
        )
    return 1 if failed else 0


def unformatted_path(line: str) -> str | None:
    body = (line or "").strip()
    if not body:
        return None
    lowered = body.lower()
    for prefix in _UNFORMATTED:
        if lowered.startswith(prefix):
            return body.split(":", 1)[-1].strip() or None
    return None


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["ruff"]:
        return run_ruff_github(args[1:])
    print(
        "usage: python -m quality_gates.github_annotate ruff [paths...]",
        file=sys.stderr,
    )
    return 2


def _from_finding(finding: Finding) -> str:
    title = "/".join(part for part in (finding.gate, finding.rule) if part) or "quality"
    detail = finding.message or f"{finding.gate} failed"
    if finding.snippet:
        detail += f" At: {finding.snippet}."
    if finding.reason:
        detail += f" Why: {finding.reason}."
    if finding.suggestion:
        detail += f" Fix: {finding.suggestion}"
    return github_annotation(
        detail,
        level="error" if finding.severity == "error" else "warning",
        title=title,
        path=finding.path,
        line=finding.line,
        column=finding.column,
    )


def _fallback_finding(result: GateResult) -> Finding:
    note = next((item for item in result.notes if item.strip()), "")
    message = note or f"{result.name} failed with no parseable diagnostics"
    return Finding(
        gate=result.name,
        rule="execution-failed",
        severity="error",
        message=message,
    )


def _level(level: str) -> str:
    if level in {"error", "warning", "notice"}:
        return level
    return "error"


def _escape(value: str) -> str:
    return (
        value.replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
        .replace(",", "%2C")
        .replace(":", "%3A")
    )


if __name__ == "__main__":
    raise SystemExit(main())
