"""Inline and file-based overrides for findings.

Teams need a cheap way to say "this hit is known" without a SaaS dashboard.
Inline comments win for a single line; `.quality/ignore.toml` is the durable
record; `quality.exceptions` remains the signed, expiring merge-policy form.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from quality_gates.models import Finding, GateResult
from quality_gates.review.routing import glob_match

IGNORE_FILE = ".quality/ignore.toml"
IGNORE_RE = re.compile(
    r"quality:\s*ignore(?:-(next-line|file))?(?:\s+([^\s#]+))?",
    re.I,
)


@dataclass(frozen=True)
class IgnoreRule:
    rule: str | None = None
    gate: str | None = None
    path: str | None = None
    reason: str = ""
    owner: str = ""
    expires: str | None = None

    def active(self) -> bool:
        if not self.expires:
            return True
        try:
            expires = datetime.fromisoformat(self.expires.replace("Z", "+00:00"))
        except ValueError:
            return False
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        return expires > datetime.now(UTC)


def load_ignore_rules(root: Path) -> list[IgnoreRule]:
    path = root / IGNORE_FILE
    if not path.is_file():
        return []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    rows = data.get("ignore") or data.get("ignores") or []
    if not isinstance(rows, list):
        return []
    out: list[IgnoreRule] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        rule = IgnoreRule(
            rule=_opt_str(item.get("rule")),
            gate=_opt_str(item.get("gate")),
            path=_opt_str(item.get("path")),
            reason=str(item.get("reason") or "").strip(),
            owner=str(item.get("owner") or "").strip(),
            expires=_opt_str(item.get("expires")),
        )
        if rule.active():
            out.append(rule)
    return out


def apply_ignores(
    results: list[GateResult], root: Path, extra: list[IgnoreRule] | None = None
) -> list[GateResult]:
    rules = load_ignore_rules(root) + list(extra or [])
    for result in results:
        kept: list[Finding] = []
        ignored = 0
        for item in result.findings:
            why = ignore_reason(root, item, rules)
            if why:
                ignored += 1
                item.severity = "info"
                item.reason = why
                continue
            kept.append(item)
        if ignored:
            result.findings = kept
            result.notes.append(f"ignored {ignored} finding(s) via quality:ignore")
            if result.status == "fail" and not result.error_count():
                result.status = "pass"
    return results


def ignore_reason(
    root: Path, finding: Finding, rules: list[IgnoreRule] | None = None
) -> str | None:
    """Return the ignore reason, or None if the finding still counts."""
    posix = (finding.path or "").replace("\\", "/").lstrip("./")
    rule_id = (finding.rule or "").strip()
    for item in rules or []:
        if not item.active():
            continue
        if item.gate and item.gate != finding.gate:
            continue
        if item.rule and item.rule not in {rule_id, "*", f"{finding.gate}:{rule_id}"}:
            continue
        if item.path and posix and not _path_match(posix, item.path):
            continue
        if item.path and not posix and not item.path.startswith("*"):
            continue
        owner = f" ({item.owner})" if item.owner else ""
        return f"ignored{owner}: {item.reason or 'quality ignore file'}"
    if posix and finding.line:
        inline = _inline_reason(root / posix, finding.line, rule_id, finding.gate)
        if inline:
            return inline
    if posix:
        file_reason = _file_header_ignore(root / posix, rule_id, finding.gate)
        if file_reason:
            return file_reason
    return None


def append_ignore(
    root: Path,
    *,
    rule: str,
    path: str | None = None,
    gate: str | None = None,
    reason: str,
    owner: str,
    days: int = 90,
) -> Path:
    dest = root / IGNORE_FILE
    dest.parent.mkdir(parents=True, exist_ok=True)
    expires = (datetime.now(UTC) + timedelta(days=max(1, days))).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    block = [
        "[[ignore]]",
        f'rule = "{_escape(rule)}"',
    ]
    if gate:
        block.append(f'gate = "{_escape(gate)}"')
    if path:
        block.append(f'path = "{_escape(path)}"')
    block.append(f'reason = "{_escape(reason)}"')
    if owner:
        block.append(f'owner = "{_escape(owner)}"')
    block.append(f'expires = "{expires}"')
    block.append("")
    existing = (
        dest.read_text(encoding="utf-8")
        if dest.is_file()
        else "# quality ignore overrides\n\n"
    )
    if existing and not existing.endswith("\n"):
        existing += "\n"
    dest.write_text(existing + "\n".join(block), encoding="utf-8")
    return dest


def _inline_reason(path: Path, line: int, rule: str, gate: str) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    if line < 1 or line > len(lines):
        return None
    current = IGNORE_RE.search(lines[line - 1])
    if current and (current.group(1) or "").lower() != "file":
        target = (current.group(2) or "*").strip()
        if _rule_matches(target, rule, gate):
            return f"ignored via quality:ignore {target}"
    if line >= 2:
        previous = IGNORE_RE.search(lines[line - 2])
        if previous and (previous.group(1) or "").lower() == "next-line":
            target = (previous.group(2) or "*").strip()
            if _rule_matches(target, rule, gate):
                return f"ignored via quality:ignore-next-line {target}"
    return None


def _file_header_ignore(path: Path, rule: str, gate: str) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[:40]
    except OSError:
        return None
    for text in lines:
        match = IGNORE_RE.search(text)
        if not match:
            continue
        scope = (match.group(1) or "").lower()
        target = (match.group(2) or "*").strip()
        if scope == "file" and _rule_matches(target, rule, gate):
            return f"ignored via quality:ignore-file {target}"
        # File-level missing-tests / timing accepts a bare ignore in the header.
        if (
            not match.group(1)
            and _rule_matches(target, rule, gate)
            and rule
            in {
                "missing-tests",
                "untested-change",
                "timing-regression",
            }
        ):
            return f"ignored via quality:ignore {target}"
    return None


def _rule_matches(target: str, rule: str, gate: str) -> bool:
    if not target or target == "*":
        return True
    if target == rule or target == f"{gate}:{rule}":
        return True
    return target.endswith(":*") and target.split(":", 1)[0] == gate


def _path_match(posix: str, pattern: str) -> bool:
    if posix == pattern:
        return True
    return glob_match(posix, pattern) or glob_match(posix, pattern.lstrip("./"))


def _opt_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
