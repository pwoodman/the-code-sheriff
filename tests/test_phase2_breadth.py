from __future__ import annotations

from pathlib import Path

import pytest

from quality_gates.adapters import (
    FORMAT_COMMANDS,
    LINT_COMMANDS,
    CommandTemplate,
    command_argv,
    run_builtin_profile,
)
from quality_gates.config import QualityConfig
from quality_gates.coverage_parse import (
    aggregate_summaries,
    parse_coverage_file,
)
from quality_gates.models import RunResult
from quality_gates.registry import (
    FILE_PROFILES,
    PROFILES,
    file_profiles_for,
    profiles_for_path,
)


def test_registry_metadata_is_truthful_and_specialized() -> None:
    assert PROFILES["toml"].tools["format"][0].name == "tombi"
    assert "compile" not in PROFILES["python"].capabilities
    assert "compile" not in PROFILES["php"].capabilities
    assert "style" in PROFILES["java"].capabilities
    assert PROFILES["zsh"].format_policy == "preserve"
    for kind in ("xml", "ini", "properties", "dotenv", "makefile", "batch"):
        assert "format" not in PROFILES[kind].capabilities
        assert "validate" in PROFILES[kind].capabilities


def test_file_profiles_for_scopes_single_programming_language() -> None:
    assert file_profiles_for(["javascript"]) == ()
    assert file_profiles_for(["python"]) == ()
    assert file_profiles_for([]) == FILE_PROFILES
    yaml_ids = {profile.id for profile in file_profiles_for(["yaml"])}
    assert yaml_ids == {"yaml"}
    auto = {profile.id for profile in file_profiles_for(["python", "javascript"])}
    assert "github_actions" in auto


def test_javascript_format_does_not_apply_github_actions_preserve(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.js").write_text("const x = 1;\n", encoding="utf-8")
    workflow = tmp_path / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: ci\non: push\njobs: {}\n", encoding="utf-8")
    from quality_gates.gates.format import run_format

    result = run_format(tmp_path, QualityConfig(), ["javascript"], check=True)
    assert all("GitHub Actions" not in note for note in result.notes)


def test_specialized_workflow_and_action_override_yaml(tmp_path: Path) -> None:
    workflow = tmp_path / ".github/workflows/ci.yml"
    action = tmp_path / ".github/actions/demo/action.yaml"
    workflow.parent.mkdir(parents=True)
    action.parent.mkdir(parents=True)
    assert [p.id for p in profiles_for_path(workflow, tmp_path)] == ["github_actions"]
    assert [p.id for p in profiles_for_path(action, tmp_path)] == ["github_actions"]


@pytest.mark.parametrize(
    ("kind", "name", "content"),
    [
        ("json", "space ü.json", b'\xef\xbb\xbf{"ok": true}\r\n'),
        ("toml", "space ü.toml", b'\xef\xbb\xbfkey = "value"\r\n'),
        ("xml", "space ü.xml", b"\xef\xbb\xbf<root><item /></root>\r\n"),
        ("ini", "space ü.ini", b"\xef\xbb\xbf[main]\r\nkey=value\r\n"),
        ("dotenv", ".env", b"\xef\xbb\xbfKEY=value\r\n"),
        ("properties", "space ü.properties", b"\xef\xbb\xbfkey=value\r\n"),
        ("batch", "space ü.cmd", b"\xef\xbb\xbf@echo off\r\ngoto :eof\r\n"),
    ],
)
def test_builtin_validators_accept_bom_crlf_and_do_not_mutate(
    tmp_path: Path, kind: str, name: str, content: bytes
) -> None:
    path = tmp_path / name
    path.write_bytes(content)
    result = run_builtin_profile(
        tmp_path, QualityConfig(), kind, "lint", (path,), check=True
    )
    assert result.status == "pass"
    assert path.read_bytes() == content


@pytest.mark.parametrize(
    ("kind", "name", "content"),
    [
        ("json", "bad.json", b"{"),
        ("toml", "bad.toml", b"a = "),
        ("xml", "bad.xml", b"<!DOCTYPE x SYSTEM 'https://example/x'><x/>"),
        ("ini", "bad.ini", b"[a]\nx=1\nx=2\n"),
        ("dotenv", ".env", b"A=1\nA=2\n"),
        ("properties", "bad.properties", b"bad=\\u12\n"),
    ],
)
def test_builtin_validators_report_malformed(
    tmp_path: Path, kind: str, name: str, content: bytes
) -> None:
    path = tmp_path / name
    path.write_bytes(content)
    result = run_builtin_profile(tmp_path, QualityConfig(), kind, "lint", (path,))
    assert result.status == "fail"
    assert result.findings


def test_batch_structural_diagnostics_are_conservative_warnings(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bad.cmd"
    path.write_bytes(b"goto nowhere\r\n")
    result = run_builtin_profile(tmp_path, QualityConfig(), "batch", "lint", (path,))
    assert result.status == "pass"
    assert result.warning_count() == 1


def test_external_success_preserves_warning_only_builtin_pass(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "warning.cmd"
    path.write_text("goto nowhere\n", encoding="utf-8")
    monkeypatch.setitem(LINT_COMMANDS, "batch", CommandTemplate("batch-linter", ()))
    monkeypatch.setattr(
        "quality_gates.adapters.which", lambda *_args, **_kwargs: "/tools/batch-linter"
    )
    monkeypatch.setattr(
        "quality_gates.adapters.run",
        lambda argv, **_kwargs: RunResult(argv=list(argv), returncode=0),
    )
    result = run_builtin_profile(tmp_path, QualityConfig(), "batch", "lint", (path,))
    assert result.status == "pass"
    assert result.warning_count() == 1


def test_command_templates_are_arrays_and_check_only(tmp_path: Path) -> None:
    path = tmp_path / "space ü.cpp"
    argv = command_argv(
        FORMAT_COMMANDS["cpp"], "/usr/bin/clang-format", (path,), check=True
    )
    assert argv == ["/usr/bin/clang-format", "--dry-run", "--Werror", str(path)]


def test_missing_external_tool_is_skip(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("quality_gates.adapters.which", lambda *_a, **_kw: None)
    path = tmp_path / "demo.lua"
    path.write_text("return 1\n", encoding="utf-8")
    result = run_builtin_profile(
        tmp_path, QualityConfig(), "lua", "format", (path,), check=True
    )
    assert result.status == "skip"
    assert result.skipped_tools == ["stylua"]


def test_coverage_aggregates_jacoco_and_lcov(tmp_path: Path) -> None:
    jacoco = tmp_path / "jacoco.xml"
    jacoco.write_text(
        '<report><counter type="LINE" missed="2" covered="8"/></report>',
        encoding="utf-8",
    )
    lcov = tmp_path / "lcov.info"
    lcov.write_text("LF:10\nLH:5\n", encoding="utf-8")
    summaries = [parse_coverage_file(jacoco), parse_coverage_file(lcov)]
    combined = aggregate_summaries([item for item in summaries if item is not None])
    assert combined is not None
    assert combined.lines_valid == 20
    assert combined.lines_covered == 13
    assert combined.line_percent == 65.0
