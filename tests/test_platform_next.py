from __future__ import annotations

import json
import subprocess
from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.detect import detect_languages, discover_workspaces
from quality_gates.evidence import snapshot_digest
from quality_gates.gates.compile import run_compile
from quality_gates.gates.contract import run_contract
from quality_gates.gates.security import run_security
from quality_gates.models import Finding, GateResult
from quality_gates.report import filter_new_findings, write_reports
from quality_gates.review.llm import resolve_client
from quality_gates.watch import snapshot


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_elixir_is_detected_and_matlab_is_not(tmp_path: Path) -> None:
    (tmp_path / "lib.ex").write_text("defmodule Lib do\nend\n", encoding="utf-8")
    (tmp_path / "mix.exs").write_text(
        "defmodule Demo.MixProject do\nend\n", encoding="utf-8"
    )
    (tmp_path / "legacy.m").write_text("x = 1;\n", encoding="utf-8")
    info = detect_languages(tmp_path, QualityConfig())
    assert "elixir" in info["languages"]
    assert "matlab" not in info["languages"]
    languages = {item.language for item in discover_workspaces(tmp_path)}
    assert "elixir" in languages


def test_proto_contract_flags_removed_message(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    proto = tmp_path / "user.proto"
    proto.write_text(
        'syntax = "proto3";\nmessage User {\n  string name = 1;\n}\n',
        encoding="utf-8",
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    proto.write_text('syntax = "proto3";\n', encoding="utf-8")
    result = run_contract(tmp_path, QualityConfig(), base="HEAD")
    assert result.status == "fail"
    assert "type-removed" in {item.rule for item in result.findings}


def test_license_allow_list_is_optional(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    monkeypatch.setattr("quality_gates.gates.security.which", lambda *_a, **_k: None)
    result = run_security(tmp_path, QualityConfig(), ["python"])
    assert "license allow-list unset" in " ".join(result.notes)
    assert not any(item.rule == "license-not-allowed" for item in result.findings)


def test_report_history_diagnostics_and_diff(tmp_path: Path) -> None:
    older = GateResult(
        name="lint",
        status="fail",
        findings=[Finding(gate="lint", rule="X", path="a.py", message="old")],
        duration_ms=1,
    )
    newer = GateResult(
        name="lint",
        status="fail",
        findings=[
            Finding(gate="lint", rule="X", path="a.py", message="old"),
            Finding(gate="lint", rule="Y", path="b.py", message="new"),
        ],
        duration_ms=2,
    )
    reports = tmp_path / ".quality-reports"
    write_reports([older], reports, policy="enforce")
    write_reports([newer], reports, policy="enforce")
    assert (reports / "quality-report.prev.json").is_file()
    history = json.loads((reports / "history.json").read_text(encoding="utf-8"))
    assert len(history) == 2
    diagnostics = json.loads((reports / "diagnostics.json").read_text(encoding="utf-8"))
    assert diagnostics["diagnostics"]
    added = filter_new_findings(newer.findings, older.findings)
    assert [item.message for item in added] == ["new"]


def test_watch_snapshot_changes_with_mtime(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    path.write_text("VALUE = 1\n", encoding="utf-8")
    before = snapshot(tmp_path, QualityConfig())
    # Different length so Windows filesystems that keep the same mtime still
    # change the snapshot via size.
    path.write_text("VALUE = 2\n# changed\n", encoding="utf-8")
    after = snapshot(tmp_path, QualityConfig())
    assert before != after


def test_ollama_resolve_uses_compat_client(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client = resolve_client(QualityConfig(review_provider="ollama"))
    assert client is not None
    assert client.name == "ollama"
    assert "/v1/chat/completions" in client.url


def test_cmake_without_tool_skips(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "CMakeLists.txt").write_text("project(demo)\n", encoding="utf-8")
    (tmp_path / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    monkeypatch.setattr("quality_gates.gates.compile.which", lambda *_a, **_k: None)
    result = run_compile(
        tmp_path,
        QualityConfig(),
        ["c"],
        security=GateResult(name="security", status="pass"),
    )
    assert result.status in {"skip", "unsupported"}
    assert result.status != "pass"


def test_snapshot_digest_is_stable_until_edit(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    first = snapshot_digest(tmp_path)
    second = snapshot_digest(tmp_path)
    assert first == second
    (tmp_path / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert snapshot_digest(tmp_path) != first
