"""Cheap, configurable regex gate over the change set."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from quality_gates.change_manifest import discover_changes
from quality_gates.config import QualityConfig
from quality_gates.gates.common import fail_or_pass, skip_result
from quality_gates.models import Finding, GateResult
from quality_gates.review.heuristic import _scan_unsafe_api
from quality_gates.review.routing import DEFAULT_SKIP_GLOBS, path_skipped

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
    text = diff
    if text is None:
        from quality_gates.review.context import collect_diff

        text = collect_diff(root, base, config.max_diff_bytes)
        if not text.strip():
            manifest = discover_changes(root, base)
            if manifest.state == "empty":
                return skip_result("regex", "no diff against the review base")
            text = _tree_excerpt(root, manifest.paths, config)
    skip_globs = config.review_skip_globs or DEFAULT_SKIP_GLOBS
    findings = scan_diff(text, rules, skip_globs)
    notes = [f"{len(rules)} rule(s)", f"{len(findings)} hit(s)"]
    return fail_or_pass("regex", findings, notes)


def scan_diff(
    diff: str,
    rules: list[tuple[str, re.Pattern[str], str, str]],
    skip_globs: list[str],
) -> list[Finding]:
    findings: list[Finding] = []
    current: str | None = None
    new_line = 0
    for raw in diff.splitlines():
        if raw.startswith("+++ b/"):
            current = raw[6:]
            if current == "/dev/null":
                current = None
            continue
        if raw.startswith("@@"):
            match = re.search(r"\+(\d+)", raw)
            new_line = int(match.group(1)) if match else 0
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            if (
                current
                and not path_skipped(current, skip_globs)
                and _scan_unsafe_api(current)
            ):
                text = raw[1:]
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
            new_line += 1
        elif raw.startswith(" ") and not raw.startswith("+++"):
            new_line += 1
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


def _tree_excerpt(root: Path, paths: list[str], config: QualityConfig) -> str:
    parts: list[str] = []
    skip_globs = config.review_skip_globs or DEFAULT_SKIP_GLOBS
    for rel in paths:
        if path_skipped(rel, skip_globs):
            continue
        path = root / rel
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        body = "\n".join(f"+{line}" for line in lines[:400])
        parts.append(
            f"diff --git a/{rel} b/{rel}\n--- a/{rel}\n+++ b/{rel}\n"
            f"@@ -0,0 +1,{min(len(lines), 400)} @@\n{body}\n"
        )
    return "\n".join(parts)
