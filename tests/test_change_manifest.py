import subprocess
from pathlib import Path

from quality_gates.change_manifest import discover_changes


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_manifest_includes_renames_deletions_and_untracked_files(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "old.py").write_text("old\n", encoding="utf-8")
    (tmp_path / "gone.py").write_text("gone\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "initial")
    _git(tmp_path, "mv", "old.py", "new.py")
    (tmp_path / "gone.py").unlink()
    (tmp_path / "untracked.py").write_text("new\n", encoding="utf-8")

    manifest = discover_changes(tmp_path, "HEAD")

    assert manifest.state == "available"
    assert {(item.kind, item.path, item.old_path) for item in manifest.changes} >= {
        ("renamed", "new.py", "old.py"),
        ("deleted", "gone.py", None),
        ("untracked", "untracked.py", None),
    }


def test_manifest_reports_unknown_explicit_base(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "initial")

    manifest = discover_changes(tmp_path, "does-not-exist")

    assert manifest.state == "unknown"
