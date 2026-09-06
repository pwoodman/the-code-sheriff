"""Risk-triggered verification gates for migrations, access, resilience, and budgets.

The gates are intentionally configuration-first: an unrelated patch is not
penalised for missing infrastructure, while a change that declares or touches a
risky surface is never represented as verified without executable evidence.
"""

from __future__ import annotations

import re
from pathlib import Path

from quality_gates.authorization import blocked_gate_result, check_authorization
from quality_gates.config import QualityConfig
from quality_gates.gates.common import fail_or_pass, skip_result
from quality_gates.models import Finding, GateResult
from quality_gates.risk import triggered_capabilities
from quality_gates.tools import run


def run_advanced(
    root: Path, config: QualityConfig, capability: str, paths: list[str]
) -> GateResult:
    gate = {
        "migration": "migration",
        "authorization": "authorization",
        "resilience": "resilience",
        "mutation": "mutation",
        "performance": "performance",
    }[capability]
    if capability not in triggered_capabilities(paths):
        return skip_result(gate, f"no {capability} surface changed")
    section = config.raw.get("quality", {}).get(capability, {})
    if not isinstance(section, dict):
        section = {}
    command = section.get("command")
    if not isinstance(command, list) or not all(
        isinstance(item, str) for item in command
    ):
        return GateResult(
            name=gate,
            status="unsupported",
            exit_state="unsupported",
            findings=[
                Finding(
                    gate=gate,
                    rule="verification-not-configured",
                    message=(
                        f"{capability}-sensitive change requires a configured "
                        "verification command"
                    ),
                    severity="error",
                    suggestion=f"set [quality.{capability}].command to an approved command",
                )
            ],
            notes=["risk-triggered verification is required; no command configured"],
        )
    auth_reason = check_authorization(
        config, f"{capability} command", permission="trusted isolated worker"
    )
    if auth_reason:
        return blocked_gate_result(gate, auth_reason)
    result = run(command, cwd=root, timeout=int(section.get("timeout", 600)))
    findings: list[Finding] = []
    if capability == "migration":
        findings.extend(_migration_findings(root, paths, section))
    return fail_or_pass(
        gate,
        findings,
        [f"executed configured {capability} verification"],
        root=root,
        run=result,
    )


def _migration_findings(
    root: Path, paths: list[str], section: dict[str, object]
) -> list[Finding]:
    """Static guardrails supplement the disposable command, never replace it."""
    out: list[Finding] = []
    destructive = re.compile(
        r"\b(drop\s+(table|column)|truncate|delete\s+from)\b", re.I
    )
    for rel in paths:
        if "migration" not in rel.lower() and not rel.lower().endswith("schema.sql"):
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except OSError:
            continue
        if destructive.search(text) and not bool(
            section.get("allow_destructive", False)
        ):
            out.append(
                Finding(
                    gate="migration",
                    rule="destructive-operation",
                    path=rel,
                    message="destructive migration requires an explicit recovery strategy",
                    severity="error",
                )
            )
    return out
