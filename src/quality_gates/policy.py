"""PR-blocking policy: observe, adopt (ratchet vs baseline), or enforce.

Old repos should see every finding without turning the first PR into a 400-file
rewrite. New issues still fail once a baseline exists.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from quality_gates.config import POLICIES, QualityConfig, is_pr_event
from quality_gates.github_comment import post_pr_comment
from quality_gates.models import Finding, GateResult

DEFAULT_BASELINE = ".quality-baseline.json"
COVERAGE_SLACK = 1.0


def effective_policy(config: QualityConfig) -> str:
    raw = os.environ.get("QUALITY_POLICY", "").strip().lower()
    if raw in POLICIES:
        return raw
    policy = (config.policy or "adopt").strip().lower()
    return policy if policy in POLICIES else "adopt"


def baseline_path(root: Path, config: QualityConfig) -> Path:
    rel = config.policy_baseline or DEFAULT_BASELINE
    path = Path(rel)
    return path if path.is_absolute() else root / path


def fingerprint(finding: Finding) -> str:
    path = (finding.path or "").replace("\\", "/")
    return f"{finding.gate}|{finding.rule or ''}|{path}"


def error_fingerprints(results: list[GateResult]) -> list[str]:
    seen: set[str] = set()
    for result in results:
        for item in result.findings:
            if item.severity != "error":
                continue
            seen.add(fingerprint(item))
    return sorted(seen)


def load_baseline(root: Path, config: QualityConfig) -> dict[str, Any] | None:
    path = baseline_path(root, config)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def write_baseline(
    root: Path,
    config: QualityConfig,
    results: list[GateResult] | None = None,
    *,
    ratchet: bool = False,
) -> Path:
    path = baseline_path(root, config)
    previous = load_baseline(root, config) if ratchet else None
    fps = set(error_fingerprints(results or _results_from_reports(root)))
    coverage = _coverage_percent(root)
    if previous:
        fps |= set(previous.get("fingerprints") or [])
        old_cov = previous.get("coverage_line")
        if isinstance(old_cov, (int, float)) and coverage is not None:
            coverage = max(float(old_cov), coverage)
        elif coverage is None and isinstance(old_cov, (int, float)):
            coverage = float(old_cov)
    payload = {
        "version": 1,
        "policy": "adopt",
        "coverage_line": coverage,
        "fingerprints": sorted(fps),
        "note": (
            "Grandfathered findings. adopt fails only on new fingerprints or a "
            "coverage drop. Run `quality baseline --ratchet` after you fix issues "
            "to raise the floor; never shrink this file to hide new defects."
        ),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def apply_policy(
    results: list[GateResult], root: Path, config: QualityConfig
) -> tuple[list[GateResult], str]:
    policy = effective_policy(config)
    if policy == "enforce" or not results:
        return results, policy

    baseline = load_baseline(root, config)
    if policy == "observe" or (policy == "adopt" and baseline is None):
        reason = (
            f"policy={policy}: findings are visible but the job does not fail. "
            "Commit `quality baseline` to ratchet (adopt) or set policy=enforce."
            if policy == "adopt"
            else "policy=observe: report-only; PRs are not blocked."
        )
        _demote_failures(results, reason)
        return results, policy

    known = {str(item) for item in (baseline or {}).get("fingerprints") or []}
    base_cov = baseline.get("coverage_line") if baseline else None
    current_cov = _coverage_percent(root)
    new_count = 0
    for result in results:
        if result.name == "coverage":
            new_count += _adopt_coverage(result, current_cov, base_cov)
            continue
        if result.status != "fail":
            continue
        kept = 0
        for item in result.findings:
            if item.severity != "error":
                continue
            if fingerprint(item) in known:
                item.severity = "warning"
                if not item.message.startswith("[grandfathered]"):
                    item.message = f"[grandfathered] {item.message}"
            else:
                kept += 1
        if kept == 0:
            result.status = "pass"
            result.notes.append(
                "policy=adopt: existing findings grandfathered vs .quality-baseline.json"
            )
        else:
            result.notes.append(f"policy=adopt: {kept} new finding(s) vs baseline")
            new_count += kept
    if new_count == 0:
        results[0].notes.append(
            "policy=adopt: no new blocking issues vs baseline (coverage ratchet + fingerprints)"
        )
    return results, policy


def maybe_comment_pr(
    results: list[GateResult], root: Path, config: QualityConfig, policy: str
) -> str | None:
    if not config.policy_comment:
        return None
    if os.environ.get("QUALITY_COMMENT", "").lower() in {"0", "false", "no"}:
        return None
    if not is_pr_event() and os.environ.get("QUALITY_PR_NUMBER") is None:
        return None
    body = render_digest(results, policy, root, config)
    note = post_pr_comment(body)
    results[-1].notes.append(note)
    return note


def render_digest(
    results: list[GateResult],
    policy: str,
    root: Path,
    config: QualityConfig,
) -> str:
    failed = [item.name for item in results if item.status == "fail"]
    warnings = sum(item.warning_count() for item in results)
    errors = sum(item.error_count() for item in results)
    cov = _coverage_percent(root)
    lines = [
        "## Quality gates",
        "",
        f"Policy: `{policy}` · this job **"
        + ("fails the PR" if failed else "does not block merge")
        + "**.",
        "",
        f"Errors (blocking under this policy): **{errors}**. "
        f"Warnings / grandfathered: **{warnings}**.",
        "",
    ]
    if cov is not None:
        lines.append(
            f"Line coverage: **{cov:.1f}%** (industry floor 80%; repo may ratchet)."
        )
        lines.append("")
    lines.append(f"Baseline: `{config.policy_baseline}`")
    lines.append("")
    lines.append("| Gate | Status | Errors | Warnings |")
    lines.append("| --- | --- | ---: | ---: |")
    for item in results:
        lines.append(
            f"| {item.name} | {item.status} | {item.error_count()} | {item.warning_count()} |"
        )
    lines.append("")
    new_errors = [
        finding
        for item in results
        for finding in item.findings
        if finding.severity == "error"
    ]
    if new_errors:
        lines.append("### Blocking")
        lines.append("")
        for finding in new_errors[:30]:
            loc = finding.path or finding.gate
            if finding.line:
                loc = f"{loc}:{finding.line}"
            lines.append(f"- `{loc}` — {finding.message}")
        lines.append("")
    if policy == "adopt":
        lines.append(
            "Grandfathered findings stay warnings until you fix them and run "
            "`quality baseline --ratchet`. New fingerprints or a coverage drop fail the job."
        )
    elif policy == "observe":
        lines.append(
            "Observe mode never fails the check. Switch to `adopt` + a committed "
            "`.quality-baseline.json` when you are ready to ratchet."
        )
    lines.append("")
    lines.append("_Posted by quality-gates. Reports: `.quality-reports/`._")
    return "\n".join(lines) + "\n"


def _demote_failures(results: list[GateResult], reason: str) -> None:
    for result in results:
        if result.status == "fail":
            result.status = "pass"
            result.notes.append(reason)
            for item in result.findings:
                if item.severity == "error":
                    item.severity = "warning"


def _adopt_coverage(result: GateResult, current: float | None, baseline: object) -> int:
    if result.status != "fail":
        return 0
    base = float(baseline) if isinstance(baseline, (int, float)) else None
    if current is None or base is None:
        _demote_failures(
            [result], "policy=adopt: no coverage baseline number; not blocking"
        )
        return 0
    if current + COVERAGE_SLACK >= base:
        result.status = "pass"
        for item in result.findings:
            if item.severity == "error":
                item.severity = "warning"
                item.message = (
                    f"[below industry floor, at/above repo baseline {base:.1f}%] "
                    f"{item.message}"
                )
        result.notes.append(
            f"policy=adopt: coverage {current:.1f}% ≥ baseline {base:.1f}% "
            f"(industry floor still 80%)"
        )
        return 0
    result.notes.append(
        f"policy=adopt: coverage {current:.1f}% dropped below baseline {base:.1f}%"
    )
    return 1


def _coverage_percent(root: Path) -> float | None:
    path = root / ".quality-reports" / "coverage.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = data.get("line_percent")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _results_from_reports(root: Path) -> list[GateResult]:
    path = root / ".quality-reports" / "quality-report.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out: list[GateResult] = []
    for row in data.get("results") or []:
        findings = [
            Finding(
                gate=str(item.get("gate") or row.get("name") or ""),
                message=str(item.get("message") or ""),
                severity=str(item.get("severity") or "error"),
                path=item.get("path"),
                line=item.get("line"),
                rule=item.get("rule"),
            )
            for item in row.get("findings") or []
        ]
        out.append(
            GateResult(
                name=str(row.get("name") or ""),
                status=str(row.get("status") or "pass"),
                findings=findings,
                notes=list(row.get("notes") or []),
            )
        )
    return out
