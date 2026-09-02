from __future__ import annotations

from pathlib import Path


def resolve_js_module(
    current: Path, spec: str, root: Path, aliases: dict[str, str]
) -> Path | None:
    if not spec or spec.startswith("node:"):
        return None
    raw = spec
    for prefix, target in aliases.items():
        if raw.startswith(prefix):
            raw = str(Path(target) / raw[len(prefix) :])
            break
    if raw.startswith("."):
        base = current.parent / raw
    elif "/" in raw and not raw.startswith("@"):
        base = root / raw.lstrip("/")
    else:
        return None
    candidates = [
        base,
        Path(str(base) + ".ts"),
        Path(str(base) + ".tsx"),
        Path(str(base) + ".js"),
        Path(str(base) + ".jsx"),
        Path(str(base) + ".mjs"),
        base / "index.ts",
        base / "index.tsx",
        base / "index.js",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None
