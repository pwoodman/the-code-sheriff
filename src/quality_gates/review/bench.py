"""Owned ReviewBench: labeled diffs, hard negatives, volume cap, closed loop."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quality_gates.diagnostics import enrich_findings
from quality_gates.models import Finding
from quality_gates.review.apply import apply_finding
from quality_gates.review.heuristic import heuristic_review
from quality_gates.review.parse import fingerprint

DEFAULT_DIR = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "review_bench"
)


@dataclass
class BenchCase:
    case_id: str
    kind: str
    languages: list[str]
    heuristic: bool
    must_rules: list[str]
    must_not_rules: list[str]
    max_findings: int | None
    needles: list[str]
    rationale: str
    diff: str
    after_patch: str | None
    path: Path


def bundled_bench_dir() -> Path:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[1] / "bundled" / "review_bench",
        Path.cwd() / "tests" / "fixtures" / "review_bench",
    ]
    for parent in here.parents:
        candidates.append(parent / "tests" / "fixtures" / "review_bench")
    for candidate in candidates:
        if candidate.is_dir() and any(candidate.glob("*.json")):
            return candidate
    return DEFAULT_DIR


def load_cases(directory: Path | None = None) -> list[BenchCase]:
    root = directory or bundled_bench_dir()
    cases: list[BenchCase] = []
    if not root.is_dir():
        return cases
    for spec in sorted(root.glob("*.json")):
        if spec.name.startswith("_") or spec.name == "scorecard.json":
            continue
        data = json.loads(spec.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "id" not in data:
            continue
        diff_name = str(data.get("diff") or (spec.stem + ".diff"))
        diff_path = spec.with_name(diff_name)
        if not diff_path.is_file():
            continue
        after = data.get("after_patch")
        after_text = None
        if after:
            after_path = spec.with_name(str(after))
            if after_path.is_file():
                after_text = after_path.read_text(encoding="utf-8")
        cases.append(
            BenchCase(
                case_id=str(data["id"]),
                kind=str(data.get("kind") or "positive"),
                languages=list(data.get("languages") or ["python"]),
                heuristic=bool(data.get("heuristic", True)),
                must_rules=list(
                    data.get("must_rules") or data.get("expected_rules") or []
                ),
                must_not_rules=list(data.get("must_not_rules") or []),
                max_findings=data.get("max_findings"),
                needles=list(data.get("needles") or []),
                rationale=str(data.get("rationale") or ""),
                diff=diff_path.read_text(encoding="utf-8"),
                after_patch=after_text,
                path=spec,
            )
        )
    return cases


def score_findings(case: BenchCase, findings: list[Finding]) -> dict[str, Any]:
    rules = {item.rule for item in findings if item.rule and item.rule != "languages"}
    counted = [item for item in findings if item.rule != "languages"]
    missing = [rule for rule in case.must_rules if rule not in rules]
    banned = [rule for rule in case.must_not_rules if rule in rules]
    volume_ok = True
    if case.max_findings is not None:
        volume_ok = len(counted) <= int(case.max_findings)
    if case.kind == "hard_negative":
        leaked = [rule for rule in ("unsafe-api", "security-gate") if rule in rules]
        if case.must_rules:
            leaked = [rule for rule in case.must_rules if rule in rules]
        ok = not leaked and not banned and volume_ok
    else:
        ok = not missing and not banned and volume_ok
    needle_hits = 0
    if case.needles:
        blob = " ".join(item.message for item in counted).lower()
        needle_hits = sum(1 for needle in case.needles if needle.lower() in blob)
    return {
        "id": case.case_id,
        "kind": case.kind,
        "ok": ok,
        "missing_rules": missing,
        "banned_rules": banned,
        "volume": len(counted),
        "volume_ok": volume_ok,
        "needle_hits": needle_hits,
        "needles": len(case.needles),
        "rules": sorted(rules),
    }


def run_heuristic_suite(
    directory: Path | None = None,
    *,
    closed_loop: bool = True,
    tmp: Path | None = None,
) -> dict[str, Any]:
    cases = [item for item in load_cases(directory) if item.heuristic]
    results: list[dict[str, Any]] = []
    for case in cases:
        findings = enrich_findings(heuristic_review(case.diff, case.languages, []))
        row = score_findings(case, findings)
        if (
            closed_loop
            and case.after_patch
            and case.kind == "positive"
            and tmp is not None
        ):
            row["closed_loop"] = _closed_loop(tmp, case, findings)
        results.append(row)
    positives = [item for item in results if item["kind"] == "positive"]
    negatives = [item for item in results if item["kind"] == "hard_negative"]
    caught = sum(1 for item in positives if item["ok"])
    quiet = sum(1 for item in negatives if item["ok"])
    return {
        "suite": "reviewbench",
        "cases": len(results),
        "positives": len(positives),
        "hard_negatives": len(negatives),
        "recall": round(caught / len(positives), 4) if positives else None,
        "hard_negative_pass": round(quiet / len(negatives), 4) if negatives else None,
        "failed": [item["id"] for item in results if not item["ok"]],
        "results": results,
    }


def _closed_loop(tmp: Path, case: BenchCase, findings: list[Finding]) -> dict[str, Any]:
    target = next((item for item in findings if item.rule in case.must_rules), None)
    if target is None or not case.after_patch:
        return {"status": "skipped"}
    work = tmp / case.case_id
    work.mkdir(parents=True, exist_ok=True)
    if target.path:
        dest = work / target.path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(_new_side(case.diff, target.path), encoding="utf-8")
        target.patch = case.after_patch
        status = apply_finding(work, target)
        after = heuristic_review(_diff_from_tree(work, target.path), case.languages, [])
        gone = fingerprint(target, bucket=1) not in {
            fingerprint(item, bucket=1) for item in after
        }
        return {"status": status, "resolved": gone}
    return {"status": "no-path"}


def _new_side(diff: str, path: str) -> str:
    lines: list[str] = []
    current = None
    for raw in diff.splitlines():
        if raw.startswith("+++ b/"):
            current = raw[6:].strip()
            continue
        if current != path:
            continue
        if (raw.startswith("+") and not raw.startswith("+++")) or raw.startswith(" "):
            lines.append(raw[1:])
    return "\n".join(lines) + ("\n" if lines else "")


def _diff_from_tree(root: Path, rel: str) -> str:
    text = (root / rel).read_text(encoding="utf-8")
    body = "\n".join(f"+{line}" for line in text.splitlines())
    return f"diff --git a/{rel} b/{rel}\n--- a/{rel}\n+++ b/{rel}\n@@ -0,0 +1,{len(text.splitlines())} @@\n{body}\n"


def require_contract(findings: list[Finding]) -> list[str]:
    """Return field names missing from the finding contract."""
    missing: list[str] = []
    for item in findings:
        if item.rule == "languages":
            continue
        if not item.message:
            missing.append(f"{item.rule}:message")
        if not item.reason:
            missing.append(f"{item.rule}:reason")
        if not item.suggestion:
            missing.append(f"{item.rule}:suggestion")
        if not item.verify:
            missing.append(f"{item.rule}:verify")
        if item.path and item.line and not item.snippet:
            # snippet needs a real file; allow missing on synthetic diffs
            pass
    return missing
