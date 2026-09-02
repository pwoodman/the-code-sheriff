"""Test coverage gate. Default floor is 80% line coverage (industry baseline)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.coverage_parse import (
    CoverageSummary,
    find_existing_reports,
    parse_coverage_file,
)
from quality_gates.detect import iter_project_files
from quality_gates.gates.common import fail_or_pass, skip_result
from quality_gates.models import Finding, GateResult
from quality_gates.tools import run, which

# ISTQB / IEEE-adjacent industry practice: 80% statement coverage is the
# most common contractual floor. Branch coverage is not enforced unless set.
DEFAULT_LINE = 80.0


def run_coverage(root: Path, config: QualityConfig) -> GateResult:
    if not config.coverage_enabled:
        return skip_result("coverage", "coverage gate disabled in quality.toml")

    if not _has_tests(root, config):
        return skip_result(
            "coverage",
            "no test files found — skip (skip ≠ fail). Add tests to measure coverage.",
        )

    report_dir = root / ".quality-reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    summary, notes = _collect(root, config, report_dir)
    if summary is None or summary.line_percent is None:
        return skip_result(
            "coverage",
            "no coverage tool or report found — install pytest-cov, Jest/Vitest "
            "--coverage, or go test -cover. skip ≠ fail.",
            tool="coverage",
        )

    payload = {
        "line_percent": summary.line_percent,
        "branch_percent": summary.branch_percent,
        "lines_covered": summary.lines_covered,
        "lines_valid": summary.lines_valid,
        "source": summary.source,
        "line_floor": config.coverage_line,
        "branch_floor": config.coverage_branch,
        "baseline": (
            "80% statement coverage is the common industry / ISTQB-style floor; "
            "override [quality.coverage] line if this repo has a documented exception."
        ),
    }
    (report_dir / "coverage.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )

    ok, reason = summary.meets(config.coverage_line, config.coverage_branch)
    branch_note = ""
    if summary.branch_percent is not None:
        branch_note = f", branch {summary.branch_percent:.1f}%"
        if config.coverage_branch > 0:
            branch_note += f" (floor {config.coverage_branch:.0f}%)"
    notes.append(
        f"line coverage {summary.line_percent:.1f}% (floor {config.coverage_line:.0f}%)"
        f"{branch_note} from {Path(summary.source).name}"
    )
    findings: list[Finding] = []
    if not ok:
        findings.append(
            Finding(
                gate="coverage",
                rule="below-floor",
                message=reason,
                severity="error",
            )
        )
    return fail_or_pass("coverage", findings, notes)


def _collect(
    root: Path, config: QualityConfig, report_dir: Path
) -> tuple[CoverageSummary | None, list[str]]:
    notes: list[str] = []
    tool = config.coverage_tool
    if tool in {"auto", "existing"}:
        existing = _best_existing(root)
        if existing is not None:
            notes.append(f"using existing report {existing.source}")
            if tool == "existing":
                return existing, notes
            # auto: prefer a freshly collected report when a tool is available
            collected = _run_tool(root, config, report_dir, notes)
            return (collected or existing), notes

    collected = _run_tool(root, config, report_dir, notes)
    if collected is not None:
        return collected, notes
    return _best_existing(root), notes


def _best_existing(root: Path) -> CoverageSummary | None:
    best: CoverageSummary | None = None
    for path in find_existing_reports(root):
        parsed = parse_coverage_file(path)
        if parsed is None or parsed.line_percent is None:
            continue
        if best is None or (parsed.lines_valid >= best.lines_valid):
            best = parsed
    return best


def _run_tool(
    root: Path,
    config: QualityConfig,
    report_dir: Path,
    notes: list[str],
) -> CoverageSummary | None:
    tool = config.coverage_tool
    runners = []
    if tool in {"auto", "pytest"}:
        runners.append(lambda: _pytest_cov(root, report_dir, notes))
    if tool in {"auto", "jest", "vitest"}:
        runners.append(lambda: _js_coverage(root, notes))
    if tool in {"auto", "go"}:
        runners.append(lambda: _go_cover(root, report_dir, notes))
    for runner in runners:
        summary = runner()
        if summary is not None and summary.line_percent is not None:
            return summary
    return None


def _pytest_cov(
    root: Path, report_dir: Path, notes: list[str]
) -> CoverageSummary | None:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    if not (root / "tests").is_dir() and not list(root.glob("test_*.py")):
        py_tests = [
            p
            for p in root.rglob("test_*.py")
            if "site-packages" not in p.as_posix() and ".venv" not in p.as_posix()
        ]
        if not py_tests:
            return None
    pytest_bin = which("pytest", project=root) or which("py.test", project=root)
    if not pytest_bin:
        return None
    xml_path = report_dir / "coverage.xml"
    argv = [
        pytest_bin,
        "--cov",
        _cov_target(root),
        "--cov-report",
        f"xml:{xml_path}",
        "--cov-report",
        "term",
        "-q",
    ]
    result = run(argv, cwd=root, timeout=600)
    if result.skipped:
        notes.append(result.skip_reason or "pytest skipped")
        return None
    if xml_path.is_file():
        parsed = parse_coverage_file(xml_path)
        if parsed:
            notes.append("collected via pytest-cov")
            return parsed
    combined = (result.stdout or "") + (result.stderr or "")
    if "unrecognized arguments" in combined or "CoverageWarning" in combined:
        notes.append("pytest is present but pytest-cov is not installed")
    elif result.returncode not in {0, 1, 5}:
        notes.append(f"pytest --cov exited {result.returncode}")
    return None


def _js_coverage(root: Path, notes: list[str]) -> CoverageSummary | None:
    pkg = root / "package.json"
    if not pkg.is_file():
        return None
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
    if "vitest" in deps:
        bin_name = "vitest"
        argv = ["npx", "--yes", "vitest", "run", "--coverage"]
    elif "jest" in deps:
        bin_name = "jest"
        argv = [
            "npx",
            "--yes",
            "jest",
            "--coverage",
            "--coverageReporters=json-summary",
            "--watchAll=false",
        ]
    else:
        return None
    if not which("npx", project=root) and not which(bin_name, project=root):
        return None
    result = run(argv, cwd=root, timeout=600)
    if result.skipped:
        return None
    summary_path = root / "coverage" / "coverage-summary.json"
    parsed = parse_coverage_file(summary_path) if summary_path.is_file() else None
    if parsed:
        notes.append(f"collected via {bin_name}")
    return parsed


def _go_cover(root: Path, report_dir: Path, notes: list[str]) -> CoverageSummary | None:
    if not (root / "go.mod").is_file():
        return None
    if not which("go", project=root):
        return None
    out = report_dir / "coverage.out"
    result = run(
        ["go", "test", "./...", f"-coverprofile={out}"],
        cwd=root,
        timeout=600,
    )
    if result.skipped or not out.is_file():
        return None
    parsed = parse_coverage_file(out)
    if parsed:
        notes.append("collected via go test -cover")
    return parsed


def _cov_target(root: Path) -> str:
    src = root / "src"
    if src.is_dir():
        packages = [
            p.name
            for p in src.iterdir()
            if p.is_dir() and (p / "__init__.py").is_file()
        ]
        if len(packages) == 1:
            return packages[0]
        if packages:
            return ",".join(sorted(packages))
    for path in root.iterdir():
        if (
            path.is_dir()
            and (path / "__init__.py").is_file()
            and path.name
            not in {
                "tests",
                "test",
            }
        ):
            return path.name
    return "."


def _has_tests(root: Path, config: QualityConfig) -> bool:
    markers = (
        ".spec.",
        ".test.",
        ".cy.",
        "_test.py",
        "_test.go",
        "test_",
    )
    for path in iter_project_files(root, config):
        name = path.name.lower()
        posix = path.as_posix().replace("\\", "/").lower()
        if (
            any(token in name for token in markers)
            or "/tests/" in posix
            or "/__tests__/" in posix
        ):
            return True
    return False
