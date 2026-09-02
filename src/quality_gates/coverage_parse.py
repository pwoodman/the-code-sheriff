"""Parse common coverage report formats into a single summary."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CoverageSummary:
    line_percent: float | None
    branch_percent: float | None
    lines_covered: int = 0
    lines_valid: int = 0
    branches_covered: int = 0
    branches_valid: int = 0
    source: str = ""

    def meets(self, line_min: float, branch_min: float) -> tuple[bool, str]:
        if self.line_percent is None:
            return False, "coverage report has no line totals"
        if self.line_percent + 1e-9 < line_min:
            return (
                False,
                f"line coverage {self.line_percent:.1f}% is below the {line_min:.0f}% floor",
            )
        if branch_min > 0:
            if self.branch_percent is None:
                return (
                    False,
                    f"branch coverage is required ({branch_min:.0f}%) but the report has none",
                )
            if self.branch_percent + 1e-9 < branch_min:
                return (
                    False,
                    f"branch coverage {self.branch_percent:.1f}% is below the {branch_min:.0f}% floor",
                )
        return True, ""


def parse_coverage_file(path: Path) -> CoverageSummary | None:
    if not path.is_file():
        return None
    name = path.name.lower()
    try:
        if name.endswith(".xml") or name == "cobertura.xml":
            return parse_cobertura_xml(path)
        if name.endswith(".json") or name == "coverage-summary.json":
            return parse_istanbul_summary(path)
        if "lcov" in name or name.endswith(".info"):
            return parse_lcov(path)
        if name.endswith(".out"):
            return parse_go_coverprofile(path)
    except (ET.ParseError, json.JSONDecodeError, ValueError, OSError):
        return None
    return None


def parse_cobertura_xml(path: Path) -> CoverageSummary:
    tree = ET.parse(path)
    root = tree.getroot()
    line_rate = _attr_float(root, "line-rate")
    branch_rate = _attr_float(root, "branch-rate")
    lines_valid = _attr_int(root, "lines-valid")
    lines_covered = _attr_int(root, "lines-covered")
    branches_valid = _attr_int(root, "branches-valid")
    branches_covered = _attr_int(root, "branches-covered")

    if line_rate is None and lines_valid:
        line_rate = lines_covered / lines_valid
    if branch_rate is None and branches_valid:
        branch_rate = branches_covered / branches_valid

    line_pct = None if line_rate is None else round(line_rate * 100.0, 2)
    branch_pct = None if branch_rate is None else round(branch_rate * 100.0, 2)
    return CoverageSummary(
        line_percent=line_pct,
        branch_percent=branch_pct,
        lines_covered=lines_covered,
        lines_valid=lines_valid,
        branches_covered=branches_covered,
        branches_valid=branches_valid,
        source=str(path),
    )


def parse_istanbul_summary(path: Path) -> CoverageSummary:
    data = json.loads(path.read_text(encoding="utf-8"))
    total = data.get("total", data)
    lines = total.get("lines") or {}
    branches = total.get("branches") or {}
    line_pct = _num(lines.get("pct"))
    branch_pct = _num(branches.get("pct"))
    return CoverageSummary(
        line_percent=line_pct,
        branch_percent=branch_pct,
        lines_covered=int(lines.get("covered") or 0),
        lines_valid=int(lines.get("total") or 0),
        branches_covered=int(branches.get("covered") or 0),
        branches_valid=int(branches.get("total") or 0),
        source=str(path),
    )


def parse_lcov(path: Path) -> CoverageSummary:
    found = 0
    hit = 0
    br_found = 0
    br_hit = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("LF:"):
            found += int(line[3:] or 0)
        elif line.startswith("LH:"):
            hit += int(line[3:] or 0)
        elif line.startswith("BRF:"):
            br_found += int(line[4:] or 0)
        elif line.startswith("BRH:"):
            br_hit += int(line[4:] or 0)
    line_pct = None if found <= 0 else round(100.0 * hit / found, 2)
    branch_pct = None if br_found <= 0 else round(100.0 * br_hit / br_found, 2)
    return CoverageSummary(
        line_percent=line_pct,
        branch_percent=branch_pct,
        lines_covered=hit,
        lines_valid=found,
        branches_covered=br_hit,
        branches_valid=br_found,
        source=str(path),
    )


def parse_go_coverprofile(path: Path) -> CoverageSummary:
    # mode: set
    # path/file.go:N.N,N.N N N
    statements = 0
    covered = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("mode:") or not line.strip():
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            stmt = int(parts[1])
            count = int(parts[2])
        except ValueError:
            continue
        statements += stmt
        if count > 0:
            covered += stmt
    line_pct = None if statements <= 0 else round(100.0 * covered / statements, 2)
    return CoverageSummary(
        line_percent=line_pct,
        branch_percent=None,
        lines_covered=covered,
        lines_valid=statements,
        source=str(path),
    )


def find_existing_reports(root: Path) -> list[Path]:
    candidates = [
        root / "coverage.xml",
        root / "cobertura.xml",
        root / ".quality-reports" / "coverage.xml",
        root / "lcov.info",
        root / "coverage" / "lcov.info",
        root / "coverage" / "coverage-summary.json",
        root / "coverage" / "coverage-final.json",
        root / ".quality-reports" / "coverage-summary.json",
        root / ".quality-reports" / "coverage.out",
        root / "coverage.out",
    ]
    return [path for path in candidates if path.is_file()]


def _attr_float(node: ET.Element, name: str) -> float | None:
    raw = node.get(name)
    if raw is None or raw == "":
        return None
    return float(raw)


def _attr_int(node: ET.Element, name: str) -> int:
    raw = node.get(name)
    if raw is None or raw == "":
        return 0
    return int(float(raw))


def _num(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(value)
