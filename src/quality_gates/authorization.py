"""Centralized execution authorization across gates, plugins, review, and tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quality_gates.config import QualityConfig
    from quality_gates.models import GateResult

TRUSTED = "trusted"
PROMPT = "prompt"
UNTRUSTED = "untrusted"

STATIC_PERMISSIONS = {"read-only", "static"}
EXECUTION_PERMISSIONS = {
    "execution",
    "write",
    "network",
    "trusted isolated worker",
    "isolated",
}


def is_authorized(
    config: QualityConfig,
    operation: str,
    *,
    permission: str = "read-only",
) -> bool:
    """Determine whether an operation is authorized under repository trust."""
    norm_perm = permission.strip().lower()
    if norm_perm in STATIC_PERMISSIONS:
        return True
    return config.trust == TRUSTED


def check_authorization(
    config: QualityConfig,
    operation: str,
    *,
    permission: str = "read-only",
) -> str | None:
    """Return an explicit rejection reason if the operation is not authorized."""
    if is_authorized(config, operation, permission=permission):
        return None
    return (
        f"{operation} requires quality.trust = 'trusted' "
        f"(current trust is {config.trust!r}; permission required: {permission})"
    )


def blocked_gate_result(gate: str, reason: str) -> GateResult:
    """Produce a standard blocked result for unauthorized operations."""
    from quality_gates.models import GateResult

    return GateResult(
        name=gate,
        status="blocked",
        exit_state="blocked",
        notes=[reason],
    )
