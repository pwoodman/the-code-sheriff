"""Dependency-aware, explainable quality execution planning."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from quality_gates import GATES
from quality_gates.change_manifest import ChangeManifest
from quality_gates.config import QualityConfig
from quality_gates.risk import triggered_capabilities


@dataclass(frozen=True)
class PlannedTask:
    name: str
    required: bool
    prerequisites: tuple[str, ...]
    inputs: tuple[str, ...]
    reason: str
    permission: str
    status: str = "selected"
    exclusion_reason: str | None = None
    reused_evidence: str | None = None
    uncertainty: str | None = None
    fallback_scope: str | None = None
    execution_count: int = 1

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


_PREREQUISITES = {
    "compile": ("security",),
    "ui": ("compile",),
    "coverage": ("test",),
    "migration": ("contract",),
}


def build_plan(
    gates: list[str],
    config: QualityConfig,
    manifest: ChangeManifest | None,
    all_gates: tuple[str, ...] | list[str] | None = None,
    root: Path | None = None,
) -> list[PlannedTask]:
    paths = tuple(manifest.paths) if manifest else ()
    selected = set(gates)
    plan: list[PlannedTask] = []

    uncertainty = (
        "full repository assessment"
        if manifest is None
        else (
            "change discovery failed; fallback scope"
            if manifest.state == "unknown"
            else "deterministic change manifest"
        )
    )
    fallback_scope = "repository-wide" if manifest is None else "scoped"

    for gate in gates:
        prerequisites = tuple(
            item for item in _PREREQUISITES.get(gate, ()) if item in selected
        )
        risk = gate in triggered_capabilities(list(paths))
        reason = (
            "selected by configured gate policy"
            if manifest is None
            else (
                f"risk-triggered by {len(paths)} changed path(s)"
                if risk
                else f"selected for {len(paths)} changed path(s)"
            )
        )
        reused = None
        if root is not None:
            report = root / ".quality-reports" / f"{gate}.json"
            if report.is_file():
                reused = f"existing {gate} artifact present"

        plan.append(
            PlannedTask(
                name=gate,
                required=gate in config.fail_on or risk,
                prerequisites=prerequisites,
                inputs=paths,
                reason=reason,
                permission=(
                    "trusted isolated worker"
                    if gate
                    in {
                        "coverage",
                        "ui",
                        "compile",
                        "test",
                        "migration",
                        "authorization",
                        "resilience",
                        "mutation",
                        "performance",
                    }
                    else "read-only"
                ),
                status="selected",
                reused_evidence=reused,
                uncertainty=uncertainty,
                fallback_scope=fallback_scope,
                execution_count=1,
            )
        )

    pool = list(all_gates or GATES)
    for gate in pool:
        if gate not in selected:
            plan.append(
                PlannedTask(
                    name=gate,
                    required=False,
                    prerequisites=(),
                    inputs=(),
                    reason="excluded from execution plan",
                    permission="none",
                    status="excluded",
                    exclusion_reason="not applicable to changed surface or excluded by configuration",
                    execution_count=0,
                )
            )
    return plan


def render_plan(plan: list[PlannedTask]) -> str:
    lines = ["Quality execution plan:"]
    selected_tasks = [t for t in plan if t.status == "selected"]
    excluded_tasks = [t for t in plan if t.status == "excluded"]
    for item in selected_tasks:
        needs = f"; needs {', '.join(item.prerequisites)}" if item.prerequisites else ""
        reused = f"; reused: {item.reused_evidence}" if item.reused_evidence else ""
        scope_note = f"; scope: {item.fallback_scope}" if item.fallback_scope else ""
        lines.append(
            f"- {item.name}: {'required' if item.required else 'advisory'}; {item.reason}{needs}; {item.permission}{reused}{scope_note}"
        )
    if excluded_tasks:
        lines.append("\nExcluded gates:")
        for item in excluded_tasks:
            lines.append(f"- {item.name}: excluded ({item.exclusion_reason})")
    lines.append(
        f"\nSummary: {len(selected_tasks)} check(s) selected, {len(excluded_tasks)} excluded."
    )
    return "\n".join(lines)


def write_plan(root: Path, plan: list[PlannedTask]) -> Path:
    path = root / ".quality-reports" / "execution-plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"tasks": [item.to_dict() for item in plan]}, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
