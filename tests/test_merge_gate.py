from __future__ import annotations

import subprocess
from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.gates.merge import run_merge
from quality_gates.merge_tree import parse_merge_tree


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _repo(root: Path) -> None:
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")


def test_parse_merge_tree_clean() -> None:
    oid = "a" * 40
    parsed = parse_merge_tree(f"{oid}\n", 0)
    assert parsed.clean is True
    assert parsed.tree == oid
    assert parsed.files == []


def test_parse_merge_tree_conflict_messages() -> None:
    oid = "b" * 40
    stdout = (
        f"{oid}\n"
        "CONFLICT (content): Merge conflict in src/app.py\n"
        "src/app.py\n"
    )
    parsed = parse_merge_tree(stdout, 1)
    assert parsed.clean is False
    assert parsed.tree == oid
    assert parsed.files == ["src/app.py"]
    assert parsed.kinds["src/app.py"] == "content"


def test_merge_gate_skips_when_head_is_the_base(tmp_path: Path) -> None:
    _repo(tmp_path)
    (tmp_path / "readme.txt").write_text("ok\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    result = run_merge(
        tmp_path, QualityConfig(merge_verify="never"), base="main"
    )
    assert result.status == "skip"
    assert "already" in " ".join(result.notes)


def test_merge_gate_fails_textual_conflict(tmp_path: Path) -> None:
    _repo(tmp_path)
    target = tmp_path / "app.py"
    target.write_text("value = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "checkout", "-qb", "feature")
    target.write_text("value = 2\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "feature")
    _git(tmp_path, "checkout", "-q", "main")
    target.write_text("value = 3\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "main-side")
    _git(tmp_path, "checkout", "-q", "feature")

    result = run_merge(
        tmp_path, QualityConfig(merge_verify="never"), base="main"
    )
    assert result.status == "fail"
    assert any(item.rule == "textual-conflict" for item in result.findings)
    assert (tmp_path / ".quality-reports" / "merge.json").is_file()
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    dirty = [
        line
        for line in status.stdout.splitlines()
        if line.strip() and not line.startswith("??")
    ]
    assert dirty == []


def test_merge_gate_passes_clean_textual_merge(tmp_path: Path) -> None:
    _repo(tmp_path)
    (tmp_path / "keep.py").write_text("KEEP = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "checkout", "-qb", "feature")
    (tmp_path / "feature.py").write_text("FEATURE = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "feature")
    _git(tmp_path, "checkout", "-q", "main")
    (tmp_path / "main.py").write_text("MAIN = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "main-side")
    _git(tmp_path, "checkout", "-q", "feature")

    result = run_merge(
        tmp_path, QualityConfig(merge_verify="never"), base="main"
    )
    assert result.status == "pass"
    assert not result.findings
    assert any("clean textual merge" in note for note in result.notes)
