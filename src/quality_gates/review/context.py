"""Diff, related files, prior-gate digest, and custom-rule packing for review."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.detect import iter_project_files
from quality_gates.gitutil import git_base_ref, git_changed_names
from quality_gates.impact_graph import build_graph, is_source
from quality_gates.models import GateResult
from quality_gates.review.diffscan import iter_new_file_lines
from quality_gates.review.rules import ReviewRule, load_review_rules, rules_for_paths
from quality_gates.tools import run

SKIP_PRIOR = frozenset({"format", "lint", "review"})
BINARY_HINT = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def collect_diff(root: Path, base: str | None, limit: int) -> str:
    base_ref = base or os.environ.get("QUALITY_REVIEW_BASE") or git_base_ref()
    if not base_ref:
        result = run(["git", "diff", "HEAD~1"], cwd=root)
        text = result.stdout
    else:
        result = run(
            ["git", "diff", "--diff-filter=ACMRTUXB", f"{base_ref}...HEAD"], cwd=root
        )
        text = result.stdout
        if result.returncode != 0 or not text.strip():
            result = run(["git", "diff", base_ref], cwd=root)
            text = result.stdout
    return compact_diff(text, limit)


def compact_diff(diff: str, limit: int) -> str:
    packed, _reviewed, _unreviewed = partition_review_units(diff, limit)
    return packed


def partition_review_units(diff: str, limit: int) -> tuple[str, list[str], list[str]]:
    """Partition diff into budgeted units, returning (packed_diff, reviewed_units, unreviewed_units)."""
    if len(diff) <= limit:
        files = split_diff_files(diff)
        return diff, [p for p, _ in files], []
    files = split_diff_files(diff)
    if not files:
        return diff[:limit] + "\n\n[diff truncated]\n", [], []
    budget = max(500, limit // max(1, len(files)))
    reviewed: list[str] = []
    unreviewed: list[str] = []
    header = f"[diff compacted: {len(files)} files, {len(diff)} bytes originally]"
    parts = [header]
    current_size = len(header)
    for path, body in files:
        chunk = body if len(body) <= budget else body[:budget] + "\n[file truncated]\n"
        entry = f"+++ b/{path}\n{chunk}"
        if not reviewed or (current_size + len(entry) <= limit):
            parts.append(entry)
            reviewed.append(path)
            current_size += len(entry)
        else:
            unreviewed.append(path)
    if unreviewed:
        parts.append(
            f"\n[diff truncated: {len(unreviewed)} unreviewed file(s) exceed budget: {', '.join(unreviewed[:3])}]\n"
        )
    packed = "\n".join(parts)
    return packed, reviewed, unreviewed


def split_diff_files(diff: str) -> list[tuple[str, str]]:
    files: list[tuple[str, str]] = []
    current: str | None = None
    chunks: list[str] = []
    for line in diff.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current is not None:
                files.append((current, "".join(chunks)))
            current = None
            chunks = [line]
            continue
        if line.startswith("+++ b/"):
            current = line[6:].strip()
        chunks.append(line)
    if current is not None or chunks:
        files.append((current or "(unknown)", "".join(chunks)))
    return [(path, body) for path, body in files if path and path != "/dev/null"]


def changed_paths(diff: str) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for path, _body in split_diff_files(diff):
        posix = path.replace("\\", "/").lstrip("./")
        if posix in seen:
            continue
        seen.add(posix)
        paths.append(posix)
    return paths


def new_side_lines(diff: str) -> dict[str, set[int]]:
    lines: dict[str, set[int]] = {}
    for path, new_line, _kind, _text in iter_new_file_lines(diff):
        lines.setdefault(path, set()).add(new_line)
    return lines


def related_files(
    root: Path,
    config: QualityConfig,
    paths: list[str],
) -> list[tuple[str, str]]:
    neighbors = _neighbors(root, config, paths)
    budget = max(4000, config.review_related_bytes)
    per_file = max(
        1200, budget // max(1, min(len(neighbors) or 1, config.review_related_files))
    )
    packed: list[tuple[str, str]] = []
    used = 0
    for rel in neighbors[: config.review_related_files]:
        text = read_repo_file(root, rel, limit=per_file)
        if text is None:
            continue
        packed.append((rel, text))
        used += len(text)
        if used >= budget:
            break
    return packed


def prior_digest(prior: list[GateResult], *, limit: int = 40) -> str:
    lines: list[str] = []
    count = 0
    for result in prior:
        if result.name in SKIP_PRIOR:
            continue
        hits = [
            item for item in result.findings if item.severity in {"error", "warning"}
        ]
        if not hits and result.status in {"pass", "skip"}:
            continue
        lines.append(f"### {result.name} ({result.status})")
        for item in hits[:12]:
            loc = f"{item.path or 'repo'}:{item.line or '-'}"
            lines.append(f"- [{item.severity}] {loc} {item.message}")
            count += 1
            if count >= limit:
                return "\n".join(lines)
        if result.notes:
            lines.append(f"- notes: {result.notes[0]}")
    return "\n".join(lines) if lines else "- none"


def load_report_json(root: Path, name: str) -> dict[str, object] | None:
    path = root / ".quality-reports" / name
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def impact_digest(root: Path) -> str:
    data = load_report_json(root, "impact.json")
    if not data:
        return ""
    lines = ["### impact.json"]
    changed = data.get("changed") or []
    if isinstance(changed, list) and changed:
        lines.append("changed: " + ", ".join(str(item) for item in changed[:12]))
    downstream = data.get("downstream") or {}
    if isinstance(downstream, dict):
        for src, consumers in list(downstream.items())[:8]:
            if consumers:
                lines.append(
                    f"downstream of {src}: " + ", ".join(map(str, consumers[:6]))
                )
    unvalidated = data.get("unvalidated_downstream") or []
    if isinstance(unvalidated, list) and unvalidated:
        lines.append(f"unvalidated downstream: {len(unvalidated)}")
    return "\n".join(lines)


def audit_digest(root: Path, *, limit: int = 12) -> str:
    data = load_report_json(root, "audit.json")
    if not data:
        return ""
    findings = data.get("findings") or []
    if not isinstance(findings, list) or not findings:
        return ""
    lines = ["### audit.json HIGH findings"]
    for item in findings[:limit]:
        if not isinstance(item, dict):
            continue
        loc = f"{item.get('path') or 'repo'}:{item.get('line') or '-'}"
        title = item.get("title") or item.get("finding") or "finding"
        lines.append(f"- P{item.get('priority', '')} {loc} {title}")
    return "\n".join(lines)


def render_rules(rules: list[ReviewRule]) -> str:
    if not rules:
        return "- none"
    blocks = []
    for rule in rules:
        scope = ", ".join(rule.paths) if rule.paths else "(all paths)"
        blocks.append(f"### {rule.name} ({rule.severity}, {scope})\n{rule.body}")
    return "\n\n".join(blocks)


def active_rules(
    root: Path, config: QualityConfig, paths: list[str]
) -> list[ReviewRule]:
    return rules_for_paths(load_review_rules(root, config), paths)


def read_repo_file(root: Path, rel: str, *, limit: int) -> str | None:
    path = safe_repo_path(root, rel)
    if path is None:
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:8000]:
        return None
    text = data.decode("utf-8", errors="replace")
    if BINARY_HINT.search(text[:2000]):
        return None
    if len(text) > limit:
        text = text[:limit] + "\n[truncated]\n"
    return text


def safe_repo_path(root: Path, rel: str) -> Path | None:
    posix = rel.replace("\\", "/").lstrip("/")
    if not posix or posix.startswith(".git/") or ".." in Path(posix).parts:
        return None
    candidate = (root / posix).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def grep_repo(
    root: Path,
    config: QualityConfig,
    pattern: str,
    *,
    glob: str = "*",
    limit: int = 20,
) -> list[str]:
    try:
        regex = re.compile(pattern)
    except re.error:
        return [f"invalid pattern: {pattern}"]
    hits: list[str] = []
    scanned = 0
    for path in iter_project_files(root, config):
        scanned += 1
        if scanned > 400:
            break
        rel = path.relative_to(root).as_posix()
        if glob != "*" and not _fnmatch(rel, glob):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for index, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                hits.append(f"{rel}:{index}: {line.strip()[:200]}")
                if len(hits) >= limit:
                    return hits
    return hits


def _fnmatch(path: str, glob: str) -> bool:
    import fnmatch

    return fnmatch.fnmatch(path, glob) or fnmatch.fnmatch(Path(path).name, glob)


def _neighbors(root: Path, config: QualityConfig, paths: list[str]) -> list[str]:
    report = load_report_json(root, "impact.json")
    found: list[str] = []
    seen: set[str] = set(paths)
    if report:
        for key in ("upstream", "downstream", "tests"):
            mapping = report.get(key) or {}
            if not isinstance(mapping, dict):
                continue
            for src in paths:
                for item in mapping.get(src) or []:
                    posix = str(item).replace("\\", "/")
                    if posix in seen:
                        continue
                    seen.add(posix)
                    found.append(posix)
        if found:
            return found
    try:
        graph = build_graph(root, config)
    except (OSError, ValueError):
        return []
    for src in paths:
        if not is_source(src):
            continue
        for other in sorted(
            graph.imports.get(src, ()) | graph.imported_by.get(src, ())
        ):
            if other in seen:
                continue
            seen.add(other)
            found.append(other)
    if not found:
        names = git_changed_names(root, git_base_ref()) or []
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            found.append(name)
    return found
