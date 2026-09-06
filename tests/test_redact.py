from __future__ import annotations

from quality_gates.redact import redact_secrets


def test_redact_secrets() -> None:
    text = "token=ghp_secret12345 password=super_secret api_key=abcde"
    redacted = redact_secrets(text)
    assert "ghp_secret12345" not in redacted
    assert "super_secret" not in redacted
    assert "token=<redacted>" in redacted
    assert "password=<redacted>" in redacted
    assert "api_key=<redacted>" in redacted
