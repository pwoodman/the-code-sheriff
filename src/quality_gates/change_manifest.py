"""One immutable description of the repository snapshot under assessment."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Change:
    kind: str
    path: str
    old_path: str | None = None
    hunks: tuple[ChangedHunk, ...] = ()


@dataclass(frozen=True)
class ChangedHunk:
    path: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int


@dataclass(frozen=True)
class ChangeManifest:
    state: str
    base: str | None
    target: str | None
    target_tree: str | None
    working_tree_digest: str
    changes: tuple[Change, ...]
    diff: str = ""
    reason: str | None = None

    @property
    def paths(self) -> list[str]:
        return [item.path for item in self.changes]

    @property
    def hunks(self) -> tuple[ChangedHunk, ...]:
        return tuple(hunk for change in self.changes for hunk in change.hunks)

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "changes": [asdict(item) for item in self.changes],
        }

    def write(self, root: Path) -> Path:
        report = root / ".quality-reports" / "change-manifest.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        return report


def discover_changes(root: Path, base: str | None = None) -> ChangeManifest:
    target = _git(root, "rev-parse", "HEAD")
    if target is None:
        return ChangeManifest(
            state="unknown",
            base=base,
            target=None,
            target_tree=None,
            working_tree_digest=_working_digest(root),
            changes=(),
            reason="Git repository or HEAD is unavailable",
        )
    target_tree = _git(root, "rev-parse", "HEAD^{tree}")
    resolved_base = base or _default_base(root, target)
    if base and _git(root, "rev-parse", "--verify", base) is None:
        return ChangeManifest(
            state="unknown",
            base=base,
            target=target,
            target_tree=target_tree,
            working_tree_digest=_working_digest(root),
            changes=(),
            reason=f"comparison base {base!r} cannot be resolved",
        )
    rows: dict[tuple[str, str | None], Change] = {}
    if resolved_base:
        status = _git(root, "diff", "--name-status", "-M", f"{resolved_base}...HEAD")
        if status is None:
            status = _git(root, "diff", "--name-status", "-M", resolved_base)
        if status is None:
            return ChangeManifest(
                state="unknown",
                base=resolved_base,
                target=target,
                target_tree=target_tree,
                working_tree_digest=_working_digest(root),
                changes=(),
                reason="Git diff discovery failed",
            )
        _collect_status(rows, status)
        diff = _git(root, "diff", "--find-renames", f"{resolved_base}...HEAD") or ""
    else:
        # First commits have no parent; compare the commit root to the empty tree.
        status = (
            _git(
                root,
                "diff-tree",
                "--root",
                "--no-commit-id",
                "--name-status",
                "-r",
                "-M",
                "HEAD",
            )
            or ""
        )
        _collect_status(rows, status)
        diff = (
            _git(
                root,
                "diff-tree",
                "--root",
                "--no-commit-id",
                "-r",
                "--find-renames",
                "HEAD",
            )
            or ""
        )
    work_status = _git(root, "diff", "--name-status", "-M", "HEAD") or ""
    _collect_status(rows, work_status)
    # The assessment snapshot includes staged and unstaged edits as well as the
    # base-to-HEAD comparison. Keep their diff evidence beside the same manifest
    # so review, impact, and reporting cannot silently assess different trees.
    working_diff = _git(root, "diff", "--find-renames", "HEAD") or ""
    if working_diff:
        diff = "\n".join(part for part in (diff, working_diff) if part)
    for path in (
        _git(root, "ls-files", "--others", "--exclude-standard") or ""
    ).splitlines():
        if path.strip():
            rows[(path.strip(), None)] = Change("untracked", path.strip())
    hunks = _parse_hunks(diff)
    enriched = tuple(
        Change(
            change.kind, change.path, change.old_path, tuple(hunks.get(change.path, ()))
        )
        for change in rows.values()
    )
    return ChangeManifest(
        state="empty" if not rows else "available",
        base=resolved_base,
        target=target,
        target_tree=target_tree,
        working_tree_digest=_working_digest(root),
        changes=tuple(
            sorted(enriched, key=lambda item: (item.path, item.old_path or ""))
        ),
        diff=diff,
    )


def _collect_status(rows: dict[tuple[str, str | None], Change], text: str) -> None:
    for row in text.splitlines():
        parts = row.split("\t")
        if len(parts) < 2:
            continue
        code = parts[0][:1]
        kind = {
            "A": "added",
            "D": "deleted",
            "M": "modified",
            "R": "renamed",
            "C": "copied",
        }.get(code, "modified")
        if kind in {"renamed", "copied"} and len(parts) >= 3:
            old, path = parts[1], parts[2]
            rows[(path, old)] = Change(kind, path, old)
        else:
            rows[(parts[1], None)] = Change(kind, parts[1])


_HUNK = re.compile(
    r"^@@ -(?P<old>\d+)(?:,(?P<old_count>\d+))? \+(?P<new>\d+)(?:,(?P<new_count>\d+))? @@"
)


def _parse_hunks(diff: str) -> dict[str, list[ChangedHunk]]:
    """Parse unified diff headers without treating diff text as executable input."""
    output: dict[str, list[ChangedHunk]] = {}
    current: str | None = None
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            continue
        match = _HUNK.match(line)
        if not current or not match:
            continue
        output.setdefault(current, []).append(
            ChangedHunk(
                current,
                int(match["old"]),
                int(match["old_count"] or 1),
                int(match["new"]),
                int(match["new_count"] or 1),
            )
        )
    return output


def _default_base(root: Path, target: str) -> str | None:
    upstream = _git(
        root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"
    )
    if upstream:
        return upstream
    parent = _git(root, "rev-parse", f"{target}~1")
    return parent


def _git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _working_digest(root: Path) -> str:
    digest = hashlib.sha256()
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all") or ""
    digest.update(status.encode("utf-8"))
    for row in status.splitlines():
        path = row[3:].split(" -> ")[-1]
        candidate = root / path
        if candidate.is_file():
            digest.update(path.encode("utf-8"))
            digest.update(hashlib.sha256(candidate.read_bytes()).digest())
    return digest.hexdigest()
