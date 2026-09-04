from __future__ import annotations

import json
from pathlib import Path

from quality_gates.config import QualityConfig, load_config
from quality_gates.github_comment import post_review
from quality_gates.mcp_server import handle
from quality_gates.models import Finding, GateResult
from quality_gates.oracle import remaining_from_results, render_prompt
from quality_gates.review.engine import run_review
from quality_gates.review.heuristic import heuristic_review
from quality_gates.review.llm import ChatTurn, run_llm_review
from quality_gates.review.parse import (
    drop_style_nits,
    findings_from_payload,
    majority_vote,
    parse_json_object,
)
from quality_gates.review.resolve import resolution_stats
from quality_gates.review.rules import load_review_rules, rules_for_paths

EVAL_DIFF = (
    Path(__file__).parent / "fixtures/review_bench/eval_injection.diff"
).read_text(encoding="utf-8")


class ScriptedClient:
    name = "scripted"

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls = 0

    def complete(
        self,
        messages: list[ChatTurn],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2400,
    ) -> str:
        self.calls += 1
        if not self.replies:
            return '{"action":"submit","summary":"empty","findings":[]}'
        return self.replies.pop(0)


def test_heuristic_review_flags_eval_and_missing_tests() -> None:
    findings = heuristic_review(EVAL_DIFF, ["python"], [])
    rules = {item.rule for item in findings}
    assert "unsafe-api" in rules
    assert "missing-tests" in rules


def test_heuristic_skips_detector_docs_and_fixtures() -> None:
    diff = """
diff --git a/src/quality_gates/review/heuristic.py b/src/quality_gates/review/heuristic.py
+++ b/src/quality_gates/review/heuristic.py
@@ -1,0 +1,3 @@
+(re.compile(r"\\beval\\s*\\("), "eval() on untrusted input")
+(re.compile(r"new Function\\s*\\("), "new Function() is eval")
+shell=True
diff --git a/standards/AI_REVIEW.md b/standards/AI_REVIEW.md
+++ b/standards/AI_REVIEW.md
@@ -1,0 +1,1 @@
+Mention eval() in the review contract.
diff --git a/tests/test_app.py b/tests/test_app.py
+++ b/tests/test_app.py
@@ -1,0 +1,1 @@
+value = eval(user_input)
""".lstrip()
    findings = heuristic_review(diff, ["python"], [])
    assert [item.rule for item in findings if item.rule == "unsafe-api"] == []


def test_large_pr_counts_production_source_not_tests_or_docs() -> None:
    source_lines = "\n".join(f"+x = {i}" for i in range(800))
    test_lines = "\n".join(f"+assert {i}" for i in range(400))
    diff = f"""
diff --git a/src/app.py b/src/app.py
+++ b/src/app.py
@@ -0,0 +1,800 @@
{source_lines}
diff --git a/tests/test_app.py b/tests/test_app.py
+++ b/tests/test_app.py
@@ -0,0 +1,400 @@
{test_lines}
diff --git a/README.md b/README.md
+++ b/README.md
@@ -0,0 +1,2 @@
+# title
+docs
""".lstrip()
    findings = heuristic_review(diff, ["python"], [])
    rules = {item.rule for item in findings}
    assert "large-pr" in rules
    message = next(item.message for item in findings if item.rule == "large-pr")
    assert "800 production source lines" in message

    small = """
diff --git a/tests/test_app.py b/tests/test_app.py
+++ b/tests/test_app.py
@@ -0,0 +1,900 @@
""" + "\n".join(f"+assert {i}" for i in range(900))
    assert "large-pr" not in {
        item.rule for item in heuristic_review(small.lstrip(), ["python"], [])
    }


def test_review_bench_fixture_matches_expected_rules() -> None:
    meta = json.loads(
        (Path(__file__).parent / "fixtures/review_bench/eval_injection.json").read_text(
            encoding="utf-8"
        )
    )
    findings = heuristic_review(EVAL_DIFF, meta["languages"], [])
    rules = {item.rule for item in findings}
    assert set(meta["expected_rules"]) <= rules


def test_loads_scoped_markdown_rules(tmp_path: Path) -> None:
    rules_dir = tmp_path / ".quality" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "no-eval.md").write_text(
        '---\nname: no-eval\npaths:\n  - "**/*.py"\nseverity: error\n---\nNo eval.\n',
        encoding="utf-8",
    )
    (rules_dir / "js-only.md").write_text(
        '---\npaths: ["**/*.ts"]\n---\nTypeScript invariant.\n',
        encoding="utf-8",
    )
    config = QualityConfig()
    rules = load_review_rules(tmp_path, config)
    assert {rule.name for rule in rules} == {"no-eval", "js-only"}
    active = rules_for_paths(rules, ["src/app.py"])
    assert [rule.name for rule in active] == ["no-eval"]


def test_parse_json_findings_and_majority_vote() -> None:
    text = """```json
{"action":"submit","summary":"bug","findings":[
  {"severity":"error","path":"a.py","line":4,"rule":"logic","message":"off-by-one"}
]}
```"""
    payload = parse_json_object(text)
    assert payload is not None
    summary, findings = findings_from_payload(payload)
    assert summary == "bug"
    assert findings[0].rule == "logic"
    other = Finding(
        gate="review",
        severity="error",
        path="a.py",
        line=6,
        rule="logic",
        message="off-by-one in loop",
    )
    noise = Finding(
        gate="review",
        severity="warning",
        path="a.py",
        line=20,
        rule="style",
        message="use prettier",
    )
    kept = majority_vote([[findings[0], noise], [other], [findings[0]]])
    rules = {item.rule for item in kept}
    assert "logic" in rules
    assert "style" not in rules


def test_drop_style_nits_and_unknown_paths() -> None:
    findings = [
        Finding(
            gate="review",
            severity="warning",
            path="a.py",
            line=1,
            rule="format",
            message="run prettier",
        ),
        Finding(
            gate="review",
            severity="error",
            path="secret.py",
            line=2,
            rule="logic",
            message="nil deref",
        ),
        Finding(
            gate="review",
            severity="error",
            path="a.py",
            line=3,
            rule="logic",
            message="nil deref",
        ),
    ]
    kept = drop_style_nits(findings, allowed_paths={"a.py"})
    assert len(kept) == 1
    assert kept[0].path == "a.py"


def test_resolution_rate_counts_fixed_findings() -> None:
    previous = {
        "findings": [
            {
                "path": "a.py",
                "line": 1,
                "rule": "unsafe-api",
                "message": "eval",
                "severity": "error",
            },
            {
                "path": "b.py",
                "line": 2,
                "rule": "logic",
                "message": "bug",
                "severity": "error",
            },
        ]
    }
    current = [
        Finding(
            gate="review",
            path="b.py",
            line=2,
            rule="logic",
            message="bug",
            severity="error",
        )
    ]
    stats = resolution_stats(previous, current)
    assert stats["previous"] == 2
    assert stats["resolved"] == 1
    assert stats["remaining"] == 1
    assert stats["rate"] == 0.5


def test_run_review_heuristic_writes_reports(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "quality_gates.review.engine.collect_diff", lambda *_a, **_k: EVAL_DIFF
    )
    monkeypatch.setattr(
        "quality_gates.review.engine.resolve_client", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "quality_gates.review.engine.related_files", lambda *_a, **_k: []
    )
    config = QualityConfig(
        review_provider="off", review_mode="heuristic", ai_review="always"
    )
    result = run_review(tmp_path, config, ["python"], base="HEAD", post=False)
    assert result.status == "pass"
    payload = json.loads(
        (tmp_path / ".quality-reports" / "review.json").read_text(encoding="utf-8")
    )
    rules = {item["rule"] for item in payload["findings"]}
    assert "unsafe-api" in rules
    assert payload["provider"] == "heuristic"


def test_agentic_loop_fulfills_need_then_submits(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    client = ScriptedClient(
        [
            '{"action":"need","files":["mod.py"],"findings":[]}',
            '{"action":"submit","summary":"ok","findings":[{"severity":"warning","path":"mod.py","line":1,"rule":"logic","message":"magic number"}]}',
        ]
    )
    config = QualityConfig(review_tool_rounds=2, review_related_bytes=8000)
    summary, findings, mode = run_llm_review(
        client, "review this", mode="agentic", config=config, root=tmp_path, diff=""
    )
    assert mode == "agentic"
    assert summary == "ok"
    assert findings[0].path == "mod.py"
    assert client.calls == 2


def test_oracle_prompt_lists_blockers() -> None:
    results = [
        GateResult(
            name="lint",
            status="fail",
            findings=[
                Finding(
                    gate="lint",
                    rule="E001",
                    path="a.py",
                    line=3,
                    message="bad",
                    severity="error",
                )
            ],
        )
    ]
    payload = remaining_from_results(results)
    assert payload["green"] is False
    prompt = render_prompt(payload)
    assert "a.py:3" in prompt
    assert "quality oracle --run" in prompt


def test_mcp_lists_and_calls_oracle(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("quality_gates.mcp_server._root", lambda: tmp_path)
    listed = handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, runner=lambda _a: 0
    )
    assert listed is not None
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert names == {"quality_oracle", "quality_run", "quality_review"}
    called = handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "quality_oracle", "arguments": {}},
        },
        runner=lambda _a: 0,
    )
    assert called is not None
    text = called["result"]["content"][0]["text"]
    payload = json.loads(text)
    assert "green" in payload


def test_post_review_writes_inline_and_check_run(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    payloads: list[dict] = []

    def fake_request(
        method: str, url: str, token: str, payload: dict
    ) -> tuple[int, dict]:
        calls.append((method, url))
        payloads.append(payload)
        return 201, {"id": 1}

    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/app")
    monkeypatch.setenv("QUALITY_PR_NUMBER", "7")
    monkeypatch.setenv("QUALITY_HEAD_SHA", "abc123")
    monkeypatch.setattr("quality_gates.github_comment._request", fake_request)
    findings = [
        Finding(
            gate="review",
            severity="error",
            path="src/app.py",
            line=4,
            rule="unsafe-api",
            message="eval",
        ),
        Finding(
            gate="review",
            severity="error",
            path="standards/AI_REVIEW.md",
            line=12,
            rule="unsafe-api",
            message="eval() mentioned in docs",
        ),
    ]
    notes = post_review(
        "body",
        findings,
        diff_lines={"src/app.py": {4}, "standards/AI_REVIEW.md": {12}},
        inline=True,
        check_run=True,
    )
    review = next(item for item in payloads if item.get("comments") is not None)
    assert [item["path"] for item in review["comments"]] == ["src/app.py"]
    assert any("reviews" in url for _method, url in calls)
    assert any("check-runs" in url for _method, url in calls)
    assert any("inline" in note for note in notes)


def test_config_loads_review_mode(tmp_path: Path) -> None:
    (tmp_path / "quality.toml").write_text(
        '[quality.review]\nmode = "ensemble"\npasses = 4\nvalidate = false\n',
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config.review_mode == "ensemble"
    assert config.review_passes == 4
    assert config.review_validate is False


def test_compact_diff_keeps_file_list() -> None:
    from quality_gates.review.context import changed_paths, compact_diff, new_side_lines

    huge = EVAL_DIFF + ("+" + ("x" * 80) + "\n") * 50
    packed = compact_diff(huge, 800)
    assert "src/app.py" in packed
    assert changed_paths(EVAL_DIFF) == ["src/app.py"]
    lines = new_side_lines(EVAL_DIFF)
    assert 4 in lines["src/app.py"]


def test_review_skips_when_disabled(tmp_path: Path) -> None:
    config = QualityConfig(ai_review="never")
    result = run_review(tmp_path, config, ["python"], base="HEAD", post=False)
    assert result.status == "skip"


def test_oracle_cli_json(tmp_path: Path, capsys, monkeypatch) -> None:
    from quality_gates.cli import main

    monkeypatch.chdir(tmp_path)
    code = main(["--json", "oracle"])
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["green"] is False
    assert "oracle --run" in payload["next"]
