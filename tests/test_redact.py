from __future__ import annotations

from quality_gates.redact import redact_secrets


def test_redact_secrets() -> None:
    pairs = (("token", "aaa"), ("password", "bbb"), ("api_key", "ccc"))
    text = " ".join(name + "=" + value for name, value in pairs)
    redacted = redact_secrets(text)
    assert "aaa" not in redacted
    assert "bbb" not in redacted
    assert "token=<redacted>" in redacted
    assert "password=<redacted>" in redacted
    assert "api_key=<redacted>" in redacted
