from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from quality_gates.config import QualityConfig, find_project_config
from quality_gates.detect import (
    TOOLCHAIN_BY_LANGUAGE,
    iter_project_files,
)
from quality_gates.models import Finding, GateResult, RunResult
from quality_gates.paths import bundled_file
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
    return GateResult(name=name, status="skip", notes=[reason], skipped_tools=skipped)


def fail_or_pass(
    name: str, findings: list[Finding], notes: list[str] | None = None
) -> GateResult:
    errors = [item for item in findings if item.severity == "error"]
    status = "fail" if errors else "pass"
    return GateResult(name=name, status=status, findings=findings, notes=notes or [])


def merge_results(name: str, parts: Iterable[GateResult]) -> GateResult:
    findings: list[Finding] = []
    notes: list[str] = []
    skipped: list[str] = []
    saw_fail = False
    saw_pass = False
    for part in parts:
        findings.extend(part.findings)
        notes.extend(part.notes)
        skipped.extend(part.skipped_tools)
        if part.status == "fail":
            saw_fail = True
        elif part.status == "pass":
            saw_pass = True
    if saw_fail:
        status = "fail"
    elif saw_pass:
        status = "pass"
    else:
        status = "skip"
        if not notes:
            notes.append("no applicable tools ran")
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
        findings.append(
            Finding(
                gate=gate,
                message=stripped[:500],
                language=language,
            )
        )
    if not findings and result.returncode != 0:
        findings.append(
            Finding(
                gate=gate,
                message=default_message or f"command failed: {' '.join(result.argv)}",
                language=language,
            )
        )
    return findings


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
