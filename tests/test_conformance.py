from __future__ import annotations

from pathlib import Path

import pytest

from quality_gates.adapters import run_builtin_profile
from quality_gates.config import QualityConfig
from quality_gates.gates.lint import run_lint

FIXTURES = Path(__file__).parent / "fixtures" / "conformance"


@pytest.mark.parametrize(
    ("kind", "suffix"),
    [
        ("json", ".json"),
        ("protobuf", ".proto"),
        ("graphql", ".graphql"),
    ],
)
def test_builtin_conformance_good_passes_and_bad_fails(
    tmp_path: Path, kind: str, suffix: str
) -> None:
    source = FIXTURES / kind
    good = tmp_path / f"good{suffix}"
    bad = tmp_path / f"bad{suffix}"
    good.write_bytes((source / f"good{suffix}").read_bytes())
    bad.write_bytes((source / f"bad{suffix}").read_bytes())
    ok = run_builtin_profile(tmp_path, QualityConfig(), kind, "lint", (good,))
    fail = run_builtin_profile(tmp_path, QualityConfig(), kind, "lint", (bad,))
    assert ok.status == "pass"
    assert fail.status == "fail"
    assert fail.findings


def test_missing_language_tool_is_skip_not_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setattr("quality_gates.gates.common.which", lambda *_a, **_k: None)
    result = run_lint(tmp_path, QualityConfig(), ["python"])
    assert result.status in {"skip", "unsupported"}
    assert result.status != "pass"
    assert result.exit_state in {"skipped", "unsupported", "not-applicable"}
