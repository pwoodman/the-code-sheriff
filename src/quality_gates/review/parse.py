"""Parse, fingerprint, vote on, and locally validate review findings."""

from __future__ import annotations

import json
import re
from collections import defaultdict

from quality_gates.models import Finding

NIT_RE = re.compile(
    r"\b(prettier|gofmt|rustfmt|csharpier|ruff format|google-java-format|"
    r"trailing comma|line length|whitespace only|indent(ation)? style|"
    r"naming convention|missing semicolon)\b",
    re.I,
)
STYLE_RULES = frozenset({"format", "lint", "style", "nits", "formatting"})


def parse_json_object(text: str) -> dict[str, object] | None:
    cleaned = _strip_fence(text.strip())
    start = cleaned.find("{")
    if start < 0:
        return None
    try:
        obj, _end = json.JSONDecoder().raw_decode(cleaned[start:])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def findings_from_payload(payload: dict[str, object]) -> tuple[str, list[Finding]]:
    summary = str(payload.get("summary") or "").strip()
    raw = payload.get("findings")
    if not isinstance(raw, list):
        raw = []
    findings: list[Finding] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        message = str(item.get("message") or item.get("body") or "").strip()
        if not message:
            continue
        severity = str(item.get("severity") or "warning").strip().lower()
        if severity not in {"error", "warning", "info"}:
            severity = "warning"
        line = item.get("line")
        try:
            line_no = int(line) if line is not None and str(line).strip() else None
        except (TypeError, ValueError):
            line_no = None
        path = str(item.get("path") or "").strip() or None
        findings.append(
            Finding(
                gate="review",
                severity=severity,
                path=path,
                line=line_no,
                rule=str(item.get("rule") or "logic").strip() or "logic",
                message=message[:800],
                reason=str(item.get("reason") or "").strip() or None,
                suggestion=str(item.get("suggestion") or "").strip() or None,
                patch=str(item.get("patch") or "").strip() or None,
                verify=str(item.get("verify") or "").strip() or None,
            )
        )
    return summary, findings


def fingerprint(finding: Finding, *, bucket: int = 5) -> str:
    path = (finding.path or "").replace("\\", "/").lstrip("./")
    line = finding.line or 0
    if bucket > 0:
        line = (line // bucket) * bucket
    rule = (finding.rule or "logic").strip().lower()
    return f"{path}|{rule}|{line}"


def majority_vote(
    passes: list[list[Finding]], *, required: int | None = None
) -> list[Finding]:
    if not passes:
        return []
    need = required if required is not None else max(1, (len(passes) + 1) // 2)
    if len(passes) == 1:
        return list(passes[0])
    groups: dict[str, list[Finding]] = defaultdict(list)
    for bunch in passes:
        seen: set[str] = set()
        for item in bunch:
            key = fingerprint(item)
            if key in seen:
                continue
            seen.add(key)
            groups[key].append(item)
    kept: list[Finding] = []
    for items in groups.values():
        if len(items) < need:
            continue
        chosen = max(items, key=lambda item: len(item.message))
        kept.append(chosen)
    return kept


def drop_style_nits(
    findings: list[Finding],
    *,
    allowed_paths: set[str] | None = None,
) -> list[Finding]:
    kept: list[Finding] = []
    seen: set[str] = set()
    allowed = {
        path.replace("\\", "/").lstrip("./") for path in (allowed_paths or set())
    }
    for item in findings:
        if item.rule in {"languages"}:
            continue
        if (item.rule or "").lower() in STYLE_RULES:
            continue
        if NIT_RE.search(item.message) and item.rule not in {
            "unsafe-api",
            "security-gate",
        }:
            continue
        path = (item.path or "").replace("\\", "/").lstrip("./")
        if allowed and path and path not in allowed:
            continue
        key = fingerprint(item, bucket=1)
        if key in seen:
            continue
        seen.add(key)
        kept.append(item)
    return kept


def merge_findings(*groups: list[Finding]) -> list[Finding]:
    seen: set[str] = set()
    out: list[Finding] = []
    for bunch in groups:
        for item in bunch:
            key = fingerprint(item, bucket=1) + "|" + (item.message[:80])
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
    return out


def _strip_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)
