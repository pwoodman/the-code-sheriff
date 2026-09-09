from __future__ import annotations

from pathlib import Path

from quality_gates.config import QualityConfig, load_config
from quality_gates.findings_artifact import (
    load_last_findings,
    persist_last_findings,
    reconcile_last_findings,
)
from quality_gates.gates.regex import run_regex, scan_diff
from quality_gates.ignore import (
    IGNORE_FILE,
    append_ignore,
    apply_ignores,
    ignore_reason,
)
from quality_gates.models import Finding, GateResult
from quality_gates.review.incremental import added_hunks, new_hunks, unposted_findings
from quality_gates.review.parse import fingerprint
from quality_gates.review.routing import (
    classify_review_risk,
    filter_diff,
    glob_match,
    select_review_model,
)
from quality_gates.timing import accept_timings, compare_timings, parse_junit


def test_lockfile_diff_is_skip_risk() -> None:
    paths = ["package-lock.json"]
    diff = "+++ b/package-lock.json\n+  leftover\n"
    packed, skipped = filter_diff(diff, QualityConfig().review_skip_globs)
    assert skipped == ["package-lock.json"]
    assert packed.strip() == ""
    assert classify_review_risk(paths, diff, [], QualityConfig()) == "skip"
    assert glob_match("package-lock.json", "**/package-lock.json")
    assert glob_match("dist/app.js", "**/dist/**")
    assert glob_match("vendor/lib.py", "**/vendor/**")


def test_auth_diff_is_full_risk() -> None:
    paths = ["src/auth.py"]
    diff = "+++ b/src/auth.py\n+def login(token):\n+    return token\n"
    assert classify_review_risk(paths, diff, [], QualityConfig()) == "full"


def test_typical_feature_is_cheap_risk() -> None:
    paths = ["src/util.py"]
    diff = "+++ b/src/util.py\n+def add(a, b):\n+    return a + b\n"
    assert classify_review_risk(paths, diff, [], QualityConfig()) == "cheap"


def test_cheap_model_defaults_to_haiku(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_CHEAP_MODEL", raising=False)
    config = QualityConfig(review_provider="anthropic")
    assert "haiku" in select_review_model(config, "cheap")
    assert "sonnet" in select_review_model(config, "full")


def test_explicit_model_pins_every_tier() -> None:
    config = QualityConfig(review_model="custom-model")
    assert select_review_model(config, "cheap") == "custom-model"
    assert select_review_model(config, "full") == "custom-model"


def test_incremental_only_keeps_new_hunks() -> None:
    diff1 = "+++ b/app.py\n@@ -1,0 +1,1 @@\n+alpha\n"
    diff2 = "+++ b/app.py\n@@ -1,0 +1,2 @@\n+alpha\n+beta\n"
    first = added_hunks(diff1)
    second = added_hunks(diff2)
    fresh = new_hunks(second, first)
    assert fresh["app.py"]
    assert all("beta" in key or key.split(":")[0] == "2" for key in fresh["app.py"])


def test_unposted_findings_skip_previous_fingerprints() -> None:
    item = Finding(gate="review", rule="logic", path="app.py", line=3, message="bug")
    again = Finding(gate="review", rule="logic", path="app.py", line=3, message="bug")
    leftover = unposted_findings([again], [fingerprint(item, bucket=1)])
    assert leftover == []


def test_regex_flags_eval_in_diff() -> None:
    from quality_gates.gates.regex import _compiled_rules

    diff = (
        "diff --git a/src/app.py b/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1,0 +1,1 @@\n"
        "+value = eval(user_input)\n"
    )
    hits = scan_diff(diff, _compiled_rules(QualityConfig()), [])
    assert any(item.rule == "eval" for item in hits)


def test_regex_skips_detector_catalogs() -> None:
    from quality_gates.gates.regex import _compiled_rules

    diff = (
        "diff --git a/src/quality_gates/review/heuristic.py "
        "b/src/quality_gates/review/heuristic.py\n"
        "+++ b/src/quality_gates/review/heuristic.py\n"
        "@@ -1,0 +1,1 @@\n"
        '+(re.compile(r"\\beval\\s*\\("), "eval()")\n'
    )
    hits = scan_diff(diff, _compiled_rules(QualityConfig()), [])
    assert hits == []


def test_inline_ignore_drops_regex_hit(tmp_path: Path) -> None:
    src = tmp_path / "app.py"
    src.write_text("value = eval(user)  # quality:ignore eval\n", encoding="utf-8")
    finding = Finding(
        gate="regex",
        rule="eval",
        path="app.py",
        line=1,
        message="eval()",
        severity="error",
    )
    why = ignore_reason(tmp_path, finding, [])
    assert why is not None
    result = GateResult(name="regex", status="fail", findings=[finding])
    apply_ignores([result], tmp_path)
    assert result.status == "pass"
    assert result.findings == []


def test_ignore_file_roundtrip(tmp_path: Path) -> None:
    append_ignore(
        tmp_path,
        rule="missing-tests",
        path="src/generated.py",
        reason="generated client",
        owner="platform",
        days=30,
    )
    text = (tmp_path / IGNORE_FILE).read_text(encoding="utf-8")
    assert "missing-tests" in text
    finding = Finding(
        gate="test",
        rule="missing-tests",
        path="src/generated.py",
        message="need tests",
        severity="error",
    )
    result = GateResult(name="test", status="fail", findings=[finding])
    apply_ignores([result], tmp_path)
    assert result.status == "pass"


def test_last_findings_reopen_if_snippet_remains(tmp_path: Path) -> None:
    src = tmp_path / "app.py"
    src.write_text("value = eval(user)\n", encoding="utf-8")
    first = GateResult(
        name="regex",
        status="fail",
        findings=[
            Finding(
                gate="regex",
                rule="eval",
                path="app.py",
                line=1,
                message="eval()",
                severity="error",
                snippet="value = eval(user)",
            )
        ],
    )
    persist_last_findings(tmp_path, [first])
    later = GateResult(name="regex", status="pass", findings=[])
    leftover = reconcile_last_findings(tmp_path, [later])
    assert leftover
    assert leftover[0].rule == "eval"
    assert later.status == "fail"


def test_last_findings_clear_when_snippet_gone(tmp_path: Path) -> None:
    src = tmp_path / "app.py"
    src.write_text("value = int(user)\n", encoding="utf-8")
    first = GateResult(
        name="regex",
        status="fail",
        findings=[
            Finding(
                gate="regex",
                rule="eval",
                path="app.py",
                line=1,
                message="eval()",
                severity="error",
                snippet="value = eval(user)",
            )
        ],
    )
    persist_last_findings(tmp_path, [first])
    later = GateResult(name="regex", status="pass", findings=[])
    leftover = reconcile_last_findings(tmp_path, [later])
    assert leftover == []


def test_last_findings_merge_keeps_other_gates(tmp_path: Path) -> None:
    src = tmp_path / "app.py"
    src.write_text("value = eval(user)\n", encoding="utf-8")
    persist_last_findings(
        tmp_path,
        [
            GateResult(
                name="regex",
                status="fail",
                findings=[
                    Finding(
                        gate="regex",
                        rule="eval",
                        path="app.py",
                        line=1,
                        message="eval()",
                        severity="error",
                        snippet="value = eval(user)",
                    )
                ],
            ),
            GateResult(
                name="test",
                status="fail",
                findings=[
                    Finding(
                        gate="test",
                        rule="missing-tests",
                        path="app.py",
                        message="need tests",
                        severity="error",
                        snippet="value = eval(user)",
                    )
                ],
            ),
        ],
    )
    persist_last_findings(
        tmp_path, [GateResult(name="regex", status="pass", findings=[])]
    )
    rows = load_last_findings(tmp_path)
    assert any(row.get("gate") == "test" for row in rows)
    assert not any(row.get("gate") == "regex" for row in rows)
    later = GateResult(name="test", status="pass", findings=[])
    leftover = reconcile_last_findings(tmp_path, [later])
    assert leftover
    assert later.status == "fail"
    skipped = GateResult(name="lint", status="pass", findings=[])
    assert reconcile_last_findings(tmp_path, [skipped]) == []


def test_timing_regression_and_accept(tmp_path: Path) -> None:
    config = QualityConfig(test_timing_regression_pct=15, test_timing_min_delta_ms=1)
    compare_timings(
        tmp_path,
        config,
        current={"tests/test_app.py::test_ok": 0.10},
        touched={"tests/test_app.py::test_ok"},
    )
    findings, _payload = compare_timings(
        tmp_path,
        config,
        current={"tests/test_app.py::test_ok": 0.20},
        touched={"tests/test_app.py::test_ok"},
    )
    assert findings
    assert findings[0].rule == "timing-regression"
    again, _payload = compare_timings(
        tmp_path,
        config,
        current={"tests/test_app.py::test_ok": 0.20},
        touched={"tests/test_app.py::test_ok"},
    )
    assert again
    accept_timings(tmp_path, nodeids=["tests/test_app.py::test_ok"])
    findings, _payload = compare_timings(
        tmp_path,
        config,
        current={"tests/test_app.py::test_ok": 0.20},
        touched={"tests/test_app.py::test_ok"},
    )
    assert findings == []


def test_parse_junit_times(tmp_path: Path) -> None:
    xml = tmp_path / "junit.xml"
    xml.write_text(
        """
<testsuite>
  <testcase classname="tests.test_app" name="test_ok" time="0.042"/>
</testsuite>
""".strip(),
        encoding="utf-8",
    )
    parsed = parse_junit(xml)
    assert parsed["tests/test_app.py::test_ok"] == 0.042


def test_regex_gate_skips_when_disabled(tmp_path: Path) -> None:
    result = run_regex(tmp_path, QualityConfig(regex_enabled=False))
    assert result.status == "skip"


def test_loads_new_review_and_test_keys(tmp_path: Path) -> None:
    (tmp_path / "quality.toml").write_text(
        """
[quality.review]
risk = "cheap"
incremental = false
cheap_model = "haiku-local"
skip_globs = ["**/vendor/**"]

[quality.test]
require_for_source = false
timing_regression_pct = 20

[quality.regex]
include_defaults = false
[[quality.regex.rules]]
name = "todo-ban"
pattern = "TODO"
message = "no TODO"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config.review_risk == "cheap"
    assert config.review_incremental is False
    assert config.review_cheap_model == "haiku-local"
    assert config.test_require_for_source is False
    assert config.test_timing_regression_pct == 20
    assert config.regex_include_defaults is False
    assert config.regex_rules[0]["name"] == "todo-ban"
