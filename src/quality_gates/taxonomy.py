"""Map findings to OWASP Top 10 / CWE and fill steps of reproduction."""

from __future__ import annotations

from quality_gates.models import Finding

# rule or tool needle -> (OWASP, CWE, reproduce template)
# Templates may use {path}, {line}, {rule}, {verify}.
_RULES: tuple[tuple[tuple[str, ...], str, str, str], ...] = (
    (
        ("gitleaks", "hardcoded-secret", "generic.hardcoded-secret", "secret"),
        "A07:2021 Identification and Authentication Failures",
        "CWE-798",
        "1. Open `{path}` at line {line} and confirm the value is a live credential.\n"
        "2. Rotate the secret at its issuer and remove it from git history if committed.\n"
        "3. Load it from a secret manager or environment variable.\n"
        "4. Re-run `{verify}`.",
    ),
    (
        ("python.subprocess-shell", "java.runtime-exec", "csharp.process-shell", "shell=true"),
        "A03:2021 Injection",
        "CWE-78",
        "1. Open `{path}` at line {line}.\n"
        "2. Replace shell/string concatenation with an argument list and no shell.\n"
        "3. Re-run `{verify}`.",
    ),
    (
        ("python.eval", "js.eval", "eval"),
        "A03:2021 Injection",
        "CWE-94",
        "1. Open `{path}` at line {line}.\n"
        "2. Remove eval/exec or parse the input with a safe API.\n"
        "3. Re-run `{verify}`.",
    ),
    (
        ("python.pickle-loads", "pickle"),
        "A08:2021 Software and Data Integrity Failures",
        "CWE-502",
        "1. Open `{path}` at line {line}.\n"
        "2. Stop deserializing untrusted pickle; use JSON or a typed format.\n"
        "3. Re-run `{verify}`.",
    ),
    (
        ("python.yaml-unsafe-load", "yaml.load"),
        "A08:2021 Software and Data Integrity Failures",
        "CWE-502",
        "1. Open `{path}` at line {line}.\n"
        "2. Switch to yaml.safe_load (or a SafeLoader).\n"
        "3. Re-run `{verify}`.",
    ),
    (
        ("js.innerhtml", "js.document-write", "innerhtml", "xss"),
        "A03:2021 Injection",
        "CWE-79",
        "1. Open `{path}` at line {line}.\n"
        "2. Use textContent or a sanitizer instead of HTML injection.\n"
        "3. Re-run `{verify}`.",
    ),
    (
        ("go.sql-concat", "sql-concat", "sqli"),
        "A03:2021 Injection",
        "CWE-89",
        "1. Open `{path}` at line {line}.\n"
        "2. Replace string-built SQL with parameterized queries.\n"
        "3. Re-run `{verify}`.",
    ),
    (
        ("github-action-unpinned", "zizmor"),
        "A08:2021 Software and Data Integrity Failures",
        "CWE-829",
        "1. Open `{path}` at line {line}.\n"
        "2. Pin third-party actions to a full 40-character commit SHA.\n"
        "3. Re-run `{verify}`.",
    ),
    (
        ("license-not-allowed",),
        "A06:2021 Vulnerable and Outdated Components",
        "CWE-1104",
        "1. Open `{path}`.\n"
        "2. Switch to a license in `quality.license.allow` or expand the allow-list.\n"
        "3. Re-run `{verify}`.",
    ),
)

_TOOL_FALLBACKS: dict[str, tuple[str, str, str]] = {
    "osv-scanner": (
        "A06:2021 Vulnerable and Outdated Components",
        "CWE-1104",
        "1. Open lockfile `{path}`.\n"
        "2. Upgrade the named package to a non-vulnerable version (or drop it).\n"
        "3. Re-run `{verify}`.",
    ),
    "trivy": (
        "A06:2021 Vulnerable and Outdated Components",
        "CWE-1035",
        "1. Open `{path}` at line {line}.\n"
        "2. Apply the scanner's remediation (upgrade, pin, or harden config).\n"
        "3. Re-run `{verify}`.",
    ),
    "checkov": (
        "A05:2021 Security Misconfiguration",
        "CWE-16",
        "1. Open `{path}` at line {line}.\n"
        "2. Apply the Checkov/IaC hardening suggested in the finding.\n"
        "3. Re-run `{verify}`.",
    ),
    "semgrep": (
        "A03:2021 Injection",
        "CWE-693",
        "1. Open `{path}` at line {line}.\n"
        "2. Follow the Semgrep message and suggested fix.\n"
        "3. Re-run `{verify}`.",
    ),
    "gitleaks": (
        "A07:2021 Identification and Authentication Failures",
        "CWE-798",
        "1. Open `{path}` at line {line} and confirm the value is a live credential.\n"
        "2. Rotate it and remove it from source control.\n"
        "3. Re-run `{verify}`.",
    ),
}

_IAC_NEEDLES = (
    "misconfig",
    "dockerfile",
    "terraform",
    "kubernetes",
    "helm",
    "cloudformation",
    "ckv_",
    "avd-",
    "ds00",
)


def classify_finding(finding: Finding) -> Finding:
    """Fill OWASP, CWE, and steps of reproduction when they are missing."""
    owasp, cwe, template = _lookup(finding)
    if owasp and not finding.owasp:
        finding.owasp = owasp
    if cwe and not finding.cwe:
        finding.cwe = cwe
    if template and not finding.reproduce:
        finding.reproduce = _render(template, finding)
    return finding


def classify_findings(findings: list[Finding]) -> list[Finding]:
    return [classify_finding(item) for item in findings]


def _lookup(finding: Finding) -> tuple[str | None, str | None, str | None]:
    haystack = " ".join(
        part
        for part in (
            finding.rule,
            finding.tool,
            finding.message,
        )
        if part
    ).lower()
    rule = (finding.rule or "").upper()
    if rule.startswith(("CKV_", "AVD-", "DS00", "KSV", "TFSEC")) or (
        finding.tool or ""
    ).lower() in {"checkov", "trivy-config"}:
        return _TOOL_FALLBACKS["checkov"]
    if any(needle in haystack for needle in _IAC_NEEDLES) and (
        finding.tool or ""
    ).lower().startswith("trivy"):
        return _TOOL_FALLBACKS["checkov"]
    for needles, owasp, cwe, template in _RULES:
        if any(needle in haystack for needle in needles):
            return owasp, cwe, template
    if (finding.rule or "").upper().startswith(("CVE-", "GHSA-")):
        return _TOOL_FALLBACKS["osv-scanner"]
    if finding.tool and finding.tool.lower() in _TOOL_FALLBACKS:
        return _TOOL_FALLBACKS[finding.tool.lower()]
    return None, None, None


def _render(template: str, finding: Finding) -> str:
    verify = finding.verify or f"quality {finding.gate or 'security'}"
    return template.format(
        path=finding.path or "the reported file",
        line=finding.line or 1,
        rule=finding.rule or finding.gate or "finding",
        verify=verify,
    )
