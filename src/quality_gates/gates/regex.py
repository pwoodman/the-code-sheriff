"""Cheap, configurable regex gate over the change set."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from quality_gates.config import QualityConfig
from quality_gates.gates.common import fail_or_pass, skip_result
from quality_gates.models import Finding, GateResult
from quality_gates.review.diffscan import iter_added_lines, load_review_diff
from quality_gates.review.heuristic import _scan_unsafe_api
from quality_gates.review.routing import path_skipped

DEFAULT_RULES: list[dict[str, str]] = [
    {
        "name": "eval",
        "pattern": r"\beval\s*\(",
        "message": "eval() on untrusted input is a code-injection risk",
        "severity": "error",
    },
    {
        "name": "new-function",
        "pattern": r"new Function\s*\(",
        "message": "new Function() is eval in disguise",
        "severity": "error",
    },
    {
        "name": "pickle-loads",
        "pattern": r"pickle\.loads\s*\(",
        "message": "pickle.loads can execute arbitrary objects",
        "severity": "error",
    },
    {
        "name": "yaml-load",
        "pattern": r"yaml\.load\s*\(",
        "message": "yaml.load without SafeLoader can execute code",
        "severity": "error",
    },
    {
        "name": "shell-true",
        "pattern": r"shell\s*=\s*True",
        "message": "subprocess shell=True is command-injection-prone",
        "severity": "error",
    },
    {
        "name": "innerhtml",
        "pattern": r"innerHTML\s*=",
        "message": "innerHTML assignment is a common XSS sink",
        "severity": "error",
    },
    {
        "name": "swallowed-exception",
        "pattern": r"except(?:\s+\w+)?\s*:\s*(?:pass|continue)\b",
        "message": "Swallowed exception hides failures from operators.",
        "severity": "warning",
    },
    {
        "name": "unawaited-create-task",
        "pattern": r"asyncio\.create_task\s*\(",
        "message": "Unawaited asyncio.create_task can hide errors and leak work.",
        "severity": "warning",
    },
    {
        "name": "n-plus-one",
        "pattern": r"for\s+\w+\s+in\s+.+:\s*(?:\n\s*)?(?:\w+\.)?(?:query|execute|fetch)\(",
        "message": "Query inside a loop looks like an N+1 hot path.",
        "severity": "warning",
    },
]


def run_regex(
    root: Path,
    config: QualityConfig,
    *,
    base: str | None = None,
    diff: str | None = None,
) -> GateResult:
    if not config.regex_enabled:
        return skip_result("regex", "regex gate disabled")
    rules = _compiled_rules(config)
    if not rules:
        return skip_result("regex", "no regex rules configured")
    text = load_review_diff(root, config, base=base, diff=diff)
    if text is None:
        return skip_result("regex", "no diff against the review base")
    skip_globs = config.review_skip_globs or []
    findings = scan_diff(text, rules, skip_globs)
    notes = [f"{len(rules)} rule(s)", f"{len(findings)} hit(s)"]
    return fail_or_pass("regex", findings, notes)


def scan_diff(
    diff: str,
    rules: list[tuple[str, re.Pattern[str], str, str]],
    skip_globs: list[str],
) -> list[Finding]:
    findings: list[Finding] = []
    for current, new_line, text in iter_added_lines(diff):
        if path_skipped(current, skip_globs) or not _scan_unsafe_api(current):
            continue
        for name, pattern, message, severity in rules:
            if pattern.search(text):
                findings.append(
                    Finding(
                        gate="regex",
                        rule=name,
                        path=current,
                        line=new_line,
                        severity=severity,
                        message=message,
                        snippet=text.strip()[:240],
                        suggestion=(
                            "remove the match, or add `# quality:ignore "
                            f"{name}` on this line / "
                            f"`quality ignore add --rule {name} --path {current}`"
                        ),
                    )
                )
    return findings


def _compiled_rules(
    config: QualityConfig,
) -> list[tuple[str, re.Pattern[str], str, str]]:
    rows: list[dict[str, Any]] = []
    if config.regex_include_defaults:
        rows.extend(DEFAULT_RULES)
    rows.extend(config.regex_rules)
    compiled: list[tuple[str, re.Pattern[str], str, str]] = []
    seen: set[str] = set()
    for item in rows:
        name = str(item.get("name") or item.get("id") or "").strip()
        pattern = str(item.get("pattern") or "").strip()
        if not name or not pattern or name in seen:
            continue
        try:
            regex = re.compile(pattern)
        except re.error:
            continue
        seen.add(name)
        compiled.append(
            (
                name,
                regex,
                str(item.get("message") or f"regex {name} matched"),
                str(item.get("severity") or "error"),
            )
        )
    return compiled
