"""Per-test duration tracking vs the last touched run.

A 15% slowdown on a test you just changed is a signal, not a dashboard.
Accepting records a new baseline for that nodeid so CI stays quiet on purpose.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from quality_gates.config import QualityConfig
from quality_gates.models import Finding

TIMING_FILE = "test-timing.json"


def compare_timings(
    root: Path,
    config: QualityConfig,
    *,
    current: dict[str, float],
    touched: set[str],
) -> tuple[list[Finding], dict[str, Any]]:
    report = root / ".quality-reports"
    report.mkdir(parents=True, exist_ok=True)
    path = report / TIMING_FILE
    previous = _load(path)
    tests: dict[str, Any] = dict(previous.get("tests") or {})
    threshold = max(0.0, config.test_timing_regression_pct) / 100.0
    min_delta = max(0.0, config.test_timing_min_delta_ms) / 1000.0
    findings: list[Finding] = []
    for nodeid, seconds in current.items():
        row = tests.get(nodeid) or {}
        baseline = _baseline_seconds(row)
        file_path = nodeid.split("::", 1)[0]
        is_touched = nodeid in touched or file_path in touched
        if is_touched and baseline is not None:
            limit = baseline * (1.0 + threshold)
            if seconds > limit and (seconds - baseline) >= min_delta:
                pct = ((seconds - baseline) / baseline) * 100.0
                findings.append(
                    Finding(
                        gate="test",
                        rule="timing-regression",
                        path=file_path,
                        severity="error",
                        message=(
                            f"{nodeid} took {seconds:.3f}s, "
                            f"{pct:.0f}% slower than last touched run "
                            f"({baseline:.3f}s; threshold {config.test_timing_regression_pct:g}%)"
                        ),
                        suggestion=f"quality timing accept --test {nodeid}",
                    )
                )
                tests[nodeid] = {
                    **row,
                    "seconds": seconds,
                    "baseline_seconds": baseline,
                    "file": file_path,
                    "regressed": True,
                }
                continue
        if is_touched or nodeid not in tests:
            tests[nodeid] = {
                "seconds": seconds,
                "baseline_seconds": (
                    seconds if is_touched else (row.get("baseline_seconds") or seconds)
                ),
                "file": file_path,
                "accepted_seconds": (
                    _ratchet_accepted(row, seconds)
                    if is_touched
                    else row.get("accepted_seconds")
                ),
                "regressed": False,
            }
    payload = {
        "schema_version": "1.0.0",
        "regression_pct": config.test_timing_regression_pct,
        "min_delta_ms": config.test_timing_min_delta_ms,
        "tests": tests,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return findings, payload


def accept_timings(
    root: Path, *, nodeids: list[str] | None = None, all_regressed: bool = False
) -> dict[str, Any]:
    path = root / ".quality-reports" / TIMING_FILE
    data = _load(path)
    tests = data.setdefault("tests", {})
    accepted: list[str] = []
    wanted = set(nodeids or [])
    for nodeid, row in tests.items():
        if not isinstance(row, dict):
            continue
        seconds = row.get("seconds")
        if not isinstance(seconds, (int, float)):
            continue
        selected = nodeid in wanted or (all_regressed and bool(row.get("regressed")))
        if not selected:
            continue
        row["accepted_seconds"] = float(seconds)
        row["baseline_seconds"] = float(seconds)
        row["regressed"] = False
        accepted.append(nodeid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return {"accepted": accepted, "path": str(path)}


def parse_junit(path: Path) -> dict[str, float]:
    if not path.is_file():
        return {}
    try:
        tree = ET.parse(path)
    except (OSError, ET.ParseError):
        return {}
    out: dict[str, float] = {}
    for case in tree.iter("testcase"):
        name = case.get("name") or ""
        classname = case.get("classname") or ""
        try:
            seconds = float(case.get("time") or 0)
        except ValueError:
            continue
        file_path = _classname_to_path(classname)
        nodeid = f"{file_path}::{name}" if name else file_path
        out[nodeid] = seconds
    return out


def _classname_to_path(classname: str) -> str:
    text = classname.strip()
    if not text:
        return "unknown"
    if "/" in text or text.endswith(".py"):
        return text
    return text.replace(".", "/") + ".py"


def _ratchet_accepted(row: dict[str, Any], seconds: float) -> float | None:
    accepted = row.get("accepted_seconds")
    if isinstance(accepted, (int, float)) and accepted > 0:
        return float(seconds) if seconds <= float(accepted) else float(accepted)
    return accepted if isinstance(accepted, (int, float)) else None


def _baseline_seconds(row: dict[str, Any]) -> float | None:
    accepted = row.get("accepted_seconds")
    if isinstance(accepted, (int, float)) and accepted > 0:
        return float(accepted)
    for key in ("baseline_seconds", "seconds"):
        value = row.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    return None


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"tests": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"tests": {}}
    return data if isinstance(data, dict) else {"tests": {}}
