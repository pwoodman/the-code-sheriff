"""High-confidence clean-code smells common in AI-generated diffs.

These are not Clean Code dogma (no 4-line functions). Thresholds match what
makes code hard to test, review, or auto-merge: deep nests, oversized
functions, silent failure, and unexplained literals that appear more than once.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path

from quality_gates.models import Finding

NEST_DEPTH = 5
LONG_FUNCTION_LINES = 80
ALLOWED_NUMBERS = frozenset(
    {
        -1,
        0,
        1,
        2,
        3,
        4,
        5,
        8,
        10,
        16,
        24,
        32,
        60,
        64,
        100,
        128,
        256,
        512,
        1000,
        1024,
        2048,
        3600,
        8080,
        80,
        443,
    }
)
_NUMBER = re.compile(r"(?<![\w.])(-?(?:\d+\.\d+|\d+))(?![\w.])")
_CONST_ASSIGN = re.compile(r"^\s*[A-Z][A-Z0-9_]*\s*=")
_SWALLOW_PY = re.compile(r"except(?:\s+\w+(?:\s+as\s+\w+)?)?\s*:\s*(?:pass|\.\.\.)\s*$")
_BARE_EXCEPT = re.compile(r"except\s*:")
_SWALLOW_JS = re.compile(r"catch\s*(?:\([^)]*\))?\s*\{\s*\}")
_COMMENT_OR_STRING = re.compile(r"^\s*(?:#|//|\*|/\*|\")")
SOURCE_SUFFIXES = (".py", ".js", ".ts", ".tsx", ".jsx")


def craft_review(diff: str, root: Path | None = None) -> list[Finding]:
    """Scan a unified diff (and optional working tree) for craft defects."""
    findings: list[Finding] = []
    added = _added_lines(diff)
    findings.extend(_line_findings(added))
    texts = _working_texts(added, root)
    for path, text in texts.items():
        if path.endswith(".py"):
            findings.extend(python_ast_findings(path, text))
    return _dedupe(findings)


def _added_lines(diff: str) -> dict[str, list[tuple[int, str]]]:
    current: str | None = None
    line_no = 0
    added: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for raw in diff.splitlines():
        if raw.startswith("+++ b/"):
            current = raw[6:]
            if current == "/dev/null":
                current = None
            continue
        if raw.startswith("@@"):
            match = re.search(r"\+(\d+)", raw)
            line_no = int(match.group(1)) if match else 0
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            if current:
                added[current].append((line_no, raw[1:]))
            line_no += 1
        elif raw.startswith(" ") and not raw.startswith("+++"):
            line_no += 1
    return added


def _working_texts(
    added: dict[str, list[tuple[int, str]]], root: Path | None
) -> dict[str, str]:
    texts: dict[str, str] = {}
    for path in added:
        if not path.endswith(SOURCE_SUFFIXES):
            continue
        if root is not None:
            candidate = root / path
            if candidate.is_file():
                try:
                    texts[path] = candidate.read_text(encoding="utf-8")
                    continue
                except (OSError, UnicodeError):
                    pass
        lines = added[path]
        if lines:
            texts[path] = "\n".join(text for _line, text in lines) + "\n"
    return texts


def _line_findings(added: dict[str, list[tuple[int, str]]]) -> list[Finding]:
    findings: list[Finding] = []
    for path, rows in added.items():
        if _skip_path(path):
            continue
        numbers: dict[str, list[int]] = defaultdict(list)
        for line_no, text in rows:
            stripped = text.strip()
            if _SWALLOW_PY.search(stripped) or _SWALLOW_JS.search(stripped):
                findings.append(
                    _finding(
                        path,
                        line_no,
                        "swallowed-exception",
                        "error",
                        "Exception is swallowed with an empty handler",
                        "Failures disappear; operators and tests cannot see them.",
                        "Log, re-raise, or return an explicit error result. Never `except: pass`.",
                    )
                )
            elif _BARE_EXCEPT.search(stripped) and path.endswith(".py"):
                findings.append(
                    _finding(
                        path,
                        line_no,
                        "bare-except",
                        "error",
                        "Bare `except:` also catches SystemExit and KeyboardInterrupt",
                        "A cancel or bug becomes a silent success path.",
                        "Catch a specific exception type, or at least `Exception`.",
                    )
                )
            if _COMMENT_OR_STRING.match(stripped) or _CONST_ASSIGN.match(text):
                continue
            for match in _NUMBER.finditer(text):
                raw = match.group(1)
                if raw in {"0", "1", "-1", "2"}:
                    continue
                try:
                    value = float(raw) if "." in raw else int(raw)
                except ValueError:
                    continue
                if value in ALLOWED_NUMBERS:
                    continue
                numbers[raw].append(line_no)
        for raw, lines in numbers.items():
            if len(lines) < 2:
                continue
            findings.append(
                _finding(
                    path,
                    lines[0],
                    "magic-number",
                    "warning",
                    f"Literal `{raw}` is used {len(lines)} times without a name",
                    "Unnamed literals hide policy (timeouts, rates, limits) and drift.",
                    f"Extract a named constant that says what `{raw}` means, then reuse it.",
                )
            )
    return findings


def python_ast_findings(path: str, text: str) -> list[Finding]:
    if _skip_path(path):
        return []
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError:
        return []
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            end = getattr(node, "end_lineno", None) or start
            length = end - start + 1
            if length >= LONG_FUNCTION_LINES:
                findings.append(
                    _finding(
                        path,
                        start,
                        "long-function",
                        "warning",
                        f"`{node.name}` is {length} lines (threshold {LONG_FUNCTION_LINES})",
                        "Long functions mix responsibilities and are hard to test or review.",
                        "Extract one named helper per job (validate, compute, format) — not 4-line dogma.",
                    )
                )
    visitor = _NestVisitor()
    visitor.visit(tree)
    for line, depth in visitor.hits:
        findings.append(
            _finding(
                path,
                line,
                "deep-nesting",
                "warning",
                f"Control flow nested {depth} levels deep (threshold {NEST_DEPTH})",
                "Deep nests hide the real decision and are a common AI-generated smell.",
                "Extract the inner nest into a named predicate or helper (POLA: the name is the why).",
            )
        )
    return findings


class _NestVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.depth = 0
        self.hits: list[tuple[int, int]] = []

    def visit_If(self, node: ast.If) -> None:
        self.depth += 1
        if self.depth == NEST_DEPTH:
            self.hits.append((node.lineno, self.depth))
        for stmt in node.body:
            self.visit(stmt)
        self.depth -= 1
        # Python represents `elif` as a nested If in orelse. Keep it at the
        # same depth as the parent `if` so dispatch chains are not "nests".
        if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
            self.visit(node.orelse[0])
        else:
            for stmt in node.orelse:
                self.visit(stmt)

    def _enter(self, node: ast.AST) -> None:
        self.depth += 1
        self.generic_visit(node)
        self.depth -= 1

    visit_For = _enter
    visit_AsyncFor = _enter
    visit_While = _enter
    visit_With = _enter
    visit_AsyncWith = _enter


def _finding(
    path: str,
    line: int,
    rule: str,
    severity: str,
    message: str,
    reason: str,
    suggestion: str,
) -> Finding:
    return Finding(
        gate="review",
        severity=severity,
        path=path,
        line=line,
        rule=rule,
        message=message,
        reason=reason,
        suggestion=suggestion,
        verify="quality review",
    )


def _skip_path(path: str) -> bool:
    posix = path.replace("\\", "/").lstrip("./")
    if posix.endswith(".md"):
        return True
    lowered = f"/{posix.lower()}/"
    return any(
        marker in lowered
        for marker in ("/test", "/tests/", "/__tests__/", "/fixtures/", "/spec/")
    )


def _dedupe(findings: list[Finding]) -> list[Finding]:
    seen: set[tuple[str | None, int | None, str | None]] = set()
    unique: list[Finding] = []
    for item in findings:
        key = (item.path, item.line, item.rule)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique
