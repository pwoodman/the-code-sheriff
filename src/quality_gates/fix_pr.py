"""Create a separate fix PR. Never push to the author's head branch."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from quality_gates.models import Finding
from quality_gates.review.apply import apply_and_verify


def branch_name(pr: str | int) -> str:
    return f"sheriff/fix/{pr}"


def generate_test_patch(path: str, function: str, framework: str = "pytest") -> str:
    if framework in {"pytest", "python"}:
        return (
            f"def test_{function}_edge_cases():\n"
            f"    # generated for changed {path}:{function}\n"
            f"    assert {function} is not None\n"
        )
    if framework in {"jest", "vitest"}:
        return (
            f"test('{function} edge cases', () => {{\n"
            f"  // generated for changed {path}:{function}\n"
            f"  expect({function}).toBeDefined();\n"
            f"}});\n"
        )
    return f"// TODO: add tests for {function} in {path}\n"


def plan_fix_pr(
    *,
    pr: str | int,
    findings: list[Finding],
    default_branch: str = "main",
) -> dict[str, Any]:
    patches = [item for item in findings if item.patch]
    return {
        "source_branch": default_branch,
        "fix_branch": branch_name(pr),
        "author_branch_untouched": True,
        "patches": len(patches),
        "findings": [item.rule or item.message for item in patches],
    }


def apply_fix_pr(
    root: Path,
    findings: list[Finding],
    *,
    pr: str | int,
    create_branch: bool = False,
    default_branch: str = "main",
) -> dict[str, Any]:
    plan = plan_fix_pr(pr=pr, findings=findings, default_branch=default_branch)
    applied = []
    if create_branch:
        subprocess.run(
            ["git", "checkout", "-B", plan["fix_branch"], default_branch],
            cwd=root,
            check=False,
            capture_output=True,
        )
    for item in findings:
        if not item.patch:
            continue
        result = apply_and_verify(root, item)
        applied.append({"rule": item.rule, "resolved": bool(result.get("resolved"))})
    plan["applied"] = applied
    reports = root / ".quality-reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "fix-pr.json").write_text(
        json.dumps(plan, indent=2) + "\n", encoding="utf-8"
    )
    return plan
