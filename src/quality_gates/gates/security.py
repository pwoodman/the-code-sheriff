from __future__ import annotations

import json
import re
from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.gates.common import fail_or_pass
from quality_gates.installers import ensure_gitleaks, ensure_osv_scanner
from quality_gates.models import Finding, GateResult
from quality_gates.paths import bundled_file
from quality_gates.tools import run, which

SECRET_LINE = re.compile(
    r"""(?i)(api[_-]?key|apikey|secret|password|passwd|token)\s*[=:]\s*['\"][^'\"]{10,}['\"]"""
)


def run_security(root: Path, config: QualityConfig, languages: list[str]) -> GateResult:
    findings: list[Finding] = []
    notes: list[str] = []
    skipped: list[str] = []

    findings.extend(_gitleaks(root, skipped))
    findings.extend(_osv(root, skipped, notes))
    findings.extend(_semgrep(root, skipped, notes))
    findings.extend(_heuristic_secrets(root, config))

    if languages:
        notes.append("languages in scope: " + ", ".join(languages))
    if not findings and skipped and not notes:
        notes.append(
            "security scanners skipped; install gitleaks, osv-scanner, and/or semgrep"
        )
        return GateResult(
            name="security",
            status="skip",
            findings=[],
            notes=notes,
            skipped_tools=skipped,
        )
    result = fail_or_pass("security", findings, notes)
    result.skipped_tools = skipped
    return result


def _gitleaks(root: Path, skipped: list[str]) -> list[Finding]:
    try:
        binary = ensure_gitleaks()
    except OSError:
        binary = which("gitleaks")
        if not binary:
            skipped.append("gitleaks")
            return []
    else:
        binary = str(binary) if binary else which("gitleaks")
        if not binary:
            skipped.append("gitleaks")
            return []
    cfg = bundled_file("gitleaks.toml")
    report = root / ".quality-reports" / "gitleaks.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    argv = [
        binary,
        "detect",
        "--no-banner",
        "--redact",
        "--report-format",
        "json",
        "--report-path",
        str(report),
        "--source",
        str(root),
    ]
    if cfg.is_file():
        argv.extend(["--config", str(cfg)])
    run(argv, cwd=root, timeout=180)
    if not report.is_file():
        return []
    try:
        payload = json.loads(report.read_text(encoding="utf-8") or "[]")
    except json.JSONDecodeError:
        return []
    findings: list[Finding] = []
    for item in payload:
        findings.append(
            Finding(
                gate="security",
                rule=item.get("RuleID") or "gitleaks",
                path=item.get("File"),
                line=item.get("StartLine"),
                message=item.get("Description") or "secret detected",
                severity="error",
            )
        )
    return findings


def _osv(root: Path, skipped: list[str], notes: list[str]) -> list[Finding]:
    try:
        binary = ensure_osv_scanner()
    except OSError:
        binary = which("osv-scanner")
        if not binary:
            skipped.append("osv-scanner")
            return []
    else:
        binary = str(binary) if binary else which("osv-scanner")
        if not binary:
            skipped.append("osv-scanner")
            return []
    result = run(
        [binary, "scan", "--format", "json", "-r", str(root)],
        cwd=root,
        timeout=300,
    )
    if result.skipped:
        skipped.append("osv-scanner")
        return []
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        if result.returncode not in {0, 1}:
            notes.append("osv-scanner did not return JSON; lockfiles may be missing")
        return []
    findings: list[Finding] = []
    for res in payload.get("results") or []:
        source = ((res.get("source") or {}).get("path")) or "dependencies"
        for pkg in res.get("packages") or []:
            name = ((pkg.get("package") or {}).get("name")) or "package"
            for vuln in pkg.get("vulnerabilities") or []:
                findings.append(
                    Finding(
                        gate="security",
                        rule=vuln.get("id") or "osv",
                        path=source,
                        message=(
                            f"{name}: {vuln.get('summary') or vuln.get('id') or 'vulnerable dependency'}"
                        ),
                        severity="error",
                    )
                )
    if not findings:
        notes.append("osv-scanner: no known vulnerable dependencies")
    return findings


def _semgrep(root: Path, skipped: list[str], notes: list[str]) -> list[Finding]:
    binary = which("semgrep")
    if not binary:
        skipped.append("semgrep")
        notes.append(
            "semgrep not installed — bundled rules skipped (pip install semgrep)"
        )
        return []
    cfg = bundled_file("semgrep.yml")
    result = run(
        [
            binary,
            "scan",
            "--config",
            str(cfg),
            "--json",
            "--quiet",
            "--disable-version-check",
            str(root),
        ],
        cwd=root,
        timeout=420,
    )
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return []
    findings: list[Finding] = []
    for item in payload.get("results") or []:
        extra = item.get("extra") or {}
        severity = str(extra.get("severity", "ERROR")).lower()
        if severity not in {"error", "warning", "info"}:
            severity = "error"
        findings.append(
            Finding(
                gate="security",
                rule=item.get("check_id"),
                path=item.get("path"),
                line=(item.get("start") or {}).get("line"),
                message=extra.get("message") or "semgrep finding",
                severity=severity if severity != "error" else "error",
            )
        )
    return findings


def _heuristic_secrets(root: Path, config: QualityConfig) -> list[Finding]:
    findings: list[Finding] = []
    from quality_gates.detect import iter_project_files

    for path in iter_project_files(root, config):
        if path.suffix.lower() not in {
            ".py",
            ".js",
            ".ts",
            ".tsx",
            ".jsx",
            ".go",
            ".java",
            ".cs",
            ".rs",
            ".sql",
            ".env",
            ".yml",
            ".yaml",
            ".json",
            ".toml",
        }:
            continue
        if path.name in {"package-lock.json", "go.sum", "Cargo.lock"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for index, line in enumerate(text.splitlines(), start=1):
            if SECRET_LINE.search(line) and "example" not in line.lower():
                findings.append(
                    Finding(
                        gate="security",
                        rule="hardcoded-secret",
                        path=str(path.relative_to(root)),
                        line=index,
                        message="possible hardcoded credential",
                        severity="warning",
                    )
                )
    return findings
