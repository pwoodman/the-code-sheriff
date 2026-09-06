from __future__ import annotations

import re
import shlex
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path

from quality_gates.config import QualityConfig, find_project_config
from quality_gates.detect import (
    TOOLCHAIN_BY_LANGUAGE,
    iter_project_files,
)
from quality_gates.diagnostics import enrich_findings
from quality_gates.models import Finding, GateResult, RunResult
from quality_gates.paths import bundled_file
from quality_gates.redact import redact_secrets as _redact
from quality_gates.registry import gate_language, source_suffixes
from quality_gates.tools import which


def files_for_language(root: Path, config: QualityConfig, language: str) -> list[Path]:
    wanted = source_suffixes(language)
    return [
        path
        for path in iter_project_files(root, config)
        if path.suffix.lower() in wanted
    ]


def normalize_gate_languages(languages: list[str]) -> list[str]:
    unique: list[str] = []
    for language in languages:
        mapped = gate_language(language)
        if mapped not in unique:
            unique.append(mapped)
    return unique


def source_files(root: Path, config: QualityConfig, language: str) -> list[Path]:
    files = files_for_language(root, config, language)
    if language == "javascript":
        files += files_for_language(root, config, "typescript")
        files += files_for_language(root, config, "react")
    return files


def relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def skip_result(name: str, reason: str, tool: str | None = None) -> GateResult:
    skipped = [tool] if tool else []
    # Preserve the public ``skip`` status for report compatibility while making
    # the reason machine-readable to the decision evaluator. A missing required
    # executable is unsupported; an irrelevant gate is not applicable.
    state = "unsupported" if tool else "not-applicable"
    return GateResult(
        name=name,
        status="skip",
        notes=[reason],
        skipped_tools=skipped,
        exit_state=state,
    )


def fail_or_pass(
    name: str,
    findings: list[Finding],
    notes: list[str] | None = None,
    *,
    root: Path | None = None,
    run: RunResult | None = None,
) -> GateResult:
    resolved = root
    if resolved is None and run is not None:
        resolved = _result_root(run)
    findings = enrich_findings(findings, resolved, run)
    errors = [item for item in findings if item.severity == "error"]
    # A tool can fail before it emits a parseable diagnostic. Its non-zero exit
    # is still verification evidence and must not become a false green.
    if run is not None and run.returncode not in {None, 0} and not errors:
        findings.append(
            Finding(
                gate=name,
                rule="execution-failed",
                message=f"verification command exited {run.returncode}",
                severity="error",
            )
        )
        errors = [findings[-1]]
    status = "fail" if errors else "pass"
    extra = execution_details(run) if run else {}
    return GateResult(
        name=name,
        status=status,
        findings=findings,
        notes=notes or [],
        **extra,
    )


def merge_results(name: str, parts: Iterable[GateResult]) -> GateResult:
    from quality_gates.decision import ExecutionState, execution_state

    collected = list(parts)
    findings: list[Finding] = []
    notes: list[str] = []
    skipped: list[str] = []
    tool_errors: list[str] = []
    saw_fail = False
    saw_pass = False
    first_fail: GateResult | None = None
    first_with_command: GateResult | None = None
    for part in collected:
        findings.extend(part.findings)
        notes.extend(part.notes)
        skipped.extend(part.skipped_tools)
        tool_errors.extend(part.tool_errors)
        if part.status == "fail" or part.error_count() > 0:
            saw_fail = True
            if first_fail is None:
                first_fail = part
        elif part.status == "pass":
            saw_pass = True
        if part.command and first_with_command is None:
            first_with_command = part

    states = [execution_state(part) for part in collected]
    if saw_fail or any(s == ExecutionState.FAILED for s in states):
        status = "fail"
        exit_state = "failed"
    elif tool_errors or any(s == ExecutionState.ERRORED for s in states):
        status = "fail"
        exit_state = "errored"
    elif any(s == ExecutionState.BLOCKED for s in states):
        status = "blocked"
        exit_state = "blocked"
    elif any(s == ExecutionState.UNSUPPORTED for s in states):
        status = "skip"
        exit_state = "unsupported"
    elif any(s == ExecutionState.CANCELLED for s in states):
        status = "cancelled"
        exit_state = "cancelled"
    elif saw_pass or any(s == ExecutionState.PASSED for s in states):
        status = "pass"
        exit_state = "passed"
    else:
        status = "skip"
        exit_state = "not-applicable"
        if not notes:
            notes.append("no applicable tools ran")

    source = first_fail or first_with_command
    extra: dict[str, object] = {}
    if source is not None:
        extra = {
            "tool": source.tool,
            "command": source.command,
            "working_directory": source.working_directory,
            "return_code": source.return_code,
            "output_excerpt": source.output_excerpt,
        }
    extra["exit_state"] = exit_state
    return GateResult(
        name=name,
        status=status,
        findings=sorted(
            findings,
            key=lambda item: (
                item.path or "",
                item.line or 0,
                item.column or 0,
                item.rule or "",
                item.message,
            ),
        ),
        notes=sorted(dict.fromkeys(notes)),
        skipped_tools=sorted(dict.fromkeys(skipped)),
        tool_errors=sorted(dict.fromkeys(tool_errors)),
        **extra,
    )


def ruff_config(root: Path) -> list[str]:
    found = find_project_config(
        root,
        ["ruff.toml", ".ruff.toml", "pyproject.toml"],
    )
    if found and found.name != "pyproject.toml":
        return ["--config", str(found)]
    bundled = bundled_file("ruff.toml")
    if not found and bundled.is_file():
        return ["--config", str(bundled)]
    return []


def prettier_config(root: Path) -> Path:
    found = find_project_config(
        root,
        [
            ".prettierrc",
            ".prettierrc.json",
            ".prettierrc.yml",
            ".prettierrc.yaml",
            "prettier.config.js",
            "prettier.config.cjs",
            "prettier.config.mjs",
        ],
    )
    return found or bundled_file("prettier.json")


def eslint_config(root: Path) -> Path:
    found = find_project_config(
        root,
        [
            "eslint.config.js",
            "eslint.config.mjs",
            "eslint.config.cjs",
            "eslint.config.ts",
            ".eslintrc.json",
            ".eslintrc.js",
        ],
    )
    if found:
        return found
    from quality_gates.paths import tooling_js_dir

    nested = tooling_js_dir() / "eslint.config.js"
    if nested.is_file():
        return nested
    return bundled_file("eslint.config.js")


def sqlfluff_config(root: Path) -> Path:
    found = find_project_config(root, [".sqlfluff", "setup.cfg"])
    return found or bundled_file("sqlfluff.ini")


def findings_from_text(
    gate: str,
    result: RunResult,
    *,
    language: str | None = None,
    default_message: str | None = None,
    root: Path | None = None,
) -> list[Finding]:
    if result.skipped:
        return []
    text = result.combined
    if result.returncode == 0 and not text:
        return []
    findings: list[Finding] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parsed = _parse_diagnostic_line(stripped, root or _result_root(result))
        if parsed is not None:
            path, line_no, column, severity, message, rule = parsed
            findings.append(
                Finding(
                    gate=gate,
                    message=message,
                    severity=severity,
                    path=path,
                    line=line_no,
                    column=column,
                    rule=rule,
                    language=language,
                    tool=result.tool,
                )
            )
            continue
        if result.returncode == 0:
            continue
        findings.append(
            Finding(
                gate=gate,
                message=stripped[:500],
                language=language,
                tool=result.tool,
            )
        )
    if not findings and result.returncode != 0:
        findings.append(
            Finding(
                gate=gate,
                message=default_message or f"command failed: {' '.join(result.argv)}",
                language=language,
                tool=result.tool,
            )
        )
    return enrich_findings(findings, root or _result_root(result), result)


_DIAGNOSTIC_LINE = re.compile(
    r"^(?P<path>.+):(?P<line>\d+):(?P<column>\d+):\s*"
    r"(?:\[(?P<bracket_level>error|warning|info|note)\]|"
    r"(?P<plain_level>error|warning|info|note):)?\s*"
    r"(?P<message>.*?)(?:\s+\((?P<rule>[^()]+)\))?$",
    re.IGNORECASE,
)


def execution_details(result: RunResult) -> dict[str, object]:
    """Return redacted command context suitable for user-facing reports."""
    excerpt = _redact(result.combined.strip())[:2000] or None
    errors = [result.tool_error] if result.tool_error else []
    return {
        "tool": result.tool,
        "exit_state": result.exit_state,
        "tool_errors": errors,
        "command": [_redact(part) for part in result.argv],
        "working_directory": result.cwd,
        "return_code": result.returncode,
        "output_excerpt": excerpt,
    }


def format_command(argv: list[str]) -> str:
    return shlex.join(_redact(part) for part in argv)


def _parse_diagnostic_line(
    value: str, root: Path | None
) -> tuple[str, int, int, str, str, str | None] | None:
    match = _DIAGNOSTIC_LINE.match(value)
    if not match:
        return None
    raw_path = match.group("path")
    path = Path(raw_path)
    if root is not None:
        with suppress(OSError, ValueError):
            path = path.resolve().relative_to(root.resolve())
    level = match.group("bracket_level") or match.group("plain_level") or "error"
    severity = "warning" if level.lower() in {"warning", "info", "note"} else "error"
    return (
        path.as_posix(),
        int(match.group("line")),
        int(match.group("column")),
        severity,
        match.group("message").strip()[:500],
        match.group("rule"),
    )


def _result_root(result: RunResult) -> Path | None:
    return Path(result.cwd) if result.cwd else None


def tool_or_skip(
    name: str,
    project: Path,
    prefer_project: bool,
    gate: str,
    language: str,
) -> str | GateResult:
    path = which(name, project=project, prefer_project=prefer_project)
    if path:
        return path
    return skip_result(
        gate,
        f"{name} is not installed — run `quality doctor --install` or install the {language} toolchain",
        tool=name,
    )


def toolchain_for(language: str) -> str:
    return TOOLCHAIN_BY_LANGUAGE.get(language, language)
