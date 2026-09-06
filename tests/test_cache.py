from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.result_cache import cache_key


def test_cache_key_changes_when_only_tool_configuration_changes(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    config = tmp_path / "ruff.toml"
    config.write_text("line-length = 88\n", encoding="utf-8")
    options = QualityConfig()

    first = cache_key(tmp_path, options, "python", "lint", (source,), tool=None)
    config.write_text("line-length = 100\n", encoding="utf-8")
    second = cache_key(tmp_path, options, "python", "lint", (source,), tool=None)

    assert first != second
