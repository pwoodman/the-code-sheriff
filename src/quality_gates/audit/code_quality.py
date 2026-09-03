"""Evidence-backed incomplete and dead-code detectors.

Python uses its AST. Other languages only use narrow lexical forms whose block
structure is explicit; unsupported combinations are reported as such instead
of being presented as parser-backed analysis.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from quality_gates.audit.catalog import CHECK_BY_ID, Check
from quality_gates.audit.model import AuditFinding
from quality_gates.audit.walk import FileHit, RepoContext

LANGUAGE_BY_SUFFIX = {
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".cs": "csharp",
    ".c": "c",
    ".h": "c/cpp",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hh": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".go": "go",
    ".rs": "rust",
    ".php": "php",
    ".rb": "ruby",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".dart": "dart",
    ".scala": "scala",
    ".sc": "scala",
    ".lua": "lua",
    ".r": "r",
    ".rmd": "r",
    ".m": "matlab",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".fish": "shell",
    ".ps1": "powershell",
    ".psm1": "powershell",
}

# Public capability truth used by reports/tests. "lexical-narrow" deliberately
# does not imply AST-level precision.
CODE_QUALITY_CAPABILITIES = {
    language: {"stubs": "lexical-narrow", "unreachable": "lexical-narrow"}
    for language in {
        "javascript",
        "typescript",
        "java",
        "csharp",
        "c",
        "c/cpp",
        "cpp",
        "go",
        "rust",
        "php",
        "swift",
        "kotlin",
        "dart",
        "scala",
    }
}
CODE_QUALITY_CAPABILITIES.update(
    {
        "python": {"stubs": "ast", "unreachable": "ast", "unused": "ast"},
        "ruby": {"stubs": "lexical-narrow", "unreachable": "unsupported"},
        "lua": {"stubs": "lexical-narrow", "unreachable": "unsupported"},
        "r": {"stubs": "lexical-narrow", "unreachable": "unsupported"},
        "matlab": {"stubs": "lexical-narrow", "unreachable": "unsupported"},
        "shell": {"stubs": "lexical-narrow", "unreachable": "unsupported"},
        "powershell": {"stubs": "lexical-narrow", "unreachable": "unsupported"},
    }
)

_CONTROL = re.compile(r"^(?:if|for|while|switch|catch|try|else|do|match)\b")
_ARROW_EMPTY = re.compile(
    r"^(?:export\s+)?(?:const|let|var)\s+\w+\s*=\s*"
    r"(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>\s*\{\s*\}\s*;?$"
)
_NAMED_FUNCTION = re.compile(r"\b(?:function|func|fn|fun|def)\s+[A-Za-z_$][\w$]*")
_GENERIC_CALLABLE = re.compile(
    r"^(?:(?:public|private|protected|internal|static|final|virtual|override|"
    r"async|unsafe|extern|inline|suspend|open|sealed)\s+)*"
    r"(?:[\w:<>,?\[\]*&]+\s+)+[A-Za-z_$][\w$]*\s*\([^;{}]*\)"
)
_TERMINATOR = re.compile(
    r"^(?:return(?:\s+[^;]+)?|throw\s+[^;]+|break|continue)\s*;\s*$"
)
_GO_TERMINATOR = re.compile(r"^(?:return(?:\s+.+)?|break|continue)\s*$")


def scan_code_quality(ctx: RepoContext) -> dict[int, list[AuditFinding]]:
    """Find high-confidence stubs, unused imports, and unreachable statements."""
    grouped: dict[int, list[AuditFinding]] = {}
    for hit in ctx.files:
        if hit.is_test or not hit.is_source:
            continue
        suffix = hit.path.suffix.lower()
        if suffix != ".py":
            language = LANGUAGE_BY_SUFFIX.get(suffix)
            if language:
                _scan_lexical(hit, language, grouped)
            continue
        if hit.path.name == "__init__.py":
            continue
        try:
            tree = ast.parse(hit.text, filename=hit.relative)
        except SyntaxError:
            # Compile/lint gates own syntax errors; the audit must remain usable.
            continue

        _scan_stubs(tree, hit, grouped)
        _scan_unused_imports(tree, hit, grouped)
        _scan_unreachable(tree, hit, grouped)
    return grouped


def code_quality_capability_notes(ctx: RepoContext) -> list[str]:
    languages = {
        LANGUAGE_BY_SUFFIX[hit.path.suffix.lower()]
        for hit in ctx.files
        if hit.path.suffix.lower() in LANGUAGE_BY_SUFFIX
    }
    unsupported = sorted(
        f"{language}:unreachable"
        for language in languages
        if CODE_QUALITY_CAPABILITIES[language]["unreachable"] == "unsupported"
    )
    return (
        ["code-quality unsupported capabilities: " + ", ".join(unsupported)]
        if unsupported
        else []
    )


def _scan_lexical(
    hit: FileHit, language: str, grouped: dict[int, list[AuditFinding]]
) -> None:
    significant = [
        (index, line, line.strip())
        for index, line in enumerate(hit.lines, 1)
        if line.strip() and not _comment_only(line.strip(), language)
    ]
    for position, (line_no, _line, _stripped) in enumerate(significant):
        if _empty_callable(significant, position, language):
            grouped.setdefault(51, []).append(
                _finding(
                    CHECK_BY_ID[51],
                    hit,
                    line_no,
                    f"{language} callable has an empty implementation body.",
                    "A callable has an explicit body but cannot perform work.",
                    "Implement the callable or declare the interface/abstract contract explicitly.",
                    f"{language}-empty-body",
                )
            )
        if CODE_QUALITY_CAPABILITIES[language][
            "unreachable"
        ] != "unsupported" and _unreachable_after(significant, position, language):
            next_line = significant[position + 1][0]
            grouped.setdefault(57, []).append(
                _finding(
                    CHECK_BY_ID[57],
                    hit,
                    next_line,
                    f"{language} statement is unreachable after unconditional control flow.",
                    "The next same-block statement cannot execute.",
                    "Remove the dead statement or correct the preceding control flow.",
                    f"{language}-unreachable",
                )
            )


def _empty_callable(
    lines: list[tuple[int, str, str]], position: int, language: str
) -> bool:
    _line_no, _raw, stripped = lines[position]
    if language == "ruby":
        return (
            stripped.startswith("def ")
            and position + 1 < len(lines)
            and lines[position + 1][2] == "end"
        )
    if language in {"lua", "matlab"}:
        prefix = "function " if language == "lua" else "function"
        return (
            stripped.startswith(prefix)
            and position + 1 < len(lines)
            and lines[position + 1][2] == "end"
        )
    if language == "r":
        return bool(re.search(r"<-\s*function\s*\([^)]*\)\s*\{\s*\}\s*$", stripped))
    if language == "shell":
        return bool(
            re.match(
                r"^(?:function\s+)?[\w.-]+\s*(?:\(\s*\))?\s*\{\s*:\s*;\s*\}$", stripped
            )
        )
    if language == "powershell":
        return bool(re.match(r"^function\s+[\w-]+\s*\{\s*\}$", stripped, re.I))
    if not _looks_callable(stripped):
        return False
    if re.search(r"\{\s*\}\s*;?$", stripped):
        return True
    return (
        stripped.endswith("{")
        and position + 1 < len(lines)
        and lines[position + 1][2] in {"}", "};"}
        and _indent(lines[position + 1][1]) == _indent(lines[position][1])
    )


def _looks_callable(line: str) -> bool:
    normalized = line.strip()
    if _CONTROL.match(normalized) or normalized.startswith(("abstract ", "interface ")):
        return False
    return bool(
        _ARROW_EMPTY.match(normalized)
        or _NAMED_FUNCTION.search(normalized)
        or _GENERIC_CALLABLE.match(normalized)
    )


def _unreachable_after(
    lines: list[tuple[int, str, str]], position: int, language: str
) -> bool:
    if position + 1 >= len(lines):
        return False
    _line_no, raw, stripped = lines[position]
    _next_no, next_raw, next_stripped = lines[position + 1]
    terminates = bool(
        _GO_TERMINATOR.match(stripped)
        if language == "go"
        else _TERMINATOR.match(stripped)
    )
    return (
        terminates
        and _indent(raw) == _indent(next_raw)
        and not next_stripped.startswith(("}", "case ", "default:", "else"))
    )


def _comment_only(line: str, language: str) -> bool:
    prefixes = ("#",) if language in {"ruby", "r", "shell"} else ("//", "/*", "*")
    if language in {"lua", "matlab"}:
        prefixes = ("--", "%")
    return line.startswith(prefixes)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _scan_stubs(
    tree: ast.AST, hit: FileHit, grouped: dict[int, list[AuditFinding]]
) -> None:
    visitor = _StubVisitor(hit, grouped)
    visitor.visit(tree)


class _StubVisitor(ast.NodeVisitor):
    def __init__(self, hit: FileHit, grouped: dict[int, list[AuditFinding]]) -> None:
        self.hit = hit
        self.grouped = grouped
        self.protocol_depth = 0

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        is_protocol = any(
            _decorator_name(base).endswith("Protocol") for base in node.bases
        )
        self.protocol_depth += int(is_protocol)
        self.generic_visit(node)
        self.protocol_depth -= int(is_protocol)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_function(node)
        self.generic_visit(node)

    def _check_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        decorators = {_decorator_name(item) for item in node.decorator_list}
        intentional = (
            self.protocol_depth > 0
            or (node.name.startswith("__") and node.name.endswith("__"))
            or any(name.endswith(("abstractmethod", "overload")) for name in decorators)
        )
        if intentional:
            return

        body = list(node.body)
        if body and _is_docstring(body[0]):
            body = body[1:]
        if len(body) != 1 or not _is_empty_statement(body[0]):
            return

        self.grouped.setdefault(51, []).append(
            _finding(
                CHECK_BY_ID[51],
                self.hit,
                node.lineno,
                f"{node.name} has an empty implementation body.",
                "The callable can be invoked successfully but performs no work.",
                "Implement the behavior or make the intentional interface explicit with "
                "an abstract method or protocol.",
                "python-empty-body",
            )
        )


def _scan_unused_imports(
    tree: ast.Module, hit: FileHit, grouped: dict[int, list[AuditFinding]]
) -> None:
    loaded = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    exported = _exported_names(tree)
    for node in ast.walk(tree):
        aliases: list[ast.alias]
        if isinstance(node, ast.Import):
            aliases = node.names
        elif isinstance(node, ast.ImportFrom):
            if node.module == "__future__":
                continue
            aliases = node.names
        else:
            continue
        if _suppresses_unused_import(hit, node.lineno):
            continue
        for alias in aliases:
            if alias.name == "*":
                continue
            bound = alias.asname or alias.name.split(".", 1)[0]
            explicit_reexport = alias.asname == alias.name
            if (
                bound in loaded
                or bound in exported
                or bound.startswith("_")
                or explicit_reexport
            ):
                continue
            grouped.setdefault(57, []).append(
                _finding(
                    CHECK_BY_ID[57],
                    hit,
                    node.lineno,
                    f"Import '{bound}' is never used in this module.",
                    "The dependency remains loaded and maintained although no code "
                    "references it.",
                    "Remove the import, or explicitly export it through __all__ if it is "
                    "part of the module API.",
                    "python-unused-import",
                )
            )


def _scan_unreachable(
    tree: ast.AST, hit: FileHit, grouped: dict[int, list[AuditFinding]]
) -> None:
    for node in ast.walk(tree):
        for _field, value in ast.iter_fields(node):
            if not isinstance(value, list) or not value:
                continue
            if not all(isinstance(item, ast.stmt) for item in value):
                continue
            terminated = False
            for statement in value:
                if terminated:
                    grouped.setdefault(57, []).append(
                        _finding(
                            CHECK_BY_ID[57],
                            hit,
                            statement.lineno,
                            "Statement is unreachable after unconditional control flow.",
                            "This code can never execute and can conceal an incomplete "
                            "refactor or incorrect branch.",
                            "Remove the dead statement or correct the preceding control flow.",
                            "python-unreachable",
                        )
                    )
                    break
                terminated = _always_terminates(statement)


def _always_terminates(node: ast.stmt) -> bool:
    if isinstance(node, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
        return True
    if isinstance(node, ast.If) and node.body and node.orelse:
        return _block_terminates(node.body) and _block_terminates(node.orelse)
    return False


def _block_terminates(statements: list[ast.stmt]) -> bool:
    return bool(statements) and _always_terminates(statements[-1])


def _exported_names(tree: ast.Module) -> set[str]:
    exported: set[str] = set()
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in targets
        ):
            continue
        value = node.value
        if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            exported.update(
                item.value
                for item in value.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            )
    return exported


def _is_docstring(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _is_empty_statement(node: ast.stmt) -> bool:
    return isinstance(node, ast.Pass) or (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and node.value.value is Ellipsis
    )


def _decorator_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_decorator_name(node.value)}.{node.attr}"
    if isinstance(node, ast.Subscript):
        return _decorator_name(node.value)
    return ""


def _suppresses_unused_import(hit: FileHit, line_no: int) -> bool:
    line = hit.lines[line_no - 1].lower()
    return "noqa" in line and ("f401" in line or ":" not in line.split("noqa", 1)[1])


def _finding(
    check: Check,
    hit: FileHit,
    line_no: int,
    finding: str,
    scenario: str,
    fix: str,
    rule: str,
) -> AuditFinding:
    snippet = hit.lines[line_no - 1].strip()[:180]
    return AuditFinding(
        check_id=check.id,
        title=check.title,
        severity=check.severity,
        priority=check.priority,
        category=check.category,
        confidence="HIGH",
        finding=finding,
        why=check.why,
        evidence=f"{hit.relative}:{line_no}: {snippet}",
        scenario=scenario,
        fix=fix,
        path=hit.relative,
        line=line_no,
        component=_component(hit.relative),
        suggested_test=f"Regression: {rule} must not reappear at {hit.relative}.",
        references=f"audit check {check.id} / {rule}",
        can_auto_fix="No",
        regression_test="Yes",
        effort="S",
    )


def _component(relative: str) -> str:
    parts = Path(relative).parts
    return "/".join(parts[:2]) if len(parts) >= 2 else parts[0]
