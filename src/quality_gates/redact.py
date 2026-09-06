"""Secret and credential redaction across quality interfaces."""

from __future__ import annotations

import re

_SECRET_VALUE = re.compile(
    r"(?i)\b(token|password|passwd|secret|api[_-]?key|private[_-]?key|auth)=([^\s\"']+)"
)


def redact_secrets(value: str) -> str:
    """Redact tokens, passwords, and sensitive keys from output and prompts."""
    return _SECRET_VALUE.sub(lambda match: f"{match.group(1)}=<redacted>", value)


_redact = redact_secrets
