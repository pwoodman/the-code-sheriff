from __future__ import annotations

from quality_gates.risk import triggered_capabilities


def test_triggered_capabilities() -> None:
    caps = triggered_capabilities(["migrations/001_create.sql", "auth/login.py"])
    assert "migration" in caps
    assert "authorization" in caps
