from __future__ import annotations

from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.gates.common import fail_or_pass, skip_result
from quality_gates.gitutil import git_base_ref, git_changed_names
from quality_gates.impact_graph import (
    Impact,
    analyze,
    build_graph,
    dump_impact,
    is_source,
    is_test,
)
from quality_gates.models import Finding, GateResult

REPORT_LIMIT = 12


def run_impact(
    root: Path,
    config: QualityConfig,
    *,
    base: str | None = None,
) -> GateResult:
    changed = git_changed_names(root, git_base_ref(base))
    if not changed:
        return skip_result(
            "impact", "no changed files vs base — skipping impact analysis"
        )

    sources = [name for name in changed if is_source(name)]
    if not sources:
        return skip_result(
            "impact",
            "changed files are not source (docs/config only) — no upstream/downstream graph",
        )

    graph = build_graph(root, config)
    impact = analyze(graph, changed, depth=max(1, config.impact_depth))
    dump_impact(root, impact)

    if not impact.changed:
        return skip_result(
            "impact",
            "only test files changed — no production upstream/downstream to validate",
        )

    findings: list[Finding] = []
    notes = _notes(impact)

    for src, missing in impact.broken_upstream.items():
        findings.append(
            Finding(
                gate="impact",
                rule="broken-upstream",
                path=src,
                message=(
                    f"{src} imports {', '.join(missing[:6])} which does not resolve "
                    "in this repo (upstream break)"
                ),
                severity="error",
            )
        )

    if config.impact_require_downstream:
        for src, consumer in impact.unvalidated_downstream[:80]:
            findings.append(
                Finding(
                    gate="impact",
                    rule="unvalidated-downstream",
                    path=consumer,
                    message=(
                        f"{consumer} imports {src} (downstream) but was not updated "
                        "in this change and no test covers either file — update the "
                        "consumer or add/run a test that imports it"
                    ),
                    severity="error",
                )
            )

    severity = "error" if config.impact_require_own_tests else "warning"
    for src in impact.untested_changes:
        if impact.downstream.get(src) or impact.upstream.get(src):
            findings.append(
                Finding(
                    gate="impact",
                    rule="untested-change",
                    path=src,
                    message=(
                        f"{src} has upstream/downstream neighbors but no covering test; "
                        "add a test that imports it so regressions are caught"
                    ),
                    severity=severity,
                )
            )

    return fail_or_pass("impact", findings, notes)


def _notes(impact: Impact) -> list[str]:
    down_n = sum(len(items) for items in impact.downstream.values())
    up_n = sum(len(items) for items in impact.upstream.values())
    notes = [
        f"{len(impact.changed)} production file(s): "
        f"{up_n} upstream dep(s), {down_n} downstream consumer(s)",
        "wrote .quality-reports/impact.json",
    ]
    for src in impact.changed[:REPORT_LIMIT]:
        up = impact.upstream.get(src) or []
        down = [item for item in impact.downstream.get(src, []) if not is_test(item)]
        tests = impact.tests.get(src) or []
        bits = []
        if up:
            bits.append("upstream " + ", ".join(up[:4]))
        if down:
            bits.append("downstream " + ", ".join(down[:4]))
        if tests:
            bits.append("validated by " + ", ".join(tests[:3]))
        if bits:
            notes.append(f"{src}: {'; '.join(bits)}")
    leftover = len(impact.changed) - REPORT_LIMIT
    if leftover > 0:
        notes.append(f"… {leftover} more changed file(s) in impact.json")
    return notes
