from __future__ import annotations

import subprocess
from pathlib import Path

from quality_gates.tools import run


def git_head(root: Path) -> str | None:
    result = run(["git", "rev-parse", "HEAD"], cwd=root, timeout=15)
    if result.returncode != 0 or result.skipped:
        return None
    sha = result.stdout.strip()
    return sha or None


def git_base_ref(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit
    import os

    base = os.environ.get("QUALITY_REVIEW_BASE")
    if base:
        return base
    github_base = os.environ.get("GITHUB_BASE_REF")
    if github_base:
        return f"origin/{github_base}"
    return None


def git_file_at(root: Path, ref: str, relpath: str) -> str | None:
    result = run(["git", "show", f"{ref}:{relpath}"], cwd=root, timeout=15)
    if result.returncode != 0 or result.skipped:
        return None
    return result.stdout


def git_changed_names(root: Path, base: str | None) -> list[str] | None:
    if not base:
        result = run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=root,
            timeout=15,
        )
        # unstaged + staged against HEAD; also include committed vs upstream if possible
        names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        upstream = run(
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
            cwd=root,
            timeout=15,
        )
        if upstream.returncode == 0 and upstream.stdout.strip():
            committed = run(
                ["git", "diff", "--name-only", f"{upstream.stdout.strip()}...HEAD"],
                cwd=root,
                timeout=15,
            )
            names.extend(
                line.strip() for line in committed.stdout.splitlines() if line.strip()
            )
        return sorted(set(names)) or None
    result = run(
        ["git", "diff", "--name-only", "--diff-filter=ACMRTUXB", f"{base}...HEAD"],
        cwd=root,
        timeout=15,
    )
    if result.returncode != 0:
        result = run(["git", "diff", "--name-only", base], cwd=root, timeout=15)
    if result.returncode != 0 or result.skipped:
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def git_commit_subjects(root: Path, base: str | None) -> list[str]:
    argv = ["git", "log", "--pretty=%s"]
    if base:
        argv.append(f"{base}..HEAD")
    else:
        argv.extend(["-n", "20"])
    result = run(argv, cwd=root, timeout=15)
    if result.returncode != 0 or result.skipped:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def git_is_repo(root: Path) -> bool:
    return (root / ".git").exists() or subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=root,
        capture_output=True,
        check=False,
    ).returncode == 0
