from quality_gates.decision import ExecutionState, evaluate, execution_state
from quality_gates.gates.common import skip_result
from quality_gates.models import GateResult


def test_missing_tool_is_unsupported_not_a_successful_skip() -> None:
    result = skip_result("compile", "compiler missing", tool="gcc")

    assert execution_state(result) is ExecutionState.UNSUPPORTED
    assert evaluate([result], ["compile"]).approved is False


def test_not_applicable_gate_does_not_block_its_selected_plan() -> None:
    result = skip_result("ui", "no UI project detected")

    assert execution_state(result) is ExecutionState.NOT_APPLICABLE
    assert evaluate([result], ["ui"]).approved is True


def test_cancelled_and_errored_results_never_approve() -> None:
    cancelled = GateResult(name="lint", status="cancelled")
    errored = GateResult(name="security", status="tool-error")

    decision = evaluate([cancelled, errored], ["lint", "security"])

    assert decision.approved is False
    assert decision.blocking == ["lint: cancelled", "security: errored"]
