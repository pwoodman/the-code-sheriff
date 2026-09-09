"""Walk unified diffs without copying the +++ / @@ / + loop."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.review.routing import DEFAULT_SKIP_GLOBS, path_skipped

_HUNK_NEW = re.compile(r"\+(\d+)")


def iter_new_file_lines(diff: str) -> Iterator[tuple[str, int, str, str]]:
    """Yield (path, new-file line, kind, text). kind is 'add' or 'context'."""
    current: str | None = None
    new_line = 0
    for raw in diff.splitlines():
        if raw.startswith("+++ b/"):
            current = raw[6:].strip()
            if current == "/dev/null":
                current = None
            continue
        if raw.startswith("@@"):
            match = _HUNK_NEW.search(raw)
            new_line = int(match.group(1)) if match else 0
            continue
        if current is None:
            continue
        added = raw.startswith("+") and not raw.startswith("+++")
        context = raw.startswith(" ")
        if added:
            yield current, new_line, "add", raw[1:]
            new_line += 1
        elif context:
            yield current, new_line, "context", raw[1:]
            new_line += 1


def iter_added_lines(diff: str) -> Iterator[tuple[str, int, str]]:
    """Yield (path, new-file line number, added text) for unified diffs."""
    for path, new_line, kind, text in iter_new_file_lines(diff):
        if kind == "add":
            yield path, new_line, text


def tree_as_diff(root: Path, paths: list[str], skip_globs: list[str]) -> str:
    """Synthesize a unified diff of existing files when git produced none."""
    parts: list[str] = []
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
        count = min(len(lines), 400)
        parts.append(
            f"diff --git a/{rel} b/{rel}\n--- a/{rel}\n+++ b/{rel}\n"
            f"@@ -0,0 +1,{count} @@\n{body}\n"
        )
    return "\n".join(parts)


def load_review_diff(
    root: Path,
    config: QualityConfig,
    *,
    base: str | None,
    diff: str | None,
) -> str | None:
    """Return an explicit diff, git diff, or tree excerpt. None if empty."""
    if diff is not None:
        return diff
    from quality_gates.change_manifest import discover_changes
    from quality_gates.review.context import collect_diff

    text = collect_diff(root, base, config.max_diff_bytes)
    if text.strip():
        return text
    manifest = discover_changes(root, base)
    if manifest.state == "empty":
        return None
    skip_globs = config.review_skip_globs or DEFAULT_SKIP_GLOBS
    return tree_as_diff(root, manifest.paths, skip_globs)
