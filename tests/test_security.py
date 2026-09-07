from __future__ import annotations

from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.gates.compile import security_cleared
from quality_gates.gates.security import (
    findings_from_checkov,
    findings_from_trivy,
    run_security,
)


def _skip_all_scanners(monkeypatch) -> None:
    def missing() -> None:
        raise OSError("not installed")

    monkeypatch.setattr("quality_gates.gates.security.ensure_gitleaks", missing)
    monkeypatch.setattr("quality_gates.gates.security.ensure_osv_scanner", missing)
    monkeypatch.setattr("quality_gates.gates.security.which", lambda *_a, **_k: None)


def test_security_skips_when_scanners_missing(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _skip_all_scanners(monkeypatch)
    result = run_security(tmp_path, QualityConfig(), ["python"])
    assert result.status == "skip"
    assert "gitleaks" in result.skipped_tools
    assert "osv-scanner" in result.skipped_tools
    assert "semgrep" in result.skipped_tools
    ok, reason = security_cleared(result)
    assert ok is False
    assert "scanner" in reason.lower() or "security" in reason.lower()


def test_security_still_reports_heuristic_secrets(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "app.py").write_text(
        "API_KEY = " + '"' + "sk_live_" + "this_is_not_a_real_key_value" + '"\n',
        encoding="utf-8",
    )
    _skip_all_scanners(monkeypatch)
    result = run_security(tmp_path, QualityConfig(), ["python"])
    assert result.status != "skip"
    assert any(item.rule == "hardcoded-secret" for item in result.findings)
    secret = next(item for item in result.findings if item.rule == "hardcoded-secret")
    assert secret.owasp and secret.owasp.startswith("A07")
    assert secret.cwe == "CWE-798"
    assert secret.reproduce and "Rotate" in secret.reproduce


def test_trivy_parses_vuln_misconfig_and_secret() -> None:
    findings = findings_from_trivy(
        {
            "Results": [
                {
                    "Target": "requirements.txt",
                    "Vulnerabilities": [
                        {
                            "VulnerabilityID": "CVE-2024-0001",
                            "PkgName": "demo",
                            "Title": "bad package",
                            "Severity": "CRITICAL",
                            "EPSS": {"Score": 0.91},
                            "PrimaryURL": "https://example.test/cve",
                        }
                    ],
                },
                {
                    "Target": "Dockerfile",
                    "Misconfigurations": [
                        {
                            "AVDID": "AVD-DS-0002",
                            "ID": "DS002",
                            "Title": "Image user should not be root",
                            "Description": "Running as root",
                            "Severity": "HIGH",
                            "Resolution": "Add a USER directive",
                            "CauseMetadata": {"StartLine": 4},
                        }
                    ],
                    "Secrets": [
                        {
                            "RuleID": "aws-access-key-id",
                            "Title": "AWS access key",
                            "StartLine": 8,
                            "File": ".env",
                        }
                    ],
                },
            ]
        }
    )
    rules = {item.rule: item for item in findings}
    assert rules["CVE-2024-0001"].epss == "0.91"
    assert rules["CVE-2024-0001"].severity == "error"
    assert rules["AVD-DS-0002"].line == 4
    assert rules["AVD-DS-0002"].path == "Dockerfile"
    assert rules["aws-access-key-id"].path == ".env"


def test_checkov_parses_failed_checks() -> None:
    findings = findings_from_checkov(
        {
            "results": {
                "failed_checks": [
                    {
                        "check_id": "CKV_AWS_20",
                        "check_name": "S3 bucket should have public access blocked",
                        "file_path": "infra/s3.tf",
                        "file_line_range": [12, 40],
                        "severity": "HIGH",
                        "guideline": "https://example.test/ckv",
                    }
                ]
            }
        }
    )
    assert len(findings) == 1
    assert findings[0].rule == "CKV_AWS_20"
    assert findings[0].line == 12
    assert findings[0].tool == "checkov"
