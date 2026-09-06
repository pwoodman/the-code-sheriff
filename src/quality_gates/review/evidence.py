"""Optional: run impact-selected tests as evidence for a review finding."""

from __future__ import annotations

from pathlib import Path

from quality_gates.authorization import check_authorization
from quality_gates.config import QualityConfig
from quality_gates.review.context import load_report_json
from quality_gates.tools import run, which

TEST_HINT = ("test", "spec", "__tests__")


def collect_test_evidence(
    root: Path,
    config: QualityConfig,
    paths: list[str],
) -> str:
    if not config.review_verify_tests:
        return ""
    auth_reason = check_authorization(
        config, "review test execution", permission="execution"
    )
    if auth_reason:
        return f"### test evidence\n\n- blocked: {auth_reason}"
    specs = _candidate_tests(root, paths)
    if not specs:
        return ""
    lines = ["### test evidence (impact-selected, bounded)"]
    for spec in specs[:5]:
        result = _run_one(root, spec)
        lines.append(result)
    return "\n".join(lines)


def _candidate_tests(root: Path, paths: list[str]) -> list[str]:
    report = load_report_json(root, "impact.json") or {}
    found: list[str] = []
    seen: set[str] = set()
    mapping = report.get("tests") if isinstance(report, dict) else None
    if isinstance(mapping, dict):
        for src in paths:
            for item in mapping.get(src) or []:
                posix = str(item).replace("\\", "/")
                if posix in seen:
                    continue
                seen.add(posix)
                found.append(posix)
    if found:
        return found
    for path in paths:
        name = Path(path).name.lower()
        if (
            any(hint in name or hint in path.replace("\\", "/") for hint in TEST_HINT)
            and path not in seen
        ):
            found.append(path)
    return found


def _run_one(root: Path, spec: str) -> str:
    posix = spec.replace("\\", "/")
    if posix.endswith(".py"):
        argv = ["pytest", posix, "-q", "--tb=line"]
    elif posix.endswith((".ts", ".js", ".tsx", ".jsx")):
        vitest = which("vitest", project=root)
        if not vitest:
            return f"- skipped {posix} (resolved local vitest unavailable)"
        argv = [vitest, "run", posix]
    else:
        return f"- skipped {posix} (no runner)"
    result = run(argv, cwd=root, timeout=45)
    excerpt = (result.stdout or result.stderr or "").strip().splitlines()
    tail = " | ".join(excerpt[-3:])[:240] if excerpt else f"exit {result.returncode}"
    status = "pass" if result.returncode == 0 else "fail"
    return f"- {posix}: {status} — {tail}"
