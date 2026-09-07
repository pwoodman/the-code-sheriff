from __future__ import annotations

import subprocess
from pathlib import Path

from quality_gates.cli import main
from quality_gates.github_app import CHECK_NAME
from quality_gates.onboard import (
    consumer_toml,
    github_repo_from_remote,
    resolve_pin,
    resolve_source,
    workflow_yaml,
)

PIN = "0123456789abcdef0123456789abcdef01234567"


def test_resolve_source_defaults_to_this_repo() -> None:
    assert resolve_source() == "pwoodman/poly-check"
    assert resolve_source(org="REPLACE_ORG") == "pwoodman/poly-check"
    assert resolve_source(org="acme") == "acme/poly-check"
    assert resolve_source(source="acme/gates") == "acme/gates"


def test_resolve_pin_keeps_explicit_sha() -> None:
    assert resolve_pin("pwoodman/poly-check", PIN) == PIN


def test_consumer_defaults_are_adopt_and_local() -> None:
    text = consumer_toml()
    assert 'policy = "adopt"' in text
    assert 'mode = "local"' in text
    assert "The Code Sheriff" in text


def test_init_writes_pinned_workflow(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr("quality_gates.onboard.resolve_pin", lambda *a, **k: PIN)
    code = main(["--root", str(tmp_path), "init", "--no-require-check"])
    assert code == 0
    out = capsys.readouterr().out
    assert "wrote" in out
    toml = (tmp_path / "quality.toml").read_text(encoding="utf-8")
    assert 'policy = "adopt"' in toml
    workflow = (tmp_path / ".github" / "workflows" / "quality.yml").read_text(
        encoding="utf-8"
    )
    assert CHECK_NAME in workflow
    assert PIN in workflow
    assert "REPLACE_FULL_COMMIT_SHA" not in workflow
    assert not (tmp_path / ".github" / "workflows" / "quality-cli.yml").exists()


def test_init_rewrites_placeholder_workflow(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("quality_gates.onboard.resolve_pin", lambda *a, **k: PIN)
    path = tmp_path / ".github" / "workflows" / "quality.yml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "uses: pwoodman/poly-check/.github/workflows/quality.yml@REPLACE_FULL_COMMIT_SHA\n",
        encoding="utf-8",
    )
    assert main(["--root", str(tmp_path), "init"]) == 0
    text = path.read_text(encoding="utf-8")
    assert PIN in text
    assert "REPLACE_FULL_COMMIT_SHA" not in text


def test_setup_tries_required_check(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr("quality_gates.onboard.resolve_pin", lambda *a, **k: PIN)
    monkeypatch.setattr(
        "quality_gates.onboard.enable_required_check",
        lambda *a, **k: "required The Code Sheriff",
    )
    from quality_gates.onboard import init_repo

    assert init_repo(tmp_path, require_check=True) == 0
    assert "required The Code Sheriff" in capsys.readouterr().out
    assert (tmp_path / "quality.toml").is_file()


def test_github_repo_from_ssh_remote(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "remote",
            "add",
            "origin",
            "git@github.com:acme/app.git",
        ],
        check=True,
    )
    assert github_repo_from_remote(tmp_path) == ("acme", "app")


def test_setup_writes_hooks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("quality_gates.onboard.resolve_pin", lambda *a, **k: PIN)
    monkeypatch.setattr(
        "quality_gates.onboard.install_git_hooks",
        lambda *a, **k: "skipped hook install",
    )
    from quality_gates.onboard import init_repo

    assert init_repo(tmp_path, hooks=True) == 0
    text = (tmp_path / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert PIN in text
    assert "quality-format" in text


def test_init_does_not_write_hooks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("quality_gates.onboard.resolve_pin", lambda *a, **k: PIN)
    assert main(["--root", str(tmp_path), "init", "--no-require-check"]) == 0
    assert not (tmp_path / ".pre-commit-config.yaml").exists()


def test_workflow_yaml_names_the_check() -> None:
    text = workflow_yaml("pwoodman/poly-check", PIN)
    assert f"name: {CHECK_NAME}" in text
    assert f"@{PIN}" in text
