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
            return parse_xml_coverage(path)
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


def parse_xml_coverage(path: Path) -> CoverageSummary:
    """Parse Cobertura, JaCoCo, or OpenCover XML without resolving entities."""
    data = path.read_text(encoding="utf-8-sig", errors="strict")
    if "<!DOCTYPE" in data.upper() or "<!ENTITY" in data.upper():
        raise ValueError("coverage XML with declarations/entities is not accepted")
    root = ET.fromstring(data)
    tag = root.tag.rsplit("}", 1)[-1].lower()
    if tag == "report":
        return _parse_jacoco_root(root, path)
    if tag == "coveragesession":
        return _parse_opencover_root(root, path)
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
    return CoverageSummary(
        line_percent=None if line_rate is None else round(line_rate * 100, 2),
        branch_percent=None if branch_rate is None else round(branch_rate * 100, 2),
        lines_covered=lines_covered,
        lines_valid=lines_valid,
        branches_covered=branches_covered,
        branches_valid=branches_valid,
        source=str(path),
    )


def _parse_jacoco_root(root: ET.Element, path: Path) -> CoverageSummary:
    counters = {item.get("type"): item for item in root.findall("./counter")}
    line = counters.get("LINE")
    branch = counters.get("BRANCH")
    covered = _attr_int(line, "covered") if line is not None else 0
    missed = _attr_int(line, "missed") if line is not None else 0
    br_covered = _attr_int(branch, "covered") if branch is not None else 0
    br_missed = _attr_int(branch, "missed") if branch is not None else 0
    return _from_counts(
        path, covered, covered + missed, br_covered, br_covered + br_missed
    )


def _parse_opencover_root(root: ET.Element, path: Path) -> CoverageSummary:
    summary = root.find("./Summary")
    if summary is None:
        summary = root.find(".//Summary")
    if summary is None:
        return CoverageSummary(None, None, source=str(path))
    return _from_counts(
        path,
        _attr_int(summary, "visitedSequencePoints"),
        _attr_int(summary, "numSequencePoints"),
        _attr_int(summary, "visitedBranchPoints"),
        _attr_int(summary, "numBranchPoints"),
    )


def _from_counts(
    path: Path, covered: int, valid: int, branches_covered: int, branches_valid: int
) -> CoverageSummary:
    return CoverageSummary(
        line_percent=None if not valid else round(covered * 100 / valid, 2),
        branch_percent=(
            None
            if not branches_valid
            else round(branches_covered * 100 / branches_valid, 2)
        ),
        lines_covered=covered,
        lines_valid=valid,
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
        root / "target" / "site" / "jacoco" / "jacoco.xml",
        root / "build" / "reports" / "jacoco" / "test" / "jacocoTestReport.xml",
        root / "TestResults" / "coverage.opencover.xml",
        root / "TestResults" / "coverage.cobertura.xml",
        root / "coverage" / "cobertura-coverage.xml",
    ]
    for pattern in (
        "**/jacoco.xml",
        "**/jacocoTestReport.xml",
        "**/coverage.opencover.xml",
        "**/coverage.cobertura.xml",
        "**/lcov.info",
        "**/coverage-summary.json",
        "**/coverage.out",
    ):
        candidates.extend(
            path
            for path in root.glob(pattern)
            if not ({".git", "node_modules", ".venv"} & set(path.parts))
        )
    return list(dict.fromkeys(path for path in candidates if path.is_file()))


def aggregate_summaries(summaries: list[CoverageSummary]) -> CoverageSummary | None:
    """Aggregate independent reports by measured line/branch totals."""
    usable = [item for item in summaries if item.lines_valid > 0]
    if not usable:
        return None
    lines_valid = sum(item.lines_valid for item in usable)
    lines_covered = sum(item.lines_covered for item in usable)
    branch_items = [item for item in usable if item.branches_valid > 0]
    branches_valid = sum(item.branches_valid for item in branch_items)
    branches_covered = sum(item.branches_covered for item in branch_items)
    return CoverageSummary(
        line_percent=round(lines_covered * 100 / lines_valid, 2),
        branch_percent=(
            round(branches_covered * 100 / branches_valid, 2)
            if branches_valid
            else None
        ),
        lines_covered=lines_covered,
        lines_valid=lines_valid,
        branches_covered=branches_covered,
        branches_valid=branches_valid,
        source=" + ".join(item.source for item in usable),
    )


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


def parse_line_hits(path: Path) -> dict[str, dict[int, int]]:
    """Return mapping of normalized file_path -> {line_number: hits}."""
    hits_by_file: dict[str, dict[int, int]] = {}
    if not path.is_file():
        return hits_by_file
    name = path.name.lower()
    try:
        if name.endswith(".xml") or name == "cobertura.xml":
            tree = ET.parse(path)
            for cls in tree.findall(".//class"):
                filename = cls.get("filename") or ""
                if not filename:
                    continue
                norm = filename.replace("\\", "/")
                file_hits: dict[int, int] = {}
                for line in cls.findall(".//line"):
                    nr = _attr_int(line, "number")
                    hits = _attr_int(line, "hits")
                    if nr:
                        file_hits[nr] = hits
                if file_hits:
                    hits_by_file[norm] = file_hits
        elif name.endswith(".json") or name == "coverage-summary.json":
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for filepath, file_data in data.items():
                    if (
                        isinstance(file_data, dict)
                        and "s" in file_data
                        and "statementMap" in file_data
                    ):
                        norm = filepath.replace("\\", "/")
                        file_hits = {}
                        for s_id, hit in file_data["s"].items():
                            loc = file_data["statementMap"].get(s_id, {})
                            start_line = loc.get("start", {}).get("line")
                            if start_line is not None:
                                file_hits[int(start_line)] = int(hit)
                        if file_hits:
                            hits_by_file[norm] = file_hits
    except Exception:
        return hits_by_file
    return hits_by_file
