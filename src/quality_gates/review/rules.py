"""Load repo-local review rules from markdown files with optional front matter."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path

from quality_gates.agent_loop import LOOP_MARKER
from quality_gates.config import QualityConfig

MAX_AGENT_BODY = 8_000
_AGENT_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    "REVIEW.md",
    "REVIEWER.md",
    ".reviewer.yml",
    ".cursorrules",
    ".clinerules",
    ".github/copilot-instructions.md",
)
_AGENT_GLOBS = (
    ".cursor/rules/*.mdc",
    ".cursor/rules/*.md",
    ".github/instructions/*.md",
    ".claude/rules/*.md",
    ".windsurf/rules/*.md",
    ".clinerules/*.md",
)
_SKIP_LOOP_NAMES = frozenset(
    {
        "the-code-sheriff.mdc",
        "the-code-sheriff.md",
    }
)


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
    rules: list[ReviewRule] = []
    directory = root / (config.review_rules_dir or ".quality/rules")
    if directory.is_dir():
        for path in sorted(directory.glob("*.md")):
            rule = _rule_from_markdown(root, path)
            if rule is not None:
                rules.append(rule)
    if getattr(config, "review_ingest_agent_files", True):
        seen = {rule.source for rule in rules}
        for path in _agent_instruction_paths(root):
            rel = path.relative_to(root).as_posix()
            if rel in seen:
                continue
            rule = _rule_from_markdown(root, path)
            if rule is None:
                continue
            seen.add(rel)
            rules.append(rule)
    return rules


def rules_for_paths(rules: list[ReviewRule], paths: list[str]) -> list[ReviewRule]:
    if not paths:
        return list(rules)
    return [rule for rule in rules if any(rule.matches(path) for path in paths)]


def _agent_instruction_paths(root: Path) -> list[Path]:
    found: list[Path] = []
    for rel in _AGENT_FILES:
        path = root / rel
        if path.is_file():
            found.append(path)
    for pattern in _AGENT_GLOBS:
        found.extend(sorted(p for p in root.glob(pattern) if p.is_file()))
    return found


def _rule_from_markdown(root: Path, path: Path) -> ReviewRule | None:
    if path.name.lower().startswith("readme"):
        return None
    if path.name.lower() in _SKIP_LOOP_NAMES:
        return None
    if path.parent.name == "the-code-sheriff" and path.stem.lower() == "skill":
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if LOOP_MARKER in text[:800]:
        return None
    meta, body = _front_matter(text)
    body = body.strip()
    if not body:
        return None
    if len(body) > MAX_AGENT_BODY:
        body = body[:MAX_AGENT_BODY] + "\n[truncated]\n"
    name = str(meta.get("name") or path.stem).strip()
    severity = str(meta.get("severity") or "warning").strip().lower()
    if severity not in {"error", "warning", "info"}:
        severity = "warning"
    patterns = _as_patterns(meta.get("paths")) or _as_patterns(meta.get("globs"))
    try:
        source = path.relative_to(root).as_posix()
    except ValueError:
        source = path.name
    return ReviewRule(
        name=name,
        body=body,
        paths=patterns,
        severity=severity,
        source=source,
    )


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
