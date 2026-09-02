from __future__ import annotations

from pathlib import Path

from quality_gates.config import load_config
from quality_gates.gates.review import _heuristic_review


def test_loads_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    assert config.languages == ["auto"]
    assert "lint" in config.fail_on
    assert config.sql_dialect == "ansi"


def test_loads_overrides(tmp_path: Path) -> None:
    (tmp_path / "quality.toml").write_text(
        """
[quality]
fail_on = ["lint"]
ai_review = "never"

[quality.sql]
dialect = "postgres"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config.fail_on == ["lint"]
    assert config.ai_review == "never"
    assert config.sql_dialect == "postgres"


def test_heuristic_review_flags_eval_and_missing_tests() -> None:
    diff = """
diff --git a/src/app.py b/src/app.py
+++ b/src/app.py
@@ -1,2 +1,4 @@
+value = eval(user_input)
+count = count + 1
 def main():
     return 1
""".lstrip()
    findings = _heuristic_review(diff, ["python"], [])
    rules = {item.rule for item in findings}
    assert "unsafe-api" in rules
    assert "missing-tests" in rules
