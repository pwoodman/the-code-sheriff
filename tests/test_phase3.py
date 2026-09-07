from __future__ import annotations

import json
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from quality_gates.cli import main
from quality_gates.config import QualityConfig
from quality_gates.gates.dry import run_dry
from quality_gates.gates.lint import run_lint
from quality_gates.installers import _download
from quality_gates.models import Finding, GateResult
from quality_gates.report import (
    REPORT_SCHEMA_VERSION,
    render_junit,
    render_sarif,
    write_reports,
)
from quality_gates.result_cache import cached_result
from quality_gates.tool_manifest import ToolArtifact, ToolSpec, artifact_for_install


def test_cache_invalidates_content_config_and_tool_version(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "data.json"
    source.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("QUALITY_GATES_CACHE", str(tmp_path / "cache"))
    version = ["1.0"]
    monkeypatch.setattr(
        "quality_gates.result_cache._version", lambda *_args, **_kwargs: version[0]
    )
    calls = 0

    def compute() -> GateResult:
        nonlocal calls
        calls += 1
        return GateResult(name="lint", status="pass")

    config = QualityConfig(raw={"quality": {"jobs": 2}})
    args = (tmp_path, config, "json", "lint", (source,))
    cached_result(*args, tool="checker", compute=compute)
    assert (
        "cache hit" in cached_result(*args, tool="checker", compute=compute).notes[-1]
    )
    source.write_text('{"changed": true}\n', encoding="utf-8")
    cached_result(*args, tool="checker", compute=compute)
    config.raw["quality"]["jobs"] = 3
    cached_result(*args, tool="checker", compute=compute)
    version[0] = "2.0"
    cached_result(*args, tool="checker", compute=compute)
    assert calls == 4


def test_parallel_profiles_keep_deterministic_order(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "a.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "b.toml").write_text("x=1\n", encoding="utf-8")
    lock = threading.Lock()
    active = 0
    peak = 0

    def fake(_root, _config, profile, capability, _files, **_kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02 if profile == "json" else 0.01)
        with lock:
            active -= 1
        return GateResult(name=capability, status="pass", notes=[profile])

    monkeypatch.setattr("quality_gates.gates.lint.run_builtin_profile", fake)
    first = run_lint(tmp_path, QualityConfig(jobs=2), [])
    second = run_lint(tmp_path, QualityConfig(jobs=2), [])
    assert first.notes == second.notes
    assert peak <= 2
    assert peak > 1


def test_versioned_sarif_junit_and_bundled_reports(tmp_path: Path) -> None:
    result = GateResult(
        name="lint",
        status="fail",
        findings=[
            Finding(
                gate="lint",
                path="src/a.py",
                line=2,
                rule="E1",
                message="bad",
            )
        ],
    )
    directory = tmp_path / "reports"
    write_reports([result], directory)
    payload = json.loads((directory / "quality-report.json").read_text())
    assert payload["schema_version"] == REPORT_SCHEMA_VERSION
    assert payload["support"]["capability_coverage"]["lint"] == "fail"
    sarif = render_sarif([result])
    assert sarif["version"] == "2.1.0"
    assert (
        sarif["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"][
            "startLine"
        ]
        == 2
    )
    suite = ET.fromstring(render_junit([result]))
    assert suite.attrib["failures"] == "1"
    assert (directory / "quality-report.sarif").is_file()
    assert (directory / "quality-report.junit.xml").is_file()


def test_cache_commands_and_offline_install_rejection(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("QUALITY_GATES_CACHE", str(tmp_path / "cache"))
    assert main(["--root", str(tmp_path), "--json", "cache", "status"]) == 0
    assert json.loads(capsys.readouterr().out)["entries"] == 0
    (tmp_path / "quality.toml").write_text(
        "[quality]\noffline=true\n", encoding="utf-8"
    )
    assert main(["--root", str(tmp_path), "doctor", "--install"]) == 2
    assert "offline" in capsys.readouterr().err


def test_installer_requires_supported_platform_and_checksum(monkeypatch) -> None:
    spec = ToolSpec(
        id="example",
        version="1",
        commands=("example",),
        version_args=("--version",),
        license="MIT",
        platforms=("linux",),
        capabilities=("lint",),
        languages=("python",),
        file_kinds=(),
        install_supported=True,
        installer="archive",
        install_reason=None,
        cache_path=None,
        artifacts=(ToolArtifact("linux-x86_64", "https://example.invalid/tool", None),),
    )
    with pytest.raises(RuntimeError, match="SHA-256"):
        artifact_for_install(spec, system="linux", machine="x86_64")
    with pytest.raises(RuntimeError, match="no artifact"):
        artifact_for_install(
            ToolSpec(**{**spec.__dict__, "artifacts": ()}),
            system="windows",
            machine="x86_64",
        )
    called = False

    def network(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("quality_gates.installers.urlopen", network)
    with pytest.raises(RuntimeError, match="unverified"):
        _download("https://example.invalid/tool", Path("unused"))
    assert called is False


def test_release_metadata_schemas_and_wheel_includes() -> None:
    assert callable(run_dry)
    root = Path(__file__).parents[1]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert "https://github.com/pwoodman/the-code-sheriff" in pyproject
    assert '"tooling/js/package-lock.json"' in pyproject
    assert (root / ".github/workflows/release.yml").is_file()
    assert (root / ".github/workflows/sbom.yml").is_file()
    for name in ("report", "audit", "baseline"):
        schema = json.loads(
            (root / "configs" / f"{name}.schema.json").read_text(encoding="utf-8")
        )
        assert schema["$schema"].endswith("2020-12/schema")
        assert "schema_version" in schema["properties"]
