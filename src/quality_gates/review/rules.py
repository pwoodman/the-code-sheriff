"""Load repo-local review rules from markdown files with optional front matter."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path

from quality_gates.config import QualityConfig


@dataclass
class ReviewRule:
    name: str
    body: str
    paths: list[str]
    severity: str
    source: str

    def matches(self, path: str) -> bool:
        if not self.paths:
            return True
        posix = path.replace("\\", "/").lstrip("./")
        return any(
            fnmatch.fnmatch(posix, pattern)
            or fnmatch.fnmatch(Path(posix).name, pattern)
            for pattern in self.paths
        )


def load_review_rules(root: Path, config: QualityConfig) -> list[ReviewRule]:
    directory = root / (config.review_rules_dir or ".quality/rules")
    if not directory.is_dir():
        return []
    rules: list[ReviewRule] = []
    for path in sorted(directory.glob("*.md")):
        if path.name.lower().startswith("readme"):
            continue
        text = path.read_text(encoding="utf-8")
        meta, body = _front_matter(text)
        body = body.strip()
        if not body:
            continue
        name = str(meta.get("name") or path.stem).strip()
        severity = str(meta.get("severity") or "warning").strip().lower()
        if severity not in {"error", "warning", "info"}:
            severity = "warning"
        rules.append(
            ReviewRule(
                name=name,
                body=body,
                paths=_as_patterns(meta.get("paths")),
                severity=severity,
                source=path.relative_to(root).as_posix(),
            )
        )
    return rules


def rules_for_paths(rules: list[ReviewRule], paths: list[str]) -> list[ReviewRule]:
    if not paths:
        return list(rules)
    return [rule for rule in rules if any(rule.matches(path) for path in paths)]


def _as_patterns(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _front_matter(text: str) -> tuple[dict[str, object], str]:
    if not text.startswith("---"):
        return {}, text
    rest = text[3:].lstrip("\r\n")
    end = rest.find("\n---")
    if end < 0:
        return {}, text
    raw = rest[:end]
    body = rest[end + 4 :].lstrip("\r\n")
    return _parse_simple_yaml(raw), body


def _parse_simple_yaml(raw: str) -> dict[str, object]:
    meta: dict[str, object] = {}
    current: str | None = None
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and current:
            existing = meta.get(current)
            if not isinstance(existing, list):
                existing = [] if existing is None else [existing]
            existing.append(stripped[2:].strip().strip("\"'"))
            meta[current] = existing
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        current = key
        if not value:
            meta[key] = []
        elif value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            meta[key] = [
                part.strip().strip("\"'") for part in inner.split(",") if part.strip()
            ]
        else:
            meta[key] = value
    return meta
