"""Independent test-execution gate; coverage is a separate measurement."""

from __future__ import annotations

import json
from pathlib import Path

from quality_gates.authorization import blocked_gate_result, check_authorization
from quality_gates.config import QualityConfig
from quality_gates.detect import iter_project_files
from quality_gates.gates.common import fail_or_pass, merge_results, skip_result
from quality_gates.models import Finding, GateResult
from quality_gates.tools import run, which


def run_tests(root: Path, config: QualityConfig) -> GateResult:
    auth_reason = check_authorization(config, "test execution", permission="execution")
    if auth_reason:
        return blocked_gate_result("test", auth_reason)
    selected, selection_note = _selected_tests(root)
    runners: list[tuple[str, list[str]]] = []
    if (root / "tests").is_dir() or list(root.glob("test_*.py")):
        pytest = which("pytest", project=root) or which("py.test", project=root)
        if pytest:
            runners.append(("pytest", [pytest, "-q", "--tb=line", *selected]))
        else:
            return skip_result(
                "test", "pytest is required for discovered Python tests", tool="pytest"
            )
    package = root / "package.json"
    if package.is_file():
        try:
            deps = {
                **json.loads(package.read_text(encoding="utf-8")).get(
                    "dependencies", {}
                ),
                **json.loads(package.read_text(encoding="utf-8")).get(
                    "devDependencies", {}
                ),
            }
        except (OSError, json.JSONDecodeError):
            deps = {}
        for name in ("vitest", "jest"):
            binary = which(name, project=root)
            if name in deps and binary:
                js_targets = [
                    s
                    for s in selected
                    if any(s.endswith(ext) for ext in (".js", ".ts", ".jsx", ".tsx"))
                ]
                runners.append(
                    (
                        name,
                        [binary, "run", *js_targets]
                        if name == "vitest"
                        else [binary, "--watchAll=false", *js_targets],
                    )
                )
    if (root / "go.mod").is_file():
        go_bin = which("go", project=root)
        if go_bin:
            go_targets = [s for s in selected if s.endswith(".go")] or ["./..."]
            runners.append(("go", [go_bin, "test", *go_targets]))
    if (root / "Cargo.toml").is_file():
        cargo_bin = which("cargo", project=root)
        if cargo_bin:
            runners.append(("cargo", [cargo_bin, "test"]))
    if not runners:
        source = [
            path
            for path in iter_project_files(root, config)
            if path.suffix.lower()
            in {".py", ".js", ".ts", ".tsx", ".go", ".rs", ".java", ".cs"}
        ]
        if source:
            suggestion = _onboarding_suggestion(root, source)
            return GateResult(
                name="test",
                status="unsupported",
                exit_state="unsupported",
                findings=[
                    Finding(
                        gate="test",
                        rule="test-readiness",
                        message="source files were discovered but no supported test runner is configured",
                        severity="error",
                        suggestion=suggestion,
                    )
                ],
                notes=["new-project onboarding required", suggestion],
            )
        return skip_result("test", "no supported test runner discovered")
    parts: list[GateResult] = []
    for name, argv in runners:
        result = run(argv, cwd=root, timeout=600)
        findings: list[Finding] = []
        if result.returncode == 5:
            findings.append(
                Finding(
                    gate="test",
                    rule="zero-tests",
                    message=f"{name} collected zero tests",
                    severity="error",
                )
            )
        elif result.exit_state == "timeout" or getattr(result, "timed_out", False):
            findings.append(
                Finding(
                    gate="test",
                    rule="test-timeout",
                    message=f"{name} timed out",
                    severity="error",
                )
            )
        elif result.returncode not in {0, None}:
            findings.append(
                Finding(
                    gate="test",
                    rule="execution-failed",
                    message=f"{name} exited with returncode {result.returncode}",
                    severity="error",
                )
            )
        parts.append(
            fail_or_pass(
                "test", findings, [f"ran {name}", selection_note], root=root, run=result
            )
        )
    return merge_results("test", parts)


def propose_onboarding_patch(root: Path, source: list[Path]) -> str:
    """Generate a starter smoke test patch for newly onboarded projects."""
    suffixes = {path.suffix.lower() for path in source}
    if {".py"} & suffixes:
        return (
            "--- /dev/null\n"
            "+++ b/tests/test_smoke.py\n"
            "@@ -0,0 +1,3 @@\n"
            "+def test_smoke():\n"
            "+    pass\n"
        )
    if {".js", ".ts", ".tsx"} & suffixes:
        return (
            "--- /dev/null\n"
            "+++ b/test/smoke.test.js\n"
            "@@ -0,0 +1,3 @@\n"
            "+test('smoke', () => {\n"
            "+  expect(true).toBe(true);\n"
            "+});\n"
        )
    if ".go" in suffixes:
        return (
            "--- /dev/null\n"
            "+++ b/smoke_test.go\n"
            "@@ -0,0 +1,6 @@\n"
            "+package main\n"
            '+import "testing"\n'
            "+func TestSmoke(t *testing.T) {}\n"
        )
    return (
        "--- /dev/null\n"
        "+++ b/tests/test_smoke.py\n"
        "@@ -0,0 +1,3 @@\n"
        "+def test_smoke():\n"
        "+    pass\n"
    )


def _selected_tests(root: Path) -> tuple[list[str], str]:
    """Use impact-selected tests only when fresh structured evidence exists."""
    path = root / ".quality-reports" / "impact.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        mapping = data.get("tests") if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        mapping = None
    candidates = (
        sorted(
            {
                str(test)
                for tests in mapping.values()
                for test in tests
                if (root / str(test)).is_file()
            }
        )
        if isinstance(mapping, dict)
        else []
    )
    if candidates:
        return candidates, f"impact-selected {len(candidates)} test file(s)"
    return [], "selection uncertain; ran full supported suite"


def _onboarding_suggestion(root: Path, source: list[Path]) -> str:
    suffixes = {path.suffix.lower() for path in source}
    if {".py"} & suffixes:
        return "add pytest and tests/test_smoke.py, then run `quality test`"
    if {".js", ".ts", ".tsx"} & suffixes:
        return "add Vitest or Jest and one smoke spec, then run `quality test`"
    if ".go" in suffixes:
        return "add a *_test.go smoke test, then run `quality test`"
    return "configure a supported test runner and add a smoke test"
