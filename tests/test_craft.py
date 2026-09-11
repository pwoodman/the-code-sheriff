from __future__ import annotations

from pathlib import Path

from quality_gates.audit.craft import scan_craft
from quality_gates.audit.walk import FileHit, RepoContext
from quality_gates.models import Finding, GateResult
from quality_gates.oracle import remaining_from_results, render_prompt
from quality_gates.playbook import build_playbook
from quality_gates.review.craft import craft_review


def _hit(relative: str, text: str) -> FileHit:
    return FileHit(
        path=Path(relative),
        relative=relative,
        text=text,
        lines=text.splitlines(),
        is_test=False,
        is_source=True,
    )


def test_craft_flags_swallowed_exception_and_magic_number() -> None:
    diff = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,0 +1,6 @@
+def price(amount):
+    try:
+        return amount * 0.175 + 0.175
+    except:
+        pass
"""
    rules = {item.rule for item in craft_review(diff)}
    assert "swallowed-exception" in rules or "bare-except" in rules
    assert "magic-number" in rules


def test_craft_flags_deep_nesting_and_long_function() -> None:
    body = "\n".join(["    x = 1"] * 80)
    nested = """
def decide(a, b, c, d, e):
    if a:
        if b:
            if c:
                if d:
                    if e:
                        return 1
"""
    long_fn = f"def huge():\n{body}\n"
    nest_findings = craft_review(
        "diff --git a/src/dec.py b/src/dec.py\n+++ b/src/dec.py\n@@ -1,0 +1,8 @@\n"
        + "\n".join("+" + line for line in nested.strip().splitlines())
        + "\n"
    )
    long_findings = craft_review(
        "diff --git a/src/big.py b/src/big.py\n+++ b/src/big.py\n@@ -1,0 +1,81 @@\n"
        + "\n".join("+" + line for line in long_fn.splitlines())
        + "\n"
    )
    assert any(item.rule == "deep-nesting" for item in nest_findings)
    assert any(item.rule == "long-function" for item in long_findings)


def test_craft_does_not_treat_elif_dispatch_as_nesting() -> None:
    chain = """
def pick(kind):
    if kind == "a":
        return 1
    elif kind == "b":
        return 2
    elif kind == "c":
        return 3
    elif kind == "d":
        return 4
    elif kind == "e":
        return 5
    elif kind == "f":
        return 6
"""
    findings = craft_review(
        "diff --git a/src/pick.py b/src/pick.py\n+++ b/src/pick.py\n@@ -1,0 +1,14 @@\n"
        + "\n".join("+" + line for line in chain.strip().splitlines())
        + "\n"
    )
    assert not any(item.rule == "deep-nesting" for item in findings)


def test_scan_craft_feeds_audit_check_48() -> None:
    text = """
def decide(a, b, c, d, e):
    if a:
        if b:
            if c:
                if d:
                    if e:
                        return 1
"""
    ctx = RepoContext(root=Path("."), files=[_hit("src/dec.py", text)])
    grouped = scan_craft(ctx)
    assert 48 in grouped
    assert grouped[48][0].check_id == 48


def test_playbook_puts_format_first_and_certificate_blocks() -> None:
    results = [
        GateResult(
            name="format",
            status="fail",
            findings=[
                Finding(
                    gate="format",
                    message="needs format",
                    severity="error",
                    path="a.py",
                )
            ],
        ),
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
        ),
    ]
    payload = remaining_from_results(results)
    assert payload["green"] is False
    assert payload["playbook"]["next"]["gate"] == "format"
    assert payload["playbook"]["next"]["autofix"] is True
    assert payload["certificate"]["auto_merge"] == "blocked"
    prompt = render_prompt(payload)
    assert "Next action:" in prompt
    assert "quality fix" in prompt or "format" in prompt
    assert "quality oracle --run" in prompt


def test_green_oracle_is_merge_ready() -> None:
    payload = remaining_from_results([GateResult(name="lint", status="pass")])
    assert payload["green"] is True
    assert payload["certificate"]["ready"] is True
    assert payload["certificate"]["auto_merge"] == "ready"
    assert (
        "certificate" in render_prompt(payload).lower()
        or "green" in render_prompt(payload).lower()
    )
    playbook = build_playbook(payload)
    assert playbook["remaining"] == 0
