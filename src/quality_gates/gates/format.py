from __future__ import annotations

from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.gates.common import (
    fail_or_pass,
    findings_from_text,
    merge_results,
    normalize_gate_languages,
    prettier_config,
    relative,
    ruff_config,
    skip_result,
    source_files,
    sqlfluff_config,
    tool_or_skip,
)
from quality_gates.installers import ensure_google_java_format, ensure_node_tooling
from quality_gates.models import Finding, GateResult
from quality_gates.paths import bundled_file
from quality_gates.tools import run, which


def run_format(
    root: Path,
    config: QualityConfig,
    languages: list[str],
    *,
    check: bool = True,
) -> GateResult:
    unique = normalize_gate_languages(languages)
    parts = [
        _format_language(root, config, language, check=check) for language in unique
    ]
    if not parts:
        return skip_result("format", "no supported languages detected")
    return merge_results("format", parts)


def _format_language(
    root: Path, config: QualityConfig, language: str, *, check: bool
) -> GateResult:
    files = source_files(root, config, language)
    if not files and language != "javascript":
        return skip_result("format", f"no {language} files")
    handler = {
        "python": _python,
        "javascript": _node,
        "go": _go,
        "rust": _rust,
        "java": _java,
        "csharp": _csharp,
        "sql": _sql,
    }.get(language)
    if handler is None:
        return skip_result("format", f"no formatter mapped for {language}")
    return handler(root, config, files, check=check)


def _python(
    root: Path, config: QualityConfig, files: list[Path], *, check: bool
) -> GateResult:
    ruff = tool_or_skip("ruff", root, config.prefer_project_tools, "format", "python")
    if isinstance(ruff, GateResult):
        return ruff
    argv = [ruff, "format", *ruff_config(root)]
    if check:
        argv.append("--check")
    argv.append(".")
    result = run(argv, cwd=root)
    findings = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.endswith("would be reformatted") or line.endswith("reformatted"):
            findings.append(
                Finding(
                    gate="format",
                    language="python",
                    path=line.split(" ")[0],
                    message="file is not formatted with ruff (line length 88, double quotes, LF)",
                    rule="ruff-format",
                )
            )
    if result.returncode != 0 and not findings:
        findings = findings_from_text("format", result, language="python")
    return fail_or_pass("format", findings)


def _node(
    root: Path, config: QualityConfig, files: list[Path], *, check: bool
) -> GateResult:
    if not files:
        return skip_result("format", "no javascript/typescript/react files")
    ensure_node_tooling()
    prettier = tool_or_skip(
        "prettier", root, config.prefer_project_tools, "format", "javascript"
    )
    if isinstance(prettier, GateResult):
        return prettier
    ignore = bundled_file("prettierignore")
    argv = [
        prettier,
        "--config",
        str(prettier_config(root)),
        "--ignore-path",
        str(ignore),
        "--ignore-unknown",
    ]
    if check:
        argv.append("--check")
    else:
        argv.append("--write")
    argv.extend(relative(root, path) for path in files)
    result = run(argv, cwd=root)
    findings = []
    for line in result.stdout.splitlines() + result.stderr.splitlines():
        stripped = line.strip()
        if stripped.endswith("[warn/error]") or "Code style issues" in stripped:
            continue
        if (
            stripped
            and not stripped.startswith("Checking")
            and result.returncode != 0
            and (
                stripped.endswith(".js")
                or stripped.endswith((".ts", ".tsx", ".jsx", ".json", ".css"))
            )
        ):
            findings.append(
                Finding(
                    gate="format",
                    language="javascript",
                    path=stripped.split(" ")[0],
                    message="file is not formatted with Prettier (2-space indent, double quotes, trailing commas)",
                    rule="prettier",
                )
            )
    if result.returncode != 0 and not findings:
        findings = findings_from_text("format", result, language="javascript")
    return fail_or_pass("format", findings)


def _go(
    root: Path, config: QualityConfig, files: list[Path], *, check: bool
) -> GateResult:
    gofmt = tool_or_skip("gofmt", root, config.prefer_project_tools, "format", "go")
    if isinstance(gofmt, GateResult):
        return gofmt
    rels = [relative(root, path) for path in files]
    if check:
        result = run([gofmt, "-l", *rels], cwd=root)
        findings = [
            Finding(
                gate="format",
                language="go",
                path=line.strip(),
                message="file is not formatted with gofmt (tabs, official Go style)",
                rule="gofmt",
            )
            for line in result.stdout.splitlines()
            if line.strip()
        ]
        return fail_or_pass("format", findings)
    result = run([gofmt, "-w", *rels], cwd=root)
    return fail_or_pass("format", findings_from_text("format", result, language="go"))


def _rust(
    root: Path, config: QualityConfig, files: list[Path], *, check: bool
) -> GateResult:
    cargo = which("cargo", project=root, prefer_project=config.prefer_project_tools)
    rustfmt = which("rustfmt", project=root, prefer_project=config.prefer_project_tools)
    rustfmt_toml = bundled_file("rustfmt.toml")
    if cargo and (root / "Cargo.toml").is_file():
        argv = [cargo, "fmt", "--all", "--"]
        if rustfmt_toml.is_file():
            argv.extend(["--config-path", str(rustfmt_toml)])
        if check:
            argv.append("--check")
        result = run(argv, cwd=root)
        return fail_or_pass(
            "format",
            findings_from_text(
                "format",
                result,
                language="rust",
                default_message="Rust sources are not formatted with rustfmt",
            ),
        )
    if not rustfmt:
        return skip_result("format", "rustfmt/cargo is not installed", tool="rustfmt")
    argv = [rustfmt, "--edition", "2021", "--config-path", str(rustfmt_toml)]
    if check:
        argv.append("--check")
    argv.extend(str(path) for path in files)
    result = run(argv, cwd=root)
    return fail_or_pass(
        "format",
        findings_from_text("format", result, language="rust"),
    )


def _java(
    root: Path, config: QualityConfig, files: list[Path], *, check: bool
) -> GateResult:
    java = tool_or_skip("java", root, True, "format", "java")
    if isinstance(java, GateResult):
        return java
    try:
        jar = ensure_google_java_format()
    except OSError as exc:
        return skip_result(
            "format",
            f"could not download google-java-format: {exc}",
            tool="google-java-format",
        )
    argv = [java, "-jar", str(jar)]
    if check:
        argv.extend(["--dry-run", "--set-exit-if-changed"])
    else:
        argv.append("--replace")
    argv.extend(str(path) for path in files)
    result = run(argv, cwd=root)
    findings = [
        Finding(
            gate="format",
            language="java",
            path=relative(root, Path(line.strip())) if line.strip() else None,
            message="file is not formatted with google-java-format (Google Java Style, 2-space indent)",
            rule="google-java-format",
        )
        for line in result.stdout.splitlines()
        if line.strip()
    ]
    if result.returncode != 0 and not findings:
        findings = findings_from_text("format", result, language="java")
    return fail_or_pass("format", findings)


def _csharp(
    root: Path, config: QualityConfig, files: list[Path], *, check: bool
) -> GateResult:
    csharpier = which(
        "csharpier", project=root, prefer_project=config.prefer_project_tools
    )
    if not csharpier:
        dotnet = which("dotnet", project=root)
        if dotnet:
            run([dotnet, "tool", "update", "-g", "csharpier"], cwd=root, timeout=180)
            csharpier = which("csharpier", project=root)
    if not csharpier:
        return skip_result(
            "format",
            "csharpier is not installed (dotnet tool install -g csharpier)",
            tool="csharpier",
        )
    config_path = bundled_file("csharpier.json")
    argv = [
        csharpier,
        "check" if check else "format",
        "--config-path",
        str(config_path),
    ]
    argv.extend(str(path) for path in files)
    result = run(argv, cwd=root)
    return fail_or_pass(
        "format",
        findings_from_text(
            "format",
            result,
            language="csharp",
            default_message="C# sources are not formatted with csharpier (4-space indent, 120 columns)",
        ),
    )


def _sql(
    root: Path, config: QualityConfig, files: list[Path], *, check: bool
) -> GateResult:
    sqlfluff = tool_or_skip(
        "sqlfluff", root, config.prefer_project_tools, "format", "sql"
    )
    if isinstance(sqlfluff, GateResult):
        return sqlfluff
    cfg = sqlfluff_config(root)
    findings: list[Finding] = []
    for path in files:
        if check:
            argv = [
                sqlfluff,
                "lint",
                "--disable-progress-bar",
                "--config",
                str(cfg),
                "--dialect",
                config.sql_dialect,
                str(path),
            ]
        else:
            argv = [
                sqlfluff,
                "fix",
                "--force",
                "--disable-progress-bar",
                "--config",
                str(cfg),
                "--dialect",
                config.sql_dialect,
                str(path),
            ]
        result = run(argv, cwd=root)
        if result.returncode != 0:
            findings.extend(findings_from_text("format", result, language="sql"))
    return fail_or_pass("format", findings)
