from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from quality_gates.adapters import run_builtin_profile
from quality_gates.config import QualityConfig
from quality_gates.detect import iter_project_files
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
from quality_gates.installers import GOOGLE_JAVA_FORMAT
from quality_gates.models import Finding, GateResult
from quality_gates.paths import bundled_file, cache_dir
from quality_gates.registry import FILE_PROFILES, profiles_for_path
from quality_gates.tools import run, which


def run_format(
    root: Path,
    config: QualityConfig,
    languages: list[str],
    *,
    check: bool = True,
    scope: list[Path] | None = None,
) -> GateResult:
    unique = normalize_gate_languages(languages)
    parts = [
        _format_language(root, config, language, check=check, scope=scope)
        for language in unique
    ]
    project_files = _scoped(iter_project_files(root, config), scope)
    jobs: list[tuple[str, tuple[Path, ...]]] = []
    for profile in FILE_PROFILES:
        files = tuple(
            path for path in project_files if profile in profiles_for_path(path, root)
        )
        if files and "format" in profile.capabilities:
            jobs.append((profile.id, files))
    if jobs:
        with ThreadPoolExecutor(max_workers=min(config.jobs, len(jobs))) as executor:
            parts.extend(
                executor.map(
                    lambda job: run_builtin_profile(
                        root, config, job[0], "format", job[1], check=check
                    ),
                    jobs,
                )
            )
    if not parts:
        return skip_result("format", "no supported languages detected")
    return merge_results("format", parts)


def _format_language(
    root: Path,
    config: QualityConfig,
    language: str,
    *,
    check: bool,
    scope: list[Path] | None = None,
) -> GateResult:
    files = _scoped(source_files(root, config, language), scope)
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
        return run_builtin_profile(
            root, config, language, "format", tuple(files), check=check
        )
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
    argv.extend(relative(root, item) for item in files) if files else argv.append(".")
    result = run(argv, cwd=root)
    by_path: dict[str, Finding] = {}
    for raw in (*result.stdout.splitlines(), *result.stderr.splitlines()):
        parsed = parse_ruff_format_line(raw)
        if parsed is None:
            continue
        path, line_no, column = parsed
        current = by_path.get(path)
        if current is None:
            by_path[path] = Finding(
                gate="format",
                language="python",
                path=path,
                line=line_no,
                column=column,
                message=(
                    "file is not formatted with ruff "
                    "(line length 88, double quotes, LF)"
                ),
                rule="ruff-format",
            )
        elif current.line is None and line_no is not None:
            current.line = line_no
            current.column = column
    findings = list(by_path.values())
    if result.returncode != 0 and not findings:
        findings = findings_from_text("format", result, language="python")
    return fail_or_pass("format", findings)


_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_RUFF_LOCATION = re.compile(r"-->\s+(.+):(\d+):(\d+)\s*$")


def parse_ruff_format_line(
    line: str,
) -> tuple[str, int | None, int | None] | None:
    """Parse one ruff format --check line into (path, line, column).

    Ruff 0.16 prints a colored diagnostic::

        unformatted: File would be reformatted
         --> src/app.py:3:2

    Older ruff printed ``Would reformat: src/app.py``. Summary lines such as
    ``6 files would be reformatted`` are not paths.
    """
    body = _ANSI.sub("", line or "").strip()
    if not body:
        return None
    lowered = body.lower()
    if lowered.startswith("would reformat:"):
        path = body.split(":", 1)[1].strip().strip("\"'")
        return (path, None, None) if path else None
    match = _RUFF_LOCATION.search(body)
    if match:
        return match.group(1), int(match.group(2)), int(match.group(3))
    return None


def _ruff_unformatted_path(line: str) -> str | None:
    parsed = parse_ruff_format_line(line)
    return None if parsed is None else parsed[0]


def _scoped(files: list[Path], scope: list[Path] | None) -> list[Path]:
    if scope is None:
        return files
    wanted = {item.resolve() for item in scope if item.is_file()}
    return [item for item in files if item.resolve() in wanted]


def _node(
    root: Path, config: QualityConfig, files: list[Path], *, check: bool
) -> GateResult:
    if not files:
        return skip_result("format", "no javascript/typescript/react files")
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
    jar = cache_dir() / "jars" / f"google-java-format-{GOOGLE_JAVA_FORMAT}-all-deps.jar"
    if not jar.is_file():
        return skip_result(
            "format",
            "google-java-format is not installed — run `quality doctor --install`",
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
