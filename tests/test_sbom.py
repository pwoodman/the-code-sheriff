from __future__ import annotations

from pathlib import Path

from quality_gates.cli import main
from quality_gates.sbom import inventory_components, write_sbom


def test_write_sbom_from_package_manifest(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("quality_gates.sbom.which", lambda *_a, **_k: None)
    (tmp_path / "package.json").write_text(
        '{"name":"demo","dependencies":{"left-pad":"1.3.0"}}\n',
        encoding="utf-8",
    )
    payload = write_sbom(tmp_path)
    cdx = tmp_path / ".quality-reports" / "sbom.cdx.json"
    spdx = tmp_path / ".quality-reports" / "sbom.spdx.json"
    assert cdx.is_file()
    assert spdx.is_file()
    assert payload["components"] >= 1
    names = {item["name"] for item in inventory_components(tmp_path)}
    assert "left-pad" in names


def test_sbom_cli_json(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr("quality_gates.sbom.which", lambda *_a, **_k: None)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = ["ruff>=0.8"]\n',
        encoding="utf-8",
    )
    code = main(["--root", str(tmp_path), "--json", "sbom"])
    assert code == 0
    out = capsys.readouterr().out
    assert "cyclonedx" in out
    assert "spdx" in out
