from __future__ import annotations

from pathlib import Path

from quality_gates.config import load_config
from quality_gates.gates.version import discover_versions, run_version
from quality_gates.semver import parse_semver


def test_discovers_pyproject_and_dunder(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "1.2.3"\n',
        encoding="utf-8",
    )
    pkg = tmp_path / "src" / "demo"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text('__version__ = "1.2.3"\n', encoding="utf-8")
    hits = discover_versions(tmp_path, load_config(tmp_path))
    values = {hit.value for hit in hits}
    assert values == {"1.2.3"}
    kinds = {hit.kind for hit in hits}
    assert "pyproject" in kinds
    assert "dunder" in kinds


def test_inconsistent_versions_fail(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "1.0.0"\n',
        encoding="utf-8",
    )
    (tmp_path / "__init__.py").write_text('__version__ = "1.0.1"\n', encoding="utf-8")
    result = run_version(tmp_path, load_config(tmp_path))
    assert result.status == "fail"
    assert any(item.rule == "consistent" for item in result.findings)


def test_non_semver_fails(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text("next\n", encoding="utf-8")
    result = run_version(tmp_path, load_config(tmp_path))
    assert result.status == "fail"
    assert parse_semver("next") is None


def test_binary_file_does_not_crash_version_discovery(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "1.0.0"\n',
        encoding="utf-8",
    )
    (tmp_path / "VERSION").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 80)
    hits = discover_versions(tmp_path, load_config(tmp_path))
    assert {hit.value for hit in hits} == {"1.0.0"}
