"""One conservative merge-decision evaluator for every quality interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from quality_gates.models import GateResult


class ExecutionState(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_APPLICABLE = "not-applicable"
    UNSUPPORTED = "unsupported"
    BLOCKED = "blocked"
    ERRORED = "errored"
    CANCELLED = "cancelled"


_STATUS_STATES = {
    "passed": ExecutionState.PASSED,
    "pass": ExecutionState.PASSED,
    "success": ExecutionState.PASSED,
    "warning": ExecutionState.PASSED,
    "failed": ExecutionState.FAILED,
    "fail": ExecutionState.FAILED,
    "not-applicable": ExecutionState.NOT_APPLICABLE,
    "skip": ExecutionState.NOT_APPLICABLE,
    "unsupported": ExecutionState.UNSUPPORTED,
    "missing": ExecutionState.UNSUPPORTED,
    "blocked": ExecutionState.BLOCKED,
    "errored": ExecutionState.ERRORED,
    "tool-error": ExecutionState.ERRORED,
    "timeout": ExecutionState.ERRORED,
    "cancelled": ExecutionState.CANCELLED,
}


def execution_state(result: GateResult) -> ExecutionState:
    """Normalize legacy result strings without discarding explicit evidence."""
    if result.status == "fail" or result.error_count() > 0:
        raw = (result.exit_state or "failed").strip().lower()
        return _STATUS_STATES.get(raw, ExecutionState.FAILED)
    raw = (result.exit_state or result.status).strip().lower()
    return _STATUS_STATES.get(raw, ExecutionState.ERRORED)


@dataclass(frozen=True)
class Decision:
    approved: bool
    blocking: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def evaluate(results: list[GateResult], required: list[str] | set[str]) -> Decision:
    """Require fresh success for every selected required gate.

    ``not-applicable`` is a successful applicability decision; unsupported tools,
    cancellation, scanner errors, and absent result records are never approval.
    Advisory gates not in ``required`` do not block approval.
    """
    by_name = {item.name: item for item in results}
    required_names = sorted(set(required))
    missing = [name for name in required_names if name not in by_name]
    blocking: list[str] = []
    for name in required_names:
        result = by_name.get(name)
        if not result:
            continue
        state = execution_state(result)
        if state in {
            ExecutionState.FAILED,
            ExecutionState.UNSUPPORTED,
            ExecutionState.BLOCKED,
            ExecutionState.ERRORED,
            ExecutionState.CANCELLED,
        }:
            blocking.append(f"{name}: {state.value}")
    return Decision(
        approved=not missing and not blocking,
        blocking=sorted(blocking),
        missing=missing,
    )
