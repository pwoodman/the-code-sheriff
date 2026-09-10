"""Release-note drafts from merged pull requests."""

from __future__ import annotations

import re
from typing import Any

_USER_HINT = re.compile(
    r"\b(add|adds|added|fix|fixes|fixed|remove|removes|breaking)\b",
    re.I,
)


def draft_notes(pulls: list[dict[str, Any]]) -> list[str]:
    notes: list[str] = []
    for item in pulls:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        if title.lower().startswith(("chore:", "ci:", "test:", "docs:")):
            continue
        if not _USER_HINT.search(title) and "!" not in title:
            continue
        notes.append(_compact(title))
    return notes


def _compact(title: str) -> str:
    cleaned = re.sub(r"^(feat|fix|breaking)[:( ]\s*", "", title, flags=re.I)
    return cleaned.rstrip(".") + "."
