"""Risk-tier review so most PRs spend cents, not a Sonnet pass."""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path, PurePosixPath

from quality_gates.config import DEFAULT_REVIEW_SKIP_GLOBS, QualityConfig
from quality_gates.models import GateResult

DEFAULT_SKIP_GLOBS = DEFAULT_REVIEW_SKIP_GLOBS

DOC_SUFFIXES = (".md", ".rst", ".txt", ".adoc")
DOC_NAMES = {"license", "licence", "authors", "notice", "copying"}
RISKY_HINT = re.compile(
    r"\b(auth|token|secret|password|sql|permission|session|crypto|jwt|"
    r"oauth|saml|migration|exec\(|eval\(|pickle|innerHTML|child_process)\b",
    re.I,
)
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
    ".php",
    ".rb",
    ".kt",
    ".ex",
    ".tf",
    ".proto",
)

CHEAP_ANTHROPIC = "claude-haiku-4-5"
CHEAP_OPENAI = "gpt-4.1-mini"
FULL_ANTHROPIC = "claude-sonnet-4-6"
FULL_OPENAI = "gpt-4.1"


def glob_match(path: str, pattern: str) -> bool:
    """Match a repo-relative path against a glob, including `**/file` on a basename."""
    posix = path.replace("\\", "/").lstrip("./")
    pat = pattern.replace("\\", "/")
    if not posix or not pat:
        return False
    name = posix.rsplit("/", 1)[-1]
    if posix == pat.lstrip("./"):
        return True
    patterns = [pat]
    if pat.startswith("**/"):
        patterns.append(pat[3:])
    candidates = (posix, name)
    try:
        for candidate in candidates:
            node = PurePosixPath(candidate)
            for item in patterns:
                if node.match(item):
                    return True
    except ValueError:
        pass
    for candidate in candidates:
        for item in patterns:
            if fnmatch.fnmatch(candidate, item):
                return True
    if pat.endswith("/**"):
        root = pat[:-3]
        if root.startswith("**/"):
            root = root[3:]
        root = root.strip("/")
        if root and (
            posix == root or posix.startswith(root + "/") or f"/{root}/" in f"/{posix}/"
        ):
            return True
    return False


def path_skipped(path: str, globs: list[str]) -> bool:
    return any(glob_match(path, pattern) for pattern in globs)


def is_doc_path(path: str) -> bool:
    posix = path.replace("\\", "/").lstrip("./")
    name = Path(posix).name.lower()
    stem = Path(posix).stem.lower()
    if posix.endswith(DOC_SUFFIXES):
        return True
    return stem in DOC_NAMES or name in DOC_NAMES


def filter_diff(diff: str, skip_globs: list[str]) -> tuple[str, list[str]]:
    """Drop lockfile/generated file hunks from the LLM bundle."""
    from quality_gates.review.context import split_diff_files

    kept: list[str] = []
    skipped: list[str] = []
    parts: list[str] = []
    for path, body in split_diff_files(diff):
        if path_skipped(path, skip_globs):
            skipped.append(path)
            continue
        kept.append(path)
        parts.append(body if body.startswith("diff --git") else f"+++ b/{path}\n{body}")
    return "\n".join(parts), skipped


def classify_review_risk(
    paths: list[str],
    diff: str,
    prior: list[GateResult],
    config: QualityConfig,
) -> str:
    """Return skip | cheap | full. Explicit config.review_risk wins."""
    forced = (config.review_risk or "auto").lower()
    if forced in {"skip", "cheap", "full", "heuristic"}:
        return "skip" if forced == "heuristic" else forced
    globs = config.review_skip_globs or DEFAULT_SKIP_GLOBS
    remaining = [path for path in paths if not path_skipped(path, globs)]
    if not remaining:
        return "skip"
    if remaining and all(is_doc_path(path) for path in remaining):
        return "skip"
    if any(result.name == "security" and result.error_count() for result in prior):
        return "full"
    if any(result.name == "audit" and result.error_count() for result in prior):
        return "full"
    if RISKY_HINT.search(diff):
        return "full"
    source = [path for path in remaining if path.endswith(SOURCE_SUFFIXES)]
    added = sum(
        1
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    if len(source) >= 8 or added >= 400:
        return "full"
    return "cheap"


def select_review_model(config: QualityConfig, tier: str) -> str:
    """Pick a model id. An explicit quality.review.model pins every tier."""
    if (config.review_model or "").strip():
        return config.review_model.strip()
    provider = (config.review_provider or "auto").lower()
    anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if provider == "auto":
        provider = "anthropic" if anthropic else "openai"
    if tier == "full":
        if config.review_full_model:
            return config.review_full_model
        if provider == "anthropic":
            return os.environ.get("ANTHROPIC_MODEL") or FULL_ANTHROPIC
        return os.environ.get("OPENAI_MODEL") or FULL_OPENAI
    if config.review_cheap_model:
        return config.review_cheap_model
    if provider == "anthropic":
        return os.environ.get("ANTHROPIC_CHEAP_MODEL") or CHEAP_ANTHROPIC
    return os.environ.get("OPENAI_CHEAP_MODEL") or CHEAP_OPENAI
