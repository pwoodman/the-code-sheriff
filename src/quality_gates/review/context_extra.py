"""CODEOWNERS, issues, ADRs, lockfiles, CI triage, docs drift, history."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from quality_gates.models import Finding

_OWNER_LINE = re.compile(r"^(?P<pattern>\S+)\s+(?P<owners>.+)$")
_ISSUE = re.compile(r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", re.I)
_UNPINNED = re.compile(
    r"""["'](?:latest|\*)["']|:\s*["'](?:latest|\*)["']|=\s*["'](?:latest|\*)["']"""
)


def parse_codeowners(root: Path) -> list[tuple[str, list[str]]]:
    for rel in ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS"):
        path = root / rel
        if not path.is_file():
            continue
        rules: list[tuple[str, list[str]]] = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            match = _OWNER_LINE.match(line)
            if not match:
                continue
            owners = [
                item for item in match.group("owners").split() if item.startswith("@")
            ]
            rules.append((match.group("pattern"), owners))
        return rules
    return []


def owners_for(paths: list[str], rules: list[tuple[str, list[str]]]) -> list[str]:
    found: list[str] = []
    for path in paths:
        posix = path.replace("\\", "/")
        for pattern, owners in rules:
            if _glob(posix, pattern):
                found.extend(owners)
    return list(dict.fromkeys(found))


def _glob(path: str, pattern: str) -> bool:
    from fnmatch import fnmatch

    if pattern.endswith("/"):
        return (
            path.startswith(pattern.lstrip("/"))
            or f"/{pattern.strip('/')}/" in f"/{path}/"
        )
    return fnmatch(path, pattern.lstrip("/")) or fnmatch(
        path.rsplit("/", 1)[-1], pattern
    )


def linked_issues(title: str, body: str = "") -> list[str]:
    return list(dict.fromkeys(_ISSUE.findall(f"{title}\n{body}")))


def load_adrs(root: Path) -> list[dict[str, str]]:
    docs: list[dict[str, str]] = []
    for folder in (root / "docs" / "adr", root / "adr", root / "docs" / "architecture"):
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md")):
            text = path.read_text(encoding="utf-8")[:4000]
            docs.append({"path": path.relative_to(root).as_posix(), "body": text})
    return docs


def adr_conflicts(
    adrs: list[dict[str, str]], paths: list[str], diff: str
) -> list[Finding]:
    findings: list[Finding] = []
    hay = ("\n".join(paths) + "\n" + diff).lower()
    for adr in adrs:
        body = adr["body"]
        if "MUST NOT" in body or "do not" in body.lower():
            title = body.splitlines()[0][:80] if body else adr["path"]
            if any(token.lower() in hay for token in _keywords(body)[:6]):
                findings.append(
                    Finding(
                        gate="review",
                        rule="adr-conflict",
                        severity="warning",
                        path=adr["path"],
                        message=f"Change may conflict with ADR: {title}",
                        reason="Documented architecture decision appears related to this diff.",
                        suggestion="Confirm the ADR still applies or record a superseding decision.",
                        confidence="MEDIUM",
                    )
                )
    return findings


def _keywords(body: str) -> list[str]:
    return [
        word
        for word in re.findall(r"[A-Za-z]{5,}", body)
        if word.lower() not in {"shall", "must", "should"}
    ]


def review_lockfiles(root: Path, paths: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    lockish = [
        path
        for path in paths
        if path.endswith(
            (
                "package.json",
                "requirements.txt",
                "pyproject.toml",
                "go.mod",
                "Cargo.toml",
            )
        )
    ]
    for rel in lockish:
        path = root / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if _UNPINNED.search(text):
            findings.append(
                Finding(
                    gate="packages",
                    rule="unpinned-dependency",
                    severity="warning",
                    path=rel,
                    message="Dependency appears unpinned (latest, *, or >=).",
                    reason="Unpinned versions hide supply-chain drift from review.",
                    suggestion="Pin a concrete version or a lockfile-resolved digest.",
                    confidence="HIGH",
                )
            )
    return findings


def triage_ci_failures(
    checks: list[dict[str, Any]],
    paths: list[str],
) -> dict[str, Any]:
    failed = [
        item
        for item in checks
        if str(item.get("conclusion") or item.get("status") or "").lower()
        in {"failure", "timed_out", "cancelled"}
    ]
    likely = []
    joined = " ".join(paths).lower()
    for item in failed:
        name = str(item.get("name") or "check")
        log = str(item.get("output") or item.get("summary") or "")
        hit = next((path for path in paths if path in log), "")
        likely.append(
            {
                "check": name,
                "path": hit
                or (
                    paths[0]
                    if paths and any(part in joined for part in name.lower().split())
                    else ""
                ),
                "next": f"Inspect `{name}` logs and the changed files, then re-run the check.",
                "excerpt": log[:400],
            }
        )
    return {
        "failed": len(failed),
        "items": likely,
        "summary": (
            f"{len(failed)} CI check(s) failed"
            if failed
            else "No failed checks on this SHA"
        ),
    }


def docs_drift(paths: list[str]) -> list[Finding]:
    source = [
        path
        for path in paths
        if path.endswith((".py", ".ts", ".go", ".rs", ".java", ".cs"))
        and "/test" not in path.lower()
    ]
    docs = [
        path
        for path in paths
        if path.endswith((".md", ".rst")) or path.startswith("docs/")
    ]
    if source and not docs:
        return [
            Finding(
                gate="review",
                rule="docs-drift",
                severity="info",
                path=source[0],
                message="Source changed without a docs/README/changelog update.",
                reason="User-facing or operator docs often drift after behavior changes.",
                suggestion="Update README, docs, examples, or the changelog if behavior is user-visible.",
                confidence="MEDIUM",
            )
        ]
    return []


def suggest_reviewers(owners: list[str], authors: list[str]) -> list[str]:
    return list(dict.fromkeys([*owners, *authors]))[:8]


def similar_history(
    entries: list[dict[str, Any]], paths: list[str]
) -> list[dict[str, Any]]:
    needles = {path.split("/")[-1] for path in paths}
    hits = []
    for item in entries:
        item_paths = {str(path).split("/")[-1] for path in item.get("paths") or []}
        if needles & item_paths:
            hits.append(item)
        if len(hits) >= 5:
            break
    return hits


def write_json(root: Path, name: str, payload: Any) -> Path:
    reports = root / ".quality-reports"
    reports.mkdir(parents=True, exist_ok=True)
    path = reports / name
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
