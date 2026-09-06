import subprocess
from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.gates.contract import run_contract


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_contract_gate_blocks_removed_required_schema_field(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    schema = tmp_path / "user.schema.json"
    schema.write_text(
        '{"required":["id","email"],"properties":{"id":{},"email":{}}}',
        encoding="utf-8",
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    schema.write_text(
        '{"required":["id"],"properties":{"id":{},"email":{}}}', encoding="utf-8"
    )

    result = run_contract(tmp_path, QualityConfig(), base="HEAD")

    assert result.status == "fail"
    assert result.findings[0].rule == "required-field-removed"


def test_contract_gate_blocks_removed_property_and_type_change(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    schema = tmp_path / "api.schema.json"
    schema.write_text(
        '{"properties":{"count":{"type":"integer"},"name":{"type":"string"}}}',
        encoding="utf-8",
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    # count type changed to string, name removed
    schema.write_text('{"properties":{"count":{"type":"string"}}}', encoding="utf-8")

    result = run_contract(tmp_path, QualityConfig(), base="HEAD")

    assert result.status == "fail"
    rules = {f.rule for f in result.findings}
    assert "field-removed" in rules
    assert "type-changed" in rules
