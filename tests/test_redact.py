from __future__ import annotations

from quality_gates.redact import redact_secrets


def test_redact_secrets() -> None:
    text = "token=example_token password=example_password api_key=example_key"
    redacted = redact_secrets(text)
    assert "example_token" not in redacted
    assert "example_password" not in redacted
    assert "token=<redacted>" in redacted
    assert "password=<redacted>" in redacted
    assert "api_key=<redacted>" in redacted
