"""Turn raw tool findings into what / where / why / fix pointers."""

from __future__ import annotations

import shlex
from pathlib import Path

from quality_gates.diagnostics_help import RULE_HELP, docs_for_rule
from quality_gates.models import Finding, RunResult
from quality_gates.taxonomy import classify_finding


def enrich_finding(
    finding: Finding,
    root: Path | None = None,
    result: RunResult | None = None,
) -> Finding:
    """Fill relative path, snippet, reason, suggestion, docs, and verify when missing."""
    finding.path = _relative_path(finding.path, root)
    finding.snippet = finding.snippet or _snippet(finding.path, finding.line, root)
    why, fix, docs = _rule_help(finding)
    if not finding.reason:
        finding.reason = why or _generic_reason(finding, result)
    if not finding.suggestion:
        finding.suggestion = fix or _generic_suggestion(finding, result)
    if not finding.documentation_url:
        finding.documentation_url = docs or _docs_url(finding)
    if not finding.verify:
        gate = finding.gate or (result.tool if result else None) or "run"
        if gate == "review":
            finding.verify = "quality review"
        else:
            finding.verify = f"quality {gate}"
    if not finding.tool and result is not None:
        finding.tool = result.tool
    return classify_finding(finding)


def enrich_findings(
    findings: list[Finding],
    root: Path | None = None,
    result: RunResult | None = None,
) -> list[Finding]:
    return [enrich_finding(item, root, result) for item in findings]


def pointer(finding: Finding) -> str:
    """Compact `path:line:column` pointer, or the rule/gate when no file is known."""
    loc = finding.path or finding.rule or finding.gate
    if finding.path and finding.line:
        loc = f"{finding.path}:{finding.line}"
        if finding.column:
            loc = f"{loc}:{finding.column}"
    return loc


def _relative_path(path: str | None, root: Path | None) -> str | None:
    if not path:
        return path
    candidate = Path(path)
    if root is not None:
        try:
            return candidate.resolve().relative_to(root.resolve()).as_posix()
        except (OSError, ValueError):
            pass
    return candidate.as_posix()


def _snippet(path: str | None, line: int | None, root: Path | None) -> str | None:
    if not path or not line or line < 1:
        return None
    candidate = Path(path)
    if not candidate.is_file() and root is not None:
        candidate = root / path
    if not candidate.is_file():
        return None
    try:
        text = candidate.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    lines = text.splitlines()
    if line > len(lines):
        return None
    body = lines[line - 1].rstrip()
    if len(body) > 160:
        body = body[:157] + "..."
    return f"{line} | {body}"


def _rule_help(finding: Finding) -> tuple[str | None, str | None, str | None]:
    rule = (finding.rule or "").strip()
    if not rule:
        return None, None, None
    tool = (finding.tool or "").strip().lower()
    gate = (finding.gate or "").strip().lower()
    if rule.startswith("GHSA-") or rule.upper().startswith("GHSA"):
        why, fix, docs = RULE_HELP.get(("osv-scanner", "GHSA"), (None, None, None))
        return why, fix, docs or None
    if rule.upper().startswith("CVE-"):
        why, fix, docs = RULE_HELP.get(("osv-scanner", "CVE"), (None, None, None))
        return why, fix, docs or None
    for key in ((tool, rule), (gate, rule), ("", rule)):
        if key in RULE_HELP:
            why, fix, docs = RULE_HELP[key]
            return why, fix, docs or None
    return None, None, None


def _docs_url(finding: Finding) -> str | None:
    rule = finding.rule
    if not rule:
        return None
    tool = (finding.tool or "").lower()
    return docs_for_rule(tool, rule) or docs_for_rule(finding.language or "", rule)


def _generic_reason(finding: Finding, result: RunResult | None) -> str | None:
    if finding.rule:
        return f"{finding.tool or finding.gate} reported `{finding.rule}`"
    if result is not None and result.returncode not in {0, None}:
        name = result.tool or finding.tool or "command"
        return f"{name} exited with code {result.returncode}"
    return None


def _generic_suggestion(finding: Finding, result: RunResult | None) -> str | None:
    loc = pointer(finding)
    if finding.path:
        return (
            f"Open `{loc}` and apply the {finding.tool or finding.gate} finding, "
            f"then re-run `quality {finding.gate}`."
        )
    if result is not None and result.argv:
        return f"Re-run `{shlex.join(result.argv)}` from `{result.cwd or '.'}`."
    return f"Re-run `quality {finding.gate}` after fixing the reported issue."


def detail_lines(finding: Finding) -> list[str]:
    """Console-oriented why / where / fix lines for a finding."""
    lines: list[str] = []
    if finding.snippet:
        lines.append(f"where: {finding.snippet}")
    if finding.reason:
        lines.append(f"why: {finding.reason}")
    if finding.suggestion:
        lines.append(f"fix: {finding.suggestion}")
    if finding.patch:
        lines.append("patch: available (apply from GitHub suggestion or oracle)")
    if finding.verify:
        lines.append(f"verify: `{finding.verify}`")
    if finding.documentation_url:
        lines.append(f"docs: {finding.documentation_url}")
    return lines
