from __future__ import annotations

import contextlib
import json
import re
from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.gates.common import (
    eslint_config,
    fail_or_pass,
    findings_from_text,
    merge_results,
    normalize_gate_languages,
    relative,
    ruff_config,
    skip_result,
    source_files,
    sqlfluff_config,
    tool_or_skip,
)
from quality_gates.installers import (
    ensure_checkstyle,
    ensure_golangci_lint,
    ensure_node_tooling,
)
from quality_gates.models import Finding, GateResult
from quality_gates.paths import bundled_file, tooling_js_dir
from quality_gates.tools import prepend_path, run, which


def run_lint(root: Path, config: QualityConfig, languages: list[str]) -> GateResult:
    unique = normalize_gate_languages(languages)
    parts = [_lint_language(root, config, language) for language in unique]
    if not parts:
        return skip_result("lint", "no supported languages detected")
    return merge_results("lint", parts)


def _lint_language(root: Path, config: QualityConfig, language: str) -> GateResult:
    files = source_files(root, config, language)
    if not files:
        return skip_result("lint", f"no {language} files")
    dispatch = {
        "python": _python,
        "javascript": _node,
        "go": _go,
        "rust": _rust,
        "java": _java,
        "csharp": _csharp,
        "sql": _sql,
    }
    handler = dispatch.get(language)
    if handler is None:
        return skip_result("lint", f"no linter mapped for {language}")
    return handler(root, config, files)


def _python(root: Path, config: QualityConfig, files: list[Path]) -> GateResult:
    ruff = tool_or_skip("ruff", root, config.prefer_project_tools, "lint", "python")
    if isinstance(ruff, GateResult):
        return ruff
    argv = [ruff, "check", "--output-format", "json", *ruff_config(root), "."]
    result = run(argv, cwd=root)
    findings: list[Finding] = []
    try:
        payload = json.loads(result.stdout or "[]")
        for item in payload:
            findings.append(
                Finding(
                    gate="lint",
                    language="python",
                    path=item.get("filename"),
                    line=(item.get("location") or {}).get("row"),
                    column=(item.get("location") or {}).get("column"),
                    rule=item.get("code"),
                    message=item.get("message", "ruff finding"),
                    severity="error",
                )
            )
    except json.JSONDecodeError:
        findings = findings_from_text("lint", result, language="python")
    return fail_or_pass("lint", findings)


def _node(root: Path, config: QualityConfig, files: list[Path]) -> GateResult:
    ensure_node_tooling()
    eslint = tool_or_skip(
        "eslint", root, config.prefer_project_tools, "lint", "javascript"
    )
    if isinstance(eslint, GateResult):
        return eslint
    config_path = eslint_config(root)
    env = prepend_path(tooling_js_dir() / "node_modules" / ".bin")
    node_modules = tooling_js_dir() / "node_modules"
    if node_modules.is_dir():
        env["NODE_PATH"] = str(node_modules) + (
            (":" + env["NODE_PATH"]) if env.get("NODE_PATH") else ""
        )
    argv = [
        eslint,
        "--config",
        str(config_path),
        "--format",
        "json",
        "--no-error-on-unmatched-pattern",
    ]
    argv.extend(relative(root, path) for path in files)
    result = run(argv, cwd=root, env=env)
    findings: list[Finding] = []
    try:
        payload = json.loads(result.stdout or "[]")
        for file_entry in payload:
            for msg in file_entry.get("messages", []):
                severity = "error" if msg.get("severity", 2) >= 2 else "warning"
                findings.append(
                    Finding(
                        gate="lint",
                        language="javascript",
                        path=file_entry.get("filePath"),
                        line=msg.get("line"),
                        column=msg.get("column"),
                        rule=msg.get("ruleId"),
                        message=msg.get("message", "eslint finding"),
                        severity=severity,
                    )
                )
    except json.JSONDecodeError:
        findings = findings_from_text("lint", result, language="javascript")
    return fail_or_pass("lint", findings)


def _go(root: Path, config: QualityConfig, files: list[Path]) -> GateResult:
    with contextlib.suppress(OSError):
        ensure_golangci_lint()
    lint = which(
        "golangci-lint", project=root, prefer_project=config.prefer_project_tools
    )
    if not lint:
        vet = which("go", project=root)
        if not vet:
            return skip_result(
                "lint", "go / golangci-lint is not installed", tool="golangci-lint"
            )
        result = run([vet, "vet", "./..."], cwd=root)
        return fail_or_pass("lint", findings_from_text("lint", result, language="go"))
    cfg = bundled_file("golangci.yml")
    project_cfg = root / ".golangci.yml"
    argv = [lint, "run", "--out-format", "json", "./..."]
    if not project_cfg.is_file() and cfg.is_file():
        argv.extend(["--config", str(cfg)])
    result = run(argv, cwd=root, timeout=480)
    findings: list[Finding] = []
    try:
        payload = json.loads(result.stdout or "{}")
        for item in payload.get("Issues") or []:
            pos = item.get("Pos") or {}
            findings.append(
                Finding(
                    gate="lint",
                    language="go",
                    path=pos.get("Filename"),
                    line=pos.get("Line"),
                    column=pos.get("Column"),
                    rule=item.get("FromLinter"),
                    message=item.get("Text", "golangci-lint finding"),
                )
            )
    except json.JSONDecodeError:
        findings = findings_from_text("lint", result, language="go")
    return fail_or_pass("lint", findings)


def _rust(root: Path, config: QualityConfig, files: list[Path]) -> GateResult:
    cargo = which("cargo", project=root, prefer_project=config.prefer_project_tools)
    if cargo and (root / "Cargo.toml").is_file():
        result = run(
            [
                cargo,
                "clippy",
                "--all-targets",
                "--message-format=json",
                "--",
                "-D",
                "warnings",
            ],
            cwd=root,
            timeout=480,
        )
        findings: list[Finding] = []
        for line in result.stdout.splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("reason") != "compiler-message":
                continue
            message = payload.get("message") or {}
            level = message.get("level")
            if level not in {"error", "warning"}:
                continue
            spans = message.get("spans") or [{}]
            span = next((item for item in spans if item.get("is_primary")), spans[0])
            findings.append(
                Finding(
                    gate="lint",
                    language="rust",
                    path=span.get("file_name"),
                    line=span.get("line_start"),
                    column=span.get("column_start"),
                    rule=(message.get("code") or {}).get("code"),
                    message=message.get("message", "clippy finding"),
                    severity="error" if level == "error" else "warning",
                )
            )
        return fail_or_pass("lint", findings)
    return skip_result(
        "lint",
        "clippy needs a Cargo.toml in the project root; rustc-only files are format-checked only",
        tool="cargo-clippy",
    )


def _java(root: Path, config: QualityConfig, files: list[Path]) -> GateResult:
    java = tool_or_skip("java", root, True, "lint", "java")
    if isinstance(java, GateResult):
        return java
    try:
        jar = ensure_checkstyle()
    except OSError as exc:
        return skip_result(
            "lint", f"could not download checkstyle: {exc}", tool="checkstyle"
        )
    cfg = bundled_file("checkstyle.xml")
    argv = [java, "-jar", str(jar), "-c", str(cfg), *[str(path) for path in files]]
    result = run(argv, cwd=root)
    findings: list[Finding] = []
    pattern = re.compile(
        r"^\[(?P<sev>\w+)\]\s+(?P<path>.+?):(?P<line>\d+)(?::(?P<col>\d+))?:\s+(?P<msg>.+)"
    )
    for line in result.combined.splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        severity = (
            "error" if match.group("sev").lower() in {"error", "fatal"} else "warning"
        )
        findings.append(
            Finding(
                gate="lint",
                language="java",
                path=match.group("path"),
                line=int(match.group("line")),
                column=int(match.group("col") or 0) or None,
                message=match.group("msg"),
                rule="checkstyle",
                severity=severity,
            )
        )
    if result.returncode != 0 and not findings:
        findings = findings_from_text("lint", result, language="java")
    return fail_or_pass("lint", findings)


def _csharp(root: Path, config: QualityConfig, files: list[Path]) -> GateResult:
    dotnet = which("dotnet", project=root)
    projects = list(root.glob("*.sln")) + list(root.glob("**/*.csproj"))
    projects = [path for path in projects if "tests/fixtures" not in path.as_posix()]
    if not dotnet:
        return skip_result(
            "lint",
            "dotnet SDK is not installed; C# format still runs via csharpier when available",
            tool="dotnet",
        )
    if not projects:
        return skip_result(
            "lint",
            "no .sln/.csproj found — csharpier covers formatting; add a project file for analyzer lint",
        )
    target = str(projects[0])
    result = run(
        [
            dotnet,
            "format",
            "analyzers",
            target,
            "--verify-no-changes",
            "--severity",
            "warn",
        ],
        cwd=root,
        timeout=480,
    )
    return fail_or_pass(
        "lint",
        findings_from_text(
            "lint",
            result,
            language="csharp",
            default_message="dotnet format analyzers reported style or analyzer issues",
        ),
    )


def _sql(root: Path, config: QualityConfig, files: list[Path]) -> GateResult:
    sqlfluff = tool_or_skip(
        "sqlfluff", root, config.prefer_project_tools, "lint", "sql"
    )
    if isinstance(sqlfluff, GateResult):
        return sqlfluff
    cfg = sqlfluff_config(root)
    argv = [
        sqlfluff,
        "lint",
        "--format",
        "json",
        "--disable-progress-bar",
        "--config",
        str(cfg),
        "--dialect",
        config.sql_dialect,
        *[str(path) for path in files],
    ]
    result = run(argv, cwd=root)
    findings: list[Finding] = []
    try:
        payload = json.loads(result.stdout or "[]")
        for file_entry in payload:
            for violation in file_entry.get("violations", []):
                findings.append(
                    Finding(
                        gate="lint",
                        language="sql",
                        path=file_entry.get("filepath"),
                        line=violation.get("start_line_no") or violation.get("line_no"),
                        column=violation.get("start_line_pos")
                        or violation.get("line_pos"),
                        rule=violation.get("code"),
                        message=violation.get("description", "sqlfluff finding"),
                    )
                )
    except json.JSONDecodeError:
        findings = findings_from_text("lint", result, language="sql")
    return fail_or_pass("lint", findings)
