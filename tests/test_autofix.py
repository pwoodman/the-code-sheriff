from __future__ import annotations

from pathlib import Path

from quality_gates.autofix import run_autofix
from quality_gates.certificate import build_certificate, render_certificate
from quality_gates.cli import main
from quality_gates.config import QualityConfig


def test_autofix_formats_python(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("x=1\n", encoding="utf-8")
    payload = run_autofix(tmp_path, QualityConfig(), apply_patches=False)
    assert payload["applied"]
    assert payload["next"] == "quality oracle --run"


def test_certify_cli_without_reports(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    code = main(["--json", "certify"])
    assert code == 1
    out = capsys.readouterr().out
    assert "blocked" in out or "ready" in out


def test_certificate_markdown_blocked() -> None:
    text = render_certificate(
        build_certificate({"green": False, "blocking": [{"gate": "lint"}]})
    )
    assert "BLOCKED" in text
    assert "Do not auto-merge" in text
