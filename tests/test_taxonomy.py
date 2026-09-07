from __future__ import annotations

from quality_gates.github_comment import merge_pr_body
from quality_gates.models import Finding
from quality_gates.taxonomy import classify_finding


def test_classify_cve_and_iac() -> None:
    cve = classify_finding(
        Finding(
            gate="security",
            rule="CVE-2024-1234",
            tool="osv-scanner",
            message="demo is vulnerable",
            path="uv.lock",
        )
    )
    assert cve.owasp and cve.owasp.startswith("A06")
    assert cve.reproduce and "Upgrade" in cve.reproduce

    iac = classify_finding(
        Finding(
            gate="security",
            rule="CKV_AWS_20",
            tool="checkov",
            message="public bucket",
            path="s3.tf",
            line=3,
        )
    )
    assert iac.owasp and iac.owasp.startswith("A05")
    assert iac.cwe == "CWE-16"


def test_merge_pr_body_replaces_sheriff_block() -> None:
    first = merge_pr_body("Fixes the login form.", "First summary")
    assert "The Code Sheriff" in first
    assert "Fixes the login form." in first
    second = merge_pr_body(first, "Second summary")
    assert "Second summary" in second
    assert "First summary" not in second
    assert second.count("<!-- the-code-sheriff:summary -->") == 1
