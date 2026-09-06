"""Test coverage gate. Default floor is 80% line coverage (industry baseline)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from quality_gates.change_manifest import ChangeManifest
from quality_gates.config import QualityConfig
from quality_gates.coverage_parse import (
    CoverageSummary,
    aggregate_summaries,
    find_existing_reports,
    parse_coverage_file,
    parse_line_hits,
)
from quality_gates.detect import iter_project_files
from quality_gates.evidence import config_digest, snapshot_digest
from quality_gates.gates.common import fail_or_pass, skip_result
from quality_gates.models import Finding, GateResult
from quality_gates.tools import run, which

# ISTQB / IEEE-adjacent industry practice: 80% statement coverage is the
# most common contractual floor. Branch coverage is not enforced unless set.
DEFAULT_LINE = 80.0


def run_coverage(
    root: Path,
    config: QualityConfig,
    *,
    manifest: ChangeManifest | None = None,
    selection: list[str] | None = None,
) -> GateResult:
    if not config.coverage_enabled:
        return skip_result("coverage", "coverage gate disabled in quality.toml")

    if not _has_tests(root, config):
        return skip_result(
            "coverage",
            "no test files found — skip (skip ≠ fail). Add tests to measure coverage.",
        )

    report_dir = root / ".quality-reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    summary, notes = _collect(root, config, report_dir, manifest)
    if summary is None or summary.line_percent is None:
        if any(
            "stale coverage" in note or "existing coverage evidence" in note
            for note in notes
        ):
            return GateResult(
                name="coverage",
                status="fail",
                exit_state="blocked",
                findings=[
                    Finding(
                        gate="coverage",
                        rule="stale-evidence",
                        message="coverage artifact is not attributable to the assessed snapshot",
                        severity="error",
                    )
                ],
                notes=notes,
            )
        return skip_result(
            "coverage",
            "no coverage tool or report found — install pytest-cov, Jest/Vitest "
            "--coverage, or go test -cover. skip ≠ fail.",
            tool="coverage",
        )

    payload = {
        "schema_version": "1.0.0",
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
        "evidence": {
            "snapshot": snapshot_digest(root, manifest),
            "configuration": config_digest(config),
            "selection": sorted(selection or []),
        },
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
    for note in notes:
        if note.startswith("test execution failed:"):
            findings.append(
                Finding(
                    gate="coverage",
                    rule="test-execution-failed",
                    message=note,
                    severity="error",
                )
            )
    if not ok:
        findings.append(
            Finding(
                gate="coverage",
                rule="below-floor",
                message=reason,
                severity="error",
            )
        )
    if manifest is not None and summary.source:
        hits = parse_line_hits(Path(summary.source))
        if hits:
            findings.extend(
                _check_changed_lines(root, manifest, hits, config.coverage_line)
            )
    return fail_or_pass("coverage", findings, notes)


def _check_changed_lines(
    root: Path,
    manifest: ChangeManifest,
    line_hits: dict[str, dict[int, int]],
    floor: float,
) -> list[Finding]:
    findings: list[Finding] = []
    for change in manifest.changes:
        if change.kind == "deleted" or not change.path.endswith(
            (".py", ".ts", ".js", ".tsx", ".jsx", ".go")
        ):
            continue
        file_hits = None
        for k, v in line_hits.items():
            if (
                k == change.path
                or k.endswith("/" + change.path)
                or change.path.endswith("/" + k)
            ):
                file_hits = v
                break
        if file_hits is None:
            continue
        uncovered: list[int] = []
        if change.hunks:
            for hunk in change.hunks:
                for ln in range(
                    hunk.new_start, hunk.new_start + max(1, hunk.new_count)
                ):
                    if ln in file_hits and file_hits[ln] == 0:
                        uncovered.append(ln)
        elif change.kind in {"added", "untracked"}:
            for ln, hits in file_hits.items():
                if hits == 0:
                    uncovered.append(ln)
        if uncovered and floor > 0:
            findings.append(
                Finding(
                    gate="coverage",
                    rule="uncovered-changed-lines",
                    path=change.path,
                    line=uncovered[0],
                    message=(
                        f"changed lines in {change.path} lack test coverage "
                        f"({len(uncovered)} uncovered lines: {uncovered[:5]}...)"
                    ),
                    severity="error",
                )
            )
    return findings


def _collect(
    root: Path,
    config: QualityConfig,
    report_dir: Path,
    manifest: ChangeManifest | None = None,
) -> tuple[CoverageSummary | None, list[str]]:
    notes: list[str] = []
    tool = config.coverage_tool
    if tool in {"auto", "existing"}:
        existing = _best_existing(root)
        if existing is not None:
            notes.append(f"using existing report {existing.source}")
            if tool == "existing":
                if not _fresh_coverage_evidence(root, config, manifest):
                    notes.append(
                        "existing coverage evidence is absent or does not match this snapshot"
                    )
                    return None, notes
                return existing, notes
            collected = _run_tool(root, config, report_dir, notes)
            refreshed = _best_existing(root)
            combined = refreshed or collected or existing
            if (
                combined
                and " + " in combined.source
                and not any("partial polyglot coverage" in note for note in notes)
            ):
                notes.append(
                    "partial polyglot coverage: aggregated available existing and "
                    "fresh reports; ecosystems without reports remain unmeasured"
                )
            return combined, notes

    collected = _run_tool(root, config, report_dir, notes)
    if collected is not None:
        return collected, notes
    fallback = _best_existing(root)
    if fallback is not None and not _fresh_coverage_evidence(root, config, manifest):
        notes.append("refused stale coverage fallback")
        return None, notes
    return fallback, notes


def _fresh_coverage_evidence(
    root: Path, config: QualityConfig, manifest: ChangeManifest | None
) -> bool:
    path = root / ".quality-reports" / "coverage.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    evidence = payload.get("evidence")
    if not isinstance(evidence, dict):
        return False
    return evidence.get("snapshot") == snapshot_digest(root, manifest) and evidence.get(
        "configuration"
    ) == config_digest(config)


def _best_existing(root: Path) -> CoverageSummary | None:
    summaries: list[CoverageSummary] = []
    for path in find_existing_reports(root):
        parsed = parse_coverage_file(path)
        if parsed is None or parsed.line_percent is None:
            continue
        summaries.append(parsed)
    return aggregate_summaries(summaries)


def _run_tool(
    root: Path,
    config: QualityConfig,
    report_dir: Path,
    notes: list[str],
) -> CoverageSummary | None:
    if config.trust != "trusted":
        notes.append("test execution skipped because repository trust is not 'trusted'")
        return None
    tool = config.coverage_tool
    runners = []
    if tool in {"auto", "pytest"}:
        runners.append(lambda: _pytest_cov(root, report_dir, notes))
    if tool in {"auto", "jest", "vitest"}:
        runners.append(lambda: _js_coverage(root, notes))
    if tool in {"auto", "go"}:
        runners.append(lambda: _go_cover(root, report_dir, notes))
    summaries: list[CoverageSummary] = []
    seen_sources: set[str] = set()
    for runner in runners:
        summary = runner()
        if summary is None or summary.line_percent is None:
            continue
        source = str(Path(summary.source).resolve()) if summary.source else ""
        if source and source in seen_sources:
            notes.append(f"duplicate coverage report ignored: {summary.source}")
            continue
        if source:
            seen_sources.add(source)
        summaries.append(summary)
    aggregated = aggregate_summaries(summaries)
    if len(summaries) > 1:
        notes.append(
            f"partial polyglot coverage: aggregated {len(summaries)} independent "
            "reports; ecosystems without reports remain unmeasured"
        )
    return aggregated


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
    if result.timed_out:
        notes.append("test execution failed: pytest --cov timed out")
    elif result.returncode == 5:
        notes.append("test execution failed: pytest collected zero tests")
    elif result.returncode not in {0, None}:
        notes.append(f"test execution failed: pytest --cov exited {result.returncode}")
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
        executable = which("vitest", project=root)
        argv = [executable, "run", "--coverage"] if executable else []
    elif "jest" in deps:
        bin_name = "jest"
        executable = which("jest", project=root)
        argv = (
            [
                executable,
                "--coverage",
                "--coverageReporters=json-summary",
                "--watchAll=false",
            ]
            if executable
            else []
        )
    else:
        return None
    if not argv:
        notes.append(
            f"{bin_name} is declared but no resolved local executable is available"
        )
        return None
    result = run(argv, cwd=root, timeout=600)
    if result.skipped:
        return None
    if result.timed_out:
        notes.append(f"test execution failed: {bin_name} timed out")
    elif result.returncode not in {0, None}:
        notes.append(f"test execution failed: {bin_name} exited {result.returncode}")
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
    if result.skipped:
        return None
    if result.timed_out:
        notes.append("test execution failed: go test timed out")
    elif result.returncode not in {0, None}:
        notes.append(f"test execution failed: go test exited {result.returncode}")
    if not out.is_file():
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
