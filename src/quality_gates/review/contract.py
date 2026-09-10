"""Shared finding payload: what / where / why / fix / patch / verify / agent prompt."""

from __future__ import annotations

from typing import Any

from quality_gates.diagnostics import pointer
from quality_gates.models import Finding
from quality_gates.playbook import autofix_command
from quality_gates.review.parse import fingerprint


def verify_command(finding: Finding) -> str:
    if finding.verify:
        return finding.verify
    gate = finding.gate or "run"
    if gate == "review":
        return "quality review"
    return f"quality {gate}"


def finding_payload(finding: Finding) -> dict[str, Any]:
    loc = pointer(finding)
    payload: dict[str, Any] = {
        "id": fingerprint(finding, bucket=1),
        "gate": finding.gate,
        "severity": finding.severity,
        "message": finding.message,
        "location": loc,
        "verify": verify_command(finding),
    }
    for key in (
        "path",
        "line",
        "column",
        "rule",
        "language",
        "tool",
        "reason",
        "suggestion",
        "documentation_url",
        "snippet",
        "patch",
        "confidence",
        "cwe",
        "owasp",
        "epss",
        "reproduce",
    ):
        value = getattr(finding, key)
        if value is not None and value != "":
            payload[key] = value
    command = autofix_command(payload)
    if command:
        payload["autofix"] = command
    return payload


def agent_prompt(finding: Finding) -> str:
    loc = pointer(finding)
    lines = [
        f"Fix this {finding.gate} finding, then re-run `{verify_command(finding)}`.",
        f"Where: {loc}",
        f"What: {finding.message}",
    ]
    if finding.rule:
        lines.append(f"Rule: {finding.rule}")
    if finding.snippet:
        lines.append(f"Snippet: {finding.snippet}")
    if finding.reason:
        lines.append(f"Why: {finding.reason}")
    if finding.suggestion:
        lines.append(f"Fix: {finding.suggestion}")
    if finding.patch:
        lines.append("Patch:\n" + finding.patch)
    if finding.owasp:
        lines.append(f"OWASP: {finding.owasp}")
    if finding.cwe:
        lines.append(f"CWE: {finding.cwe}")
    if finding.reproduce:
        lines.append("Steps of reproduction:\n" + finding.reproduce)
    if finding.documentation_url:
        lines.append(f"Docs: {finding.documentation_url}")
    command = autofix_command(
        {
            "gate": finding.gate,
            "path": finding.path,
            "line": finding.line,
            "patch": finding.patch,
            "suggestion": finding.suggestion,
        }
    )
    if command:
        lines.append(f"Autofix: `{command}`")
    return "\n".join(lines)


def suggestion_fence(finding: Finding) -> str | None:
    """GitHub apply-patch body when the finding has a single-hunk replacement."""
    patch = (finding.patch or "").strip()
    if not patch:
        return None
    body = _replacement_text(patch)
    if not body or ("\n" in body and body.count("\n") > 40):
        return None
    return f"```suggestion\n{body.rstrip()}\n```"


def _replacement_text(patch: str) -> str:
    if "```suggestion" in patch:
        start = patch.find("```suggestion")
        rest = patch[start:].split("\n", 1)[-1]
        end = rest.find("```")
        return rest[:end] if end >= 0 else rest
    added: list[str] = []
    looks_unified = False
    for line in patch.splitlines():
        if line.startswith(("@@", "diff ", "--- ", "+++ ")):
            looks_unified = True
            continue
        if looks_unified:
            if line.startswith("+") and not line.startswith("+++"):
                added.append(line[1:])
            elif line.startswith("-") and not line.startswith("---"):
                continue
        else:
            added.append(line)
    return "\n".join(added) if added else patch
