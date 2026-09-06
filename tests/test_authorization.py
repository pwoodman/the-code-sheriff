from __future__ import annotations

from quality_gates.authorization import (
    blocked_gate_result,
    check_authorization,
    is_authorized,
)
from quality_gates.config import QualityConfig


def test_authorization_checks() -> None:
    trusted_cfg = QualityConfig(trust="trusted")
    untrusted_cfg = QualityConfig(trust="untrusted")

    assert is_authorized(trusted_cfg, "test", permission="execution") is True
    assert is_authorized(untrusted_cfg, "test", permission="execution") is False
    assert is_authorized(untrusted_cfg, "lint", permission="read-only") is True

    reason = check_authorization(untrusted_cfg, "test run", permission="execution")
    assert reason is not None
    assert "requires quality.trust = 'trusted'" in reason

    blocked = blocked_gate_result("test", "not allowed")
    assert blocked.status == "blocked"
    assert blocked.exit_state == "blocked"
