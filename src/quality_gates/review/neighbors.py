"""Function-level neighbors for review context packing."""

from __future__ import annotations

import re
from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.detect import iter_project_files
from quality_gates.review.context import read_repo_file, safe_repo_path

FUNC_START = re.compile(
    r"^(\s*)(def |async def |fn |func |function |class |pub fn |fn\s+"
    r"|public |private |protected |internal |fun |sub ).+",
    re.I,
)
CALL = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\s*\(")
SKIP = frozenset(
    {
        "if",
        "for",
        "while",
        "switch",
        "return",
        "catch",
        "def",
        "func",
        "fn",
        "function",
        "class",
        "new",
        "print",
        "len",
        "int",
        "str",
        "list",
        "dict",
        "set",
        "map",
        "filter",
        "typeof",
        "await",
        "async",
        "from",
        "import",
        "console",
        "require",
        "super",
        "this",
        "self",
        "Math",
        "Object",
        "Array",
        "JSON",
        "Error",
        "Exception",
        "True",
        "False",
        "None",
    }
)


def function_windows(
    root: Path,
    diff: str,
    config: QualityConfig,
    *,
    already: set[str] | None = None,
) -> list[tuple[str, str]]:
    """Return (path, snippet) windows around functions that the diff touches."""
    seen = set(already or ())
    packed: list[tuple[str, str]] = []
    budget = max(2000, min(8000, config.review_related_bytes // 3))
    used = 0
    for path, line_no in _changed_lines(diff):
        if path in seen:
            continue
        window = _window_at(root, path, line_no)
        if not window:
            continue
        seen.add(path)
        packed.append((path, f"[function window around line {line_no}]\n{window}"))
        used += len(window)
        if used >= budget or len(packed) >= 6:
            break
    if used < budget:
        names = _called_names(diff)
        for rel, snippet in _usages(root, config, names, skip=seen, limit=4):
            packed.append((rel, snippet))
            used += len(snippet)
            if used >= budget:
                break
    return packed


def _changed_lines(diff: str) -> list[tuple[str, int]]:
    current: str | None = None
    new_line = 0
    hits: list[tuple[str, int]] = []
    for raw in diff.splitlines():
        if raw.startswith("+++ b/"):
            current = raw[6:].strip()
            if current == "/dev/null":
                current = None
            continue
        if raw.startswith("@@"):
            match = re.search(r"\+(\d+)", raw)
            new_line = int(match.group(1)) if match else 0
            continue
        if current is None:
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            hits.append((current, new_line))
            new_line += 1
        elif raw.startswith(" "):
            new_line += 1
    return hits


def _window_at(root: Path, rel: str, line_no: int) -> str | None:
    path = safe_repo_path(root, rel)
    if path is None:
        text = read_repo_file(root, rel, limit=20_000)
        if not text:
            return None
        lines = text.splitlines()
    else:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            return None
    if line_no < 1 or line_no > len(lines):
        return None
    start = line_no - 1
    while start > 0 and not FUNC_START.match(lines[start]):
        start -= 1
        if line_no - 1 - start > 80:
            start = max(0, line_no - 16)
            break
    end = min(len(lines), start + 40)
    body = "\n".join(lines[start:end])
    if len(body) > 2400:
        body = body[:2400] + "\n[truncated]"
    return body


def _called_names(diff: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for raw in diff.splitlines():
        if not raw.startswith("+") or raw.startswith("+++"):
            continue
        for match in CALL.finditer(raw[1:]):
            name = match.group(1)
            if name in SKIP or name in seen:
                continue
            seen.add(name)
            names.append(name)
            if len(names) >= 12:
                return names
    return names


def _usages(
    root: Path,
    config: QualityConfig,
    names: list[str],
    *,
    skip: set[str],
    limit: int,
) -> list[tuple[str, str]]:
    if not names:
        return []
    hits: list[tuple[str, str]] = []
    pattern = re.compile(r"\b(" + "|".join(map(re.escape, names[:8])) + r")\s*\(")
    scanned = 0
    for path in iter_project_files(root, config):
        scanned += 1
        if scanned > 200:
            break
        if path.suffix not in {
            ".py",
            ".js",
            ".ts",
            ".tsx",
            ".go",
            ".rs",
            ".java",
            ".cs",
        }:
            continue
        rel = path.relative_to(root).as_posix()
        if rel in skip:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        match = pattern.search(text)
        if not match:
            continue
        line_no = text[: match.start()].count("\n") + 1
        window = _window_at(root, rel, line_no) or match.group(0)
        hits.append((rel, f"[usage of {match.group(1)}]\n{window}"))
        skip.add(rel)
        if len(hits) >= limit:
            break
    return hits
