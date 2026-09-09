"""Read-only merge preview via `git merge-tree`. Never touches the working tree."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from quality_gates.gitutil import git_base_ref
from quality_gates.tools import run

_OID = re.compile(r"^[0-9a-f]{40,}$")
_STAGE = re.compile(r"^[0-7]{6}\s+[0-9a-f]+\s+[123]\t(.+)$")
_CONFLICT_FILE = re.compile(
    r"CONFLICT \((?P<kind>[^)]+)\):.*?(?:Merge conflict in |in )?(?P<path>\S+)",
    re.I,
)


@dataclass
class MergePreview:
    ours: str
    theirs: str
    tree: str = ""
    clean: bool = False
    files: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    kinds: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    using_stash_commit: bool = False


def resolve_theirs(root: Path, explicit: str | None = None, configured: str = "") -> str | None:
    if explicit:
        return explicit if _rev_ok(root, explicit) else None
    if configured.strip() and _rev_ok(root, configured.strip()):
        return configured.strip()
    env = git_base_ref()
    if env and _rev_ok(root, env):
        return env
    for candidate in ("origin/main", "origin/master", "main", "master"):
        if _rev_ok(root, candidate):
            return candidate
    return None


def resolve_ours(root: Path) -> tuple[str, bool]:
    """HEAD, or a `git stash create` commit when the working tree is dirty."""
    head = _rev_parse(root, "HEAD")
    if not head:
        return "", False
    status = run(["git", "status", "--porcelain"], cwd=root, timeout=15)
    if status.returncode != 0 or not status.stdout.strip():
        return head, False
    stash = run(["git", "stash", "create"], cwd=root, timeout=30)
    oid = stash.stdout.strip()
    if stash.returncode == 0 and _OID.match(oid):
        return oid, True
    return head, False


def preview(root: Path, ours: str, theirs: str) -> MergePreview:
    result = run(
        [
            "git",
            "merge-tree",
            "--write-tree",
            "--name-only",
            "--messages",
            ours,
            theirs,
        ],
        cwd=root,
        timeout=60,
    )
    if result.skipped:
        return MergePreview(ours=ours, theirs=theirs, error="git is unavailable")
    if result.returncode not in {0, 1}:
        stderr = (result.stderr or result.stdout or "").strip()
        if "unknown option" in stderr.lower() or "merge-tree" in stderr.lower():
            return MergePreview(
                ours=ours,
                theirs=theirs,
                error="git merge-tree --write-tree needs Git 2.38+",
            )
        return MergePreview(
            ours=ours,
            theirs=theirs,
            error=stderr[:400] or f"merge-tree exited {result.returncode}",
        )
    parsed = parse_merge_tree(result.stdout, result.returncode)
    parsed.ours = ours
    parsed.theirs = theirs
    return parsed


def parse_merge_tree(stdout: str, returncode: int) -> MergePreview:
    tree = ""
    files: list[str] = []
    messages: list[str] = []
    kinds: dict[str, str] = {}
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        if not tree and _OID.match(line):
            tree = line
            continue
        stage = _STAGE.match(raw.rstrip())
        if stage:
            path = stage.group(1).strip().strip('"')
            if path and path not in files:
                files.append(path)
            continue
        if line.lower().startswith("auto-merging "):
            continue
        match = _CONFLICT_FILE.search(line)
        if match:
            path = match.group("path").strip().strip("\"'`")
            kind = match.group("kind").strip()
            messages.append(line)
            if path:
                kinds[path] = kind
                if path not in files:
                    files.append(path)
            continue
        if "CONFLICT" in line.upper():
            messages.append(line)
            continue
        name_only = returncode == 1 and not line.lower().startswith("warning:")
        if (
            name_only
            and ("/" in line or ("." in line and " " not in line))
            and line not in files
            and not _OID.match(line)
        ):
            files.append(line)
    unique = list(dict.fromkeys(files))
    return MergePreview(
        ours="",
        theirs="",
        tree=tree,
        clean=returncode == 0,
        files=unique,
        messages=messages,
        kinds=kinds,
    )


def same_commit(root: Path, left: str, right: str) -> bool:
    a = _rev_parse(root, left)
    b = _rev_parse(root, right)
    return bool(a and b and a == b)


def current_branch(root: Path) -> str:
    result = run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root, timeout=15
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def untracked_names(root: Path) -> list[str]:
    result = run(
        ["git", "ls-files", "-o", "--exclude-standard"], cwd=root, timeout=15
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def materialize_tree(
    root: Path, tree: str, ours: str, theirs: str, dest: Path
) -> str | None:
    """Create a detached worktree for the merge tree. Returns the commit SHA."""
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "The Code Sheriff")
    env.setdefault("GIT_AUTHOR_EMAIL", "sheriff@localhost")
    env.setdefault("GIT_COMMITTER_NAME", "The Code Sheriff")
    env.setdefault("GIT_COMMITTER_EMAIL", "sheriff@localhost")
    commit = run(
        [
            "git",
            "commit-tree",
            tree,
            "-p",
            ours,
            "-p",
            theirs,
            "-m",
            "the-code-sheriff dry-merge preview",
        ],
        cwd=root,
        timeout=30,
    )
    sha = commit.stdout.strip()
    if commit.returncode != 0 or not _OID.match(sha):
        return None
    if dest.exists():
        run(
            ["git", "worktree", "remove", "--force", str(dest)],
            cwd=root,
            timeout=30,
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    added = run(
        ["git", "worktree", "add", "--detach", str(dest), sha],
        cwd=root,
        timeout=60,
    )
    if added.returncode != 0:
        return None
    return sha


def remove_worktree(root: Path, dest: Path) -> None:
    run(
        ["git", "worktree", "remove", "--force", str(dest)],
        cwd=root,
        timeout=60,
    )


def _rev_ok(root: Path, rev: str) -> bool:
    return _rev_parse(root, rev) is not None


def _rev_parse(root: Path, rev: str) -> str | None:
    result = run(["git", "rev-parse", "--verify", rev], cwd=root, timeout=15)
    oid = result.stdout.strip()
    if result.returncode != 0 or not _OID.match(oid):
        return None
    return oid
