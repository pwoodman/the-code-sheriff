from __future__ import annotations

import json
from pathlib import Path

from quality_gates.diagnostics import enrich_findings
from quality_gates.github_comment import _inline_body
from quality_gates.models import Finding
from quality_gates.review.apply import apply_finding
from quality_gates.review.bench import (
    bundled_bench_dir,
    load_cases,
    run_heuristic_suite,
)
from quality_gates.review.contract import (
    agent_prompt,
    finding_payload,
    suggestion_fence,
)
from quality_gates.review.external_eval import (
    macroscope_reconstructed,
    score_against_goldens,
)
from quality_gates.review.heuristic import heuristic_review


def test_reviewbench_heuristic_suite_meets_bar() -> None:
    cases = load_cases(bundled_bench_dir())
    positives = [item for item in cases if item.kind == "positive" and item.heuristic]
    negatives = [item for item in cases if item.kind == "hard_negative"]
    assert len(positives) >= 15
    assert len(negatives) >= 8
    scorecard = run_heuristic_suite(bundled_bench_dir())
    assert scorecard["failed"] == []
    assert scorecard["recall"] == 1.0
    assert scorecard["hard_negative_pass"] == 1.0


def test_finding_contract_and_github_suggestion() -> None:
    findings = enrich_findings(
        heuristic_review(
            (bundled_bench_dir() / "eval_injection.diff").read_text(encoding="utf-8"),
            ["python"],
            [],
        )
    )
    unsafe = next(item for item in findings if item.rule == "unsafe-api")
    assert unsafe.reason
    assert unsafe.suggestion
    assert unsafe.verify == "quality review"
    payload = finding_payload(unsafe)
    assert payload["id"]
    assert "eval" in agent_prompt(unsafe).lower()
    unsafe.patch = "value = ast.literal_eval(user_input)"
    body = _inline_body(unsafe)
    assert "```suggestion" in body
    assert "quality oracle --prompt" in body
    assert suggestion_fence(unsafe)


def test_closed_loop_apply_clears_eval(tmp_path: Path) -> None:
    dest = tmp_path / "src"
    dest.mkdir()
    app = dest / "app.py"
    app.write_text(
        "value = eval(user_input)\ncount = count + 1\ndef main():\n    return 1\n",
        encoding="utf-8",
    )
    finding = Finding(
        gate="review",
        message="eval",
        path="src/app.py",
        line=1,
        rule="unsafe-api",
        patch="count = count + 1",
    )
    status = apply_finding(tmp_path, finding)
    assert status.startswith("applied")
    text = app.read_text(encoding="utf-8")
    assert "eval(" not in text
    assert "count = count + 1" in text


def test_macroscope_sample_is_documented() -> None:
    info = macroscope_reconstructed()
    assert info["public_json"] is False
    assert "commons-math" in info["sample"]["repository"]
    gcd = bundled_bench_dir() / "macroscope_gcd_overflow.diff"
    assert "u * v == 0" in gcd.read_text(encoding="utf-8")


def test_martian_lexical_judge() -> None:
    goldens = [
        {"comment": "eval() on untrusted input executes attacker code"},
        {"comment": "missing authorization check on the new route"},
    ]
    findings = [{"message": "eval() on untrusted input is a code-injection risk"}]
    score = score_against_goldens(findings, goldens)
    assert score["matched"] >= 1
    assert score["goldens"] == 2


def test_eval_cli_reviewbench(capsys) -> None:
    from quality_gates.cli import main

    code = main(["eval", "--suite", "reviewbench"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["reviewbench"]["failed"] == []
