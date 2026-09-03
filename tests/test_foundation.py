from __future__ import annotations

import json
from pathlib import Path

import pytest

from quality_gates.adapters import (
    ADAPTER_API_VERSION,
    AdapterContext,
    AdapterMetadata,
    BaseAdapter,
    discover_adapters,
)
from quality_gates.cli import main
from quality_gates.config import QualityConfig, load_config
from quality_gates.detect import detect_languages
from quality_gates.models import GateResult
from quality_gates.paths import bundled_file
from quality_gates.registry import (
    ALL_LANGUAGES,
    canonical_name,
    profiles_for_path,
    profiles_for_shebang,
)
from quality_gates.tool_manifest import load_tool_manifest


def test_registry_has_phase_one_languages_and_aliases() -> None:
    required = {
        "python",
        "javascript",
        "typescript",
        "java",
        "csharp",
        "c",
        "cpp",
        "go",
        "rust",
        "php",
        "ruby",
        "swift",
        "kotlin",
        "dart",
        "scala",
        "lua",
        "r",
        "matlab",
        "shell",
        "powershell",
        "sql",
    }
    assert required.issubset(ALL_LANGUAGES)
    assert canonical_name("C++") == "cpp"
    assert canonical_name("py") == "python"
    assert canonical_name("pwsh") == "powershell"


def test_exact_path_and_shebang_precedence(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: CI\n", encoding="utf-8")
    assert [item.id for item in profiles_for_path(workflow, tmp_path)] == [
        "github_actions"
    ]
    assert [item.id for item in profiles_for_shebang("#!/usr/bin/env python3")] == [
        "python"
    ]

    disguised = tmp_path / "task.js"
    disguised.write_text("#!/usr/bin/env python3\nprint('ok')\n", encoding="utf-8")
    info = detect_languages(tmp_path, QualityConfig())
    assert "python" in info["languages"]
    assert "javascript" not in info["languages"]


def test_ambiguous_c_headers_and_m_files_are_reported(tmp_path: Path) -> None:
    (tmp_path / "shared.h").write_text("int value;\n", encoding="utf-8")
    (tmp_path / "calculate.m").write_text(
        "function y = calculate()\nend\n", encoding="utf-8"
    )
    info = detect_languages(tmp_path, QualityConfig())
    assert "c" in info["languages"]
    assert "cpp" in info["languages"]
    assert "matlab" in info["languages"]
    assert info["ambiguities"] == [
        "calculate.m: matlab or objective-c",
        "shared.h: c or cpp",
    ]


def test_config_validation_and_bundled_schema(tmp_path: Path) -> None:
    (tmp_path / "quality.toml").write_text(
        "[quality]\nunknown_setting = true\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="unknown_setting"):
        load_config(tmp_path)
    schema = json.loads(bundled_file("quality.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["quality"]["additionalProperties"] is False


def test_pull_requests_default_to_untrusted_without_enabling_install(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    config = load_config(tmp_path)
    assert config.trust == "untrusted"
    assert config.should_auto_install() is False


def test_adapter_entry_point_contract(monkeypatch, tmp_path: Path) -> None:
    class ExampleAdapter(BaseAdapter):
        metadata = AdapterMetadata(
            name="example",
            languages=("python",),
            capabilities=("lint",),
            api_version=ADAPTER_API_VERSION,
        )

        def run(self, context: AdapterContext) -> GateResult:
            return GateResult(name=context.capability, status="pass")

    class EntryPoint:
        name = "example"

        @staticmethod
        def load():
            return ExampleAdapter

    monkeypatch.setattr(
        "quality_gates.adapters.adapter_entry_points", lambda: [EntryPoint()]
    )
    assert discover_adapters()["example"] is ExampleAdapter
    result = ExampleAdapter().run(
        AdapterContext(
            root=tmp_path,
            config=QualityConfig(),
            language="python",
            capability="lint",
        )
    )
    assert result.status == "pass"


def test_manifest_loader_has_explicit_install_and_checksum_metadata() -> None:
    manifest = load_tool_manifest()
    assert manifest.version == 1
    gitleaks = manifest.by_id()["gitleaks"]
    assert gitleaks.install_supported is False
    assert gitleaks.version == "8.24.3"
    assert gitleaks.artifacts[0].url.startswith("https://")
    assert gitleaks.artifacts[0].sha256 is None
    assert "SHA-256" in (gitleaks.install_reason or "")
    assert manifest.by_id()["python3"].install_supported is False


def test_doctor_json_reports_negotiation(tmp_path: Path, capsys, monkeypatch) -> None:
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    monkeypatch.delenv("GITHUB_REF", raising=False)
    monkeypatch.setattr("quality_gates.cli.which", lambda *_a, **_kw: None)
    code = main(["--json", "doctor"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["detected"]["languages"] == ["python"]
    assert payload["platform"]
    assert payload["cache"]
    assert payload["trust"] == "trusted"
    assert payload["offline"] is False
    assert "ruff" in {item["tool"] for item in payload["tools"]}
