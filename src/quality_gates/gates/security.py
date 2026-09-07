from __future__ import annotations

import json
import re
from pathlib import Path

from quality_gates import installers
from quality_gates.config import QualityConfig
from quality_gates.gates.common import fail_or_pass
from quality_gates.models import Finding, GateResult
from quality_gates.paths import bundled_file
from quality_gates.tools import run, which

# Compatibility names remain patchable, but gate execution never invokes installers.
ensure_gitleaks = installers.ensure_gitleaks
ensure_osv_scanner = installers.ensure_osv_scanner

SECRET_LINE = re.compile(
    r"""(?i)(api[_-]?key|apikey|secret|password|passwd|token)\s*[=:]\s*['\"][^'\"]{10,}['\"]"""
)


def run_security(root: Path, config: QualityConfig, languages: list[str]) -> GateResult:
    findings: list[Finding] = []
    notes: list[str] = []
    skipped: list[str] = []

    findings.extend(_gitleaks(root, skipped))
    findings.extend(_osv(root, skipped, notes))
    findings.extend(_semgrep(root, languages, skipped, notes))
    findings.extend(_trivy(root, skipped, notes))
    findings.extend(_license(root, config, notes))
    findings.extend(_workflow_pins(root, config))
    findings.extend(_zizmor(root, skipped, notes))
    findings.extend(_heuristic_secrets(root, config))

    if languages:
        notes.append("languages in scope: " + ", ".join(languages))
    scanners = {"gitleaks", "osv-scanner", "semgrep"}
    if not findings and scanners.issubset(set(skipped)):
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


def _trivy(root: Path, skipped: list[str], notes: list[str]) -> list[Finding]:
    binary = which("trivy")
    if not binary:
        skipped.append("trivy")
        return []
    result = run(
        [
            binary,
            "fs",
            "--scanners",
            "vuln",
            "--format",
            "json",
            "--quiet",
            str(root),
        ],
        cwd=root,
        timeout=300,
    )
    if result.skipped:
        skipped.append("trivy")
        return []
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        notes.append("trivy did not return JSON")
        return []
    findings: list[Finding] = []
    for res in payload.get("Results") or []:
        target = res.get("Target") or "filesystem"
        for vuln in res.get("Vulnerabilities") or []:
            sev = str(vuln.get("Severity") or "HIGH").lower()
            findings.append(
                Finding(
                    gate="security",
                    rule=vuln.get("VulnerabilityID") or "trivy",
                    path=target,
                    message=(
                        f"{vuln.get('PkgName') or 'package'}: "
                        f"{vuln.get('Title') or vuln.get('VulnerabilityID') or 'CVE'}"
                    ),
                    severity="error" if sev in {"high", "critical"} else "warning",
                    tool="trivy",
                )
            )
    if not findings:
        notes.append("trivy: no known filesystem vulnerabilities")
    return findings


def _license(root: Path, config: QualityConfig, notes: list[str]) -> list[Finding]:
    section = config.raw.get("quality", {}).get("license", {})
    if not isinstance(section, dict):
        section = {}
    allow = section.get("allow") or []
    if not isinstance(allow, list) or not allow:
        notes.append("license allow-list unset; SPDX scan skipped")
        return []
    allowed = {str(item).lower() for item in allow}
    findings: list[Finding] = []
    needle = re.compile(r"SPDX-License-Identifier:\s*([A-Za-z0-9.+-]+)")
    for name in ("LICENSE", "LICENSE.md", "COPYING", "NOTICE"):
        path = root / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        found = {match.group(1).lower() for match in needle.finditer(text)}
        if not found:
            lowered = text.lower()
            if "mit" in lowered:
                found.add("mit")
            if "apache" in lowered:
                found.add("apache-2.0")
            if "gpl" in lowered:
                found.add("gpl-3.0")
        for ident in sorted(found):
            if ident not in allowed:
                findings.append(
                    Finding(
                        gate="security",
                        rule="license-not-allowed",
                        path=name,
                        message=f"license {ident} is outside quality.license.allow",
                        severity="error",
                    )
                )
    package = root / "package.json"
    if package.is_file():
        try:
            license_id = str(
                json.loads(package.read_text(encoding="utf-8")).get("license") or ""
            ).lower()
        except (OSError, json.JSONDecodeError):
            license_id = ""
        if license_id and license_id not in allowed:
            findings.append(
                Finding(
                    gate="security",
                    rule="license-not-allowed",
                    path="package.json",
                    message=f"package.json license {license_id} is outside quality.license.allow",
                    severity="error",
                )
            )
    return findings


def _gitleaks(root: Path, skipped: list[str]) -> list[Finding]:
    binary = which("gitleaks")
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
    binary = which("osv-scanner")
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


def _semgrep(
    root: Path, languages: list[str], skipped: list[str], notes: list[str]
) -> list[Finding]:
    generally_available = {
        "c",
        "cpp",
        "csharp",
        "go",
        "java",
        "javascript",
        "typescript",
        "react",
        "kotlin",
        "php",
        "python",
        "ruby",
        "rust",
        "scala",
        "swift",
    }
    experimental = {"dart", "lua", "r", "shell"}
    ga = sorted(set(languages) & generally_available)
    preview = sorted(set(languages) & experimental)
    unsupported = sorted(set(languages) - generally_available - experimental)
    if ga:
        notes.append("semgrep GA language capability: " + ", ".join(ga))
    if preview:
        notes.append(
            "semgrep experimental language parsing (coverage depends on rules): "
            + ", ".join(preview)
        )
    if unsupported:
        notes.append("semgrep coverage not claimed for: " + ", ".join(unsupported))
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


_FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_USES = re.compile(r"^\s*uses\s*:\s*['\"]?([^'\"\s#]+)", re.IGNORECASE)


def _workflow_pins(root: Path, config: QualityConfig) -> list[Finding]:
    """Statically require immutable SHAs in workflows and composite actions."""
    from quality_gates.detect import iter_project_files

    findings: list[Finding] = []
    for path in iter_project_files(root, config):
        relative = path.relative_to(root).as_posix()
        if not (
            relative.startswith(".github/workflows/")
            or path.name.lower() in {"action.yml", "action.yaml"}
        ):
            continue
        try:
            lines = path.read_text(encoding="utf-8-sig", errors="strict").splitlines()
        except (OSError, UnicodeError):
            continue
        for line_no, line in enumerate(lines, 1):
            match = _USES.match(line)
            if not match:
                continue
            target = match.group(1)
            if target.startswith(("./", "docker://")):
                continue
            if "@" not in target or not _FULL_SHA.fullmatch(target.rsplit("@", 1)[1]):
                findings.append(
                    Finding(
                        gate="security",
                        rule="github-action-unpinned",
                        path=relative,
                        line=line_no,
                        message="third-party action must be pinned to a full 40-character commit SHA",
                        severity="error",
                        safety="non-executing",
                    )
                )
    return findings


def _zizmor(root: Path, skipped: list[str], notes: list[str]) -> list[Finding]:
    binary = which("zizmor", project=root, prefer_project=True)
    if not binary:
        skipped.append("zizmor")
        return []
    result = run(
        [binary, "--offline", "--format", "json", str(root)],
        cwd=root,
        timeout=180,
    )
    try:
        payload = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        if result.returncode:
            notes.append("zizmor did not return JSON")
        return []
    items = payload if isinstance(payload, list) else payload.get("findings", [])
    return [
        Finding(
            gate="security",
            rule=item.get("ident") or item.get("rule") or "zizmor",
            path=item.get("path"),
            line=(item.get("location") or {}).get("line"),
            message=item.get("desc")
            or item.get("message")
            or "GitHub Actions security finding",
            severity="error",
            tool="zizmor",
        )
        for item in items
        if isinstance(item, dict)
    ]


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
            ".c",
            ".h",
            ".cc",
            ".cpp",
            ".cxx",
            ".hpp",
            ".php",
            ".phtml",
            ".rb",
            ".swift",
            ".kt",
            ".kts",
            ".dart",
            ".scala",
            ".lua",
            ".r",
            ".rmd",
            ".ex",
            ".exs",
            ".sh",
            ".bash",
            ".zsh",
            ".fish",
            ".ps1",
            ".psm1",
            ".xml",
            ".tf",
            ".hcl",
        }:
            continue
        if path.name in {
            "package-lock.json",
            "npm-shrinkwrap.json",
            "yarn.lock",
            "pnpm-lock.yaml",
            "go.sum",
            "Cargo.lock",
            "Gemfile.lock",
            "composer.lock",
            "Podfile.lock",
            "Package.resolved",
            "packages.lock.json",
            "gradle.lockfile",
            "pubspec.lock",
            "renv.lock",
        }:
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
