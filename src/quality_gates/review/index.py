"""On-disk symbol / route / schema index for cross-file review context."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from quality_gates.config import QualityConfig
from quality_gates.detect import iter_project_files

_DEF = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?(?:def|function|class|interface|fn|func)\s+"
    r"([A-Za-z_][\w]*)",
    re.M,
)
_ROUTE = re.compile(
    r"""(?:@(?:app|router)\.(?:get|post|put|patch|delete)|
        (?:app|router)\.(?:get|post|put|patch|delete)\()""",
    re.I | re.X,
)
_SCHEMA = re.compile(r"(?:message|type|interface|model|table)\s+([A-Za-z_]\w*)", re.I)

INDEX_NAME = "symbol-index.json"


def build_symbol_index(root: Path, config: QualityConfig) -> dict[str, Any]:
    symbols: list[dict[str, Any]] = []
    for path in iter_project_files(root, config):
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if len(text) > 400_000:
            continue
        for match in _DEF.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            symbols.append(
                {"kind": "symbol", "name": match.group(1), "path": rel, "line": line}
            )
        if _ROUTE.search(text):
            symbols.append({"kind": "route", "name": rel, "path": rel, "line": 1})
        for match in _SCHEMA.finditer(text):
            if path.suffix in {".proto", ".graphql", ".sql", ".prisma"}:
                symbols.append(
                    {
                        "kind": "schema",
                        "name": match.group(1),
                        "path": rel,
                        "line": text.count("\n", 0, match.start()) + 1,
                    }
                )
    payload = {"schema_version": "1.0.0", "symbols": symbols, "count": len(symbols)}
    reports = root / ".quality-reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / INDEX_NAME).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def load_symbol_index(root: Path) -> dict[str, Any]:
    path = root / ".quality-reports" / INDEX_NAME
    if not path.is_file():
        return {"symbols": [], "count": 0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"symbols": [], "count": 0}
    return data if isinstance(data, dict) else {"symbols": [], "count": 0}


def search_symbols(
    index: dict[str, Any], query: str, *, limit: int = 8
) -> list[dict[str, Any]]:
    needle = query.lower().strip()
    if not needle:
        return []
    hits = []
    for item in index.get("symbols") or []:
        name = str(item.get("name") or "").lower()
        path = str(item.get("path") or "").lower()
        if needle in name or needle in path:
            hits.append(item)
        if len(hits) >= limit:
            break
    return hits


def callers_of(index: dict[str, Any], name: str) -> list[str]:
    hits = search_symbols(index, name, limit=12)
    return [f"{item.get('path')}:{item.get('line')}" for item in hits]
