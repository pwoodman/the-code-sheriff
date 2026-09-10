from __future__ import annotations

import re
from pathlib import Path

from quality_gates.models import Finding, GateResult
from quality_gates.review.craft import craft_review

DANGEROUS = [
    (re.compile(r"\beval\s*\("), "eval() on untrusted input is a code-injection risk"),
    (re.compile(r"new Function\s*\("), "new Function() is eval in disguise"),
    (re.compile(r"innerHTML\s*="), "innerHTML assignment is a common XSS sink"),
    (re.compile(r"document\.write\s*\("), "document.write is an XSS sink"),
    (re.compile(r"pickle\.loads\s*\("), "pickle.loads can execute arbitrary objects"),
    (re.compile(r"yaml\.load\s*\("), "yaml.load without SafeLoader can execute code"),
    (
        re.compile(r"shell\s*=\s*True"),
        "subprocess shell=True is command-injection-prone",
    ),
    (re.compile(r"verify\s*=\s*False"), "TLS verification disabled"),
    (re.compile(r"md5\s*\("), "MD5 is not suitable for security-sensitive hashing"),
    (
        re.compile(r"SELECT\s+.+\s*\+\s*", re.I),
        "string-concatenated SQL is an injection risk",
    ),
    (
        re.compile(r"Runtime\.getRuntime\(\)\.exec"),
        "Runtime.exec with user input is command injection",
    ),
    (
        re.compile(r"dangerouslySetInnerHTML"),
        "dangerouslySetInnerHTML bypasses React XSS protections",
    ),
    (
        re.compile(r"\bos\.system\s*\("),
        "os.system is command-injection-prone; use subprocess with a list",
    ),
    (
        re.compile(r"child_process\.exec\s*\("),
        "child_process.exec runs a shell string; prefer execFile with argv",
    ),
    (
        re.compile(r"\.unwrap\(\)"),
        "Rust unwrap() panics on None/Err in production paths",
    ),
    (re.compile(r"\bpanic!\s*\("), "Go/Rust panic on a library path"),
    (
        re.compile(r"ObjectInputStream"),
        "Java ObjectInputStream is a deserialization gadget risk",
    ),
    (
        re.compile(r"ignore_changes\s*="),
        "Terraform ignore_changes hides drift from review",
    ),
]

TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")
TEST_HINT = re.compile(r"(test|spec|__tests__)", re.I)
SOURCE_SUFFIXES = (
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".cs",
    ".sql",
    ".php",
    ".rb",
    ".kt",
    ".ex",
    ".tf",
    ".proto",
)
STYLE_GATES = frozenset({"format", "lint"})
# Match audit god-file (800). 400 flagged HTML templates and extracted modules.
LARGE_FILE_LINES = 800
LARGE_PR_SOURCE_LINES = 800


def _scan_unsafe_api(path: str) -> bool:
    """Skip detector catalogs, docs, tests, and fixtures — they mention APIs without calling them."""
    posix = path.replace("\\", "/").lstrip("./")
    if posix.endswith(".md"):
        return False
    if TEST_HINT.search(posix):
        return False
    if "/fixtures/" in f"/{posix}/":
        return False
    return not posix.endswith(("review/heuristic.py", "gates/security.py"))


def heuristic_review(
    diff: str,
    languages: list[str],
    prior: list[GateResult],
    root: Path | None = None,
) -> list[Finding]:
    findings: list[Finding] = []
    current_file = None
    added_by_file: dict[str, int] = {}
    added_source_lines = 0
    test_files_touched = False
    src_files_touched = False

    new_file_line = 0
    for raw in diff.splitlines():
        if raw.startswith("+++ b/"):
            current_file = raw[6:]
            if current_file == "/dev/null":
                current_file = None
            continue
        if raw.startswith("@@"):
            match = re.search(r"\+(\d+)", raw)
            new_file_line = int(match.group(1)) if match else 0
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            if current_file:
                added_by_file[current_file] = added_by_file.get(current_file, 0) + 1
                name = current_file
                if TEST_HINT.search(name):
                    test_files_touched = True
                elif name.endswith(SOURCE_SUFFIXES):
                    src_files_touched = True
                    added_source_lines += 1
                text = raw[1:]
                if TODO_RE.search(text):
                    findings.append(
                        Finding(
                            gate="review",
                            severity="info",
                            path=current_file,
                            line=new_file_line,
                            rule="todo",
                            message="TODO/FIXME introduced in this change — track or resolve before merge",
                            reason="Placeholder work shipping as if the feature is done is a common AI-generated defect.",
                            suggestion="Finish the work, or file a tracked issue and remove the marker from this diff.",
                        )
                    )
                if _scan_unsafe_api(current_file):
                    for pattern, message in DANGEROUS:
                        if pattern.search(text):
                            findings.append(
                                Finding(
                                    gate="review",
                                    severity="error",
                                    path=current_file,
                                    line=new_file_line,
                                    rule="unsafe-api",
                                    message=message,
                                    reason="This API is a known injection, XSS, or crash sink.",
                                    suggestion="Replace it with a safe API (argv subprocess, parameterized SQL, textContent, SafeLoader).",
                                )
                            )
            new_file_line += 1
        elif raw.startswith(" ") and not raw.startswith("+++"):
            new_file_line += 1

    for path, count in added_by_file.items():
        if TEST_HINT.search(path) or path.endswith(".md"):
            continue
        if count >= LARGE_FILE_LINES:
            findings.append(
                Finding(
                    gate="review",
                    severity="warning",
                    path=path,
                    rule="large-file",
                    message=f"{count} lines added in one file — consider splitting the change",
                    reason="Large mixed-concern files hide bugs and make safe auto-merge impossible.",
                    suggestion="Split by responsibility; keep the PR reviewable.",
                )
            )

    if added_source_lines >= LARGE_PR_SOURCE_LINES:
        findings.append(
            Finding(
                gate="review",
                severity="warning",
                rule="large-pr",
                message=(
                    f"diff adds {added_source_lines} production source lines — "
                    "large PRs hide bugs; split if possible"
                ),
                reason="Reviewers and agents miss defects in oversized diffs.",
                suggestion="Split the change so each PR has one reason to exist.",
            )
        )

    if src_files_touched and not test_files_touched:
        findings.append(
            Finding(
                gate="review",
                severity="warning",
                rule="missing-tests",
                message="source changed without an accompanying test file — add coverage for the new behavior",
                reason="Untested new behavior is the usual way AI-generated code ships broken.",
                suggestion="Add a unit test that fails on the old behavior and passes on this change.",
            )
        )

    findings.extend(craft_review(diff, root))

    for result in prior:
        if result.name in STYLE_GATES:
            continue
        if result.name == "dry" and result.findings:
            findings.append(
                Finding(
                    gate="review",
                    severity="warning",
                    rule="dry",
                    message=f"DRY gate found {len(result.findings)} cloned block(s) in this change set",
                )
            )
        if result.name == "security":
            errors = result.error_count()
            if errors:
                findings.append(
                    Finding(
                        gate="review",
                        severity="error",
                        rule="security-gate",
                        message=f"security gate reported {errors} error(s) — treat as blocking",
                    )
                )
        if result.name == "audit":
            errors = result.error_count()
            if errors:
                findings.append(
                    Finding(
                        gate="review",
                        severity="error",
                        rule="audit-gate",
                        message=f"audit gate reported {errors} HIGH-confidence error(s)",
                    )
                )
        if result.name == "impact" and result.findings:
            findings.append(
                Finding(
                    gate="review",
                    severity="warning",
                    rule="impact-gate",
                    message=f"impact gate reported {len(result.findings)} blast-radius issue(s)",
                )
            )

    if languages:
        findings.append(
            Finding(
                gate="review",
                severity="info",
                rule="languages",
                message="languages in this change: " + ", ".join(languages),
            )
        )
    return findings
