"""PR-blocking policy: observe, adopt (ratchet vs baseline), or enforce.

Old repos should see every finding without turning the first PR into a 400-file
rewrite. New issues still fail once a baseline exists.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quality_gates.config import POLICIES, QualityConfig, is_pr_event
from quality_gates.github_comment import post_pr_comment
from quality_gates.models import Finding, GateResult
from quality_gates.report import build_digest, performance_bullets

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
    """Stable defect identity, independent of a harmless line-number shift."""
    path = (finding.path or "").replace("\\", "/")
    evidence = "\n".join(
        part.strip() for part in (finding.message, finding.snippet or "") if part
    )
    digest = hashlib.sha256(evidence.encode("utf-8")).hexdigest()[:16]
    return f"{finding.gate}|{finding.rule or ''}|{digest}|{path}"


def error_fingerprints(results: list[GateResult]) -> list[str]:
    return sorted(identity for _finding, identity in _error_identities(results))


def _error_identities(results: list[GateResult]) -> list[tuple[Finding, str]]:
    """Keep repeated same-rule findings separate without making line shifts new."""
    grouped: dict[str, list[Finding]] = {}
    for result in results:
        for item in result.findings:
            if item.severity == "error":
                grouped.setdefault(fingerprint(item), []).append(item)
    identities: list[tuple[Finding, str]] = []
    for base, findings in grouped.items():
        ordered = sorted(
            findings,
            key=lambda item: (item.line is None, item.line or 0, item.column or 0),
        )
        for occurrence, item in enumerate(ordered, start=1):
            identities.append(
                (item, base if occurrence == 1 else f"{base}#{occurrence}")
            )
    return identities


def _trusted_base_ref() -> str | None:
    base = os.environ.get("QUALITY_TRUSTED_BASE")
    if not base and is_pr_event():
        base = os.environ.get("GITHUB_BASE_REF")
        if base and not base.startswith("origin/"):
            base = f"origin/{base}"
    return base


def _load_base_baseline(
    root: Path, config: QualityConfig
) -> tuple[bool, dict[str, Any] | None]:
    base = _trusted_base_ref()
    if not base:
        return False, None
    try:
        verify = subprocess.run(
            ["git", "rev-parse", "--verify", base],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=3,
        )
        if verify.returncode != 0:
            return False, None
        rel = baseline_path(root, config).relative_to(root).as_posix()
        res = subprocess.run(
            ["git", "show", f"{base}:{rel}"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
        if res.returncode == 0:
            data = json.loads(res.stdout)
            return True, data if isinstance(data, dict) else None
        return True, None
    except (OSError, json.JSONDecodeError, ValueError, subprocess.TimeoutExpired):
        return False, None


def load_baseline(root: Path, config: QualityConfig) -> dict[str, Any] | None:
    is_pr, base_data = _load_base_baseline(root, config)
    if is_pr and base_data is not None:
        return base_data
    path = baseline_path(root, config)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def baseline_state(
    root: Path, config: QualityConfig
) -> tuple[str, dict[str, Any] | None]:
    """Differentiate first onboarding from deleted or malformed evidence."""
    path = baseline_path(root, config)
    local_data = None
    if path.is_file():
        try:
            local_data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "invalid", None
        if not isinstance(local_data, dict) or not isinstance(
            local_data.get("fingerprints", []), list
        ):
            return "invalid", None

    is_pr, base_data = _load_base_baseline(root, config)
    if is_pr:
        if base_data is not None:
            if isinstance(base_data.get("fingerprints", []), list):
                return "valid", base_data
            return "invalid", None
        if not path.is_file():
            if _tracked(root, path):
                return "missing", None
            return "initial", None
        return "valid", local_data

    if not path.is_file():
        if _tracked(root, path):
            return "missing", None
        return "initial", None
    return "valid", local_data


def _tracked(root: Path, path: Path) -> bool:
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        return False
    try:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", rel],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


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
        # A ratchet replaces the exemption inventory with freshly observed
        # defects. Retaining previous entries permanently grandfathered repairs.
        old_cov = previous.get("coverage_line")
        if isinstance(old_cov, (int, float)) and coverage is not None:
            coverage = max(float(old_cov), coverage)
        elif coverage is None and isinstance(old_cov, (int, float)):
            coverage = float(old_cov)
    payload = {
        "schema_version": "1.0.0",
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
    _apply_exceptions(results, config)
    policy = effective_policy(config)
    if policy == "enforce" or not results:
        return results, policy

    state, baseline = baseline_state(root, config)
    if policy == "adopt" and state in {"missing", "invalid"}:
        finding = Finding(
            gate="policy",
            rule=f"baseline-{state}",
            message=(
                f"required baseline {config.policy_baseline!r} is {state}; "
                "restore it or create an explicit first-time baseline"
            ),
            severity="error",
        )
        target = results[0]
        target.findings.append(finding)
        target.status = "fail"
        target.notes.append(f"policy=adopt: baseline evidence is {state}")
        return results, policy
    if policy == "observe" or (policy == "adopt" and state == "initial"):
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
    identities = {id(item): identity for item, identity in _error_identities(results)}
    for result in results:
        if result.name == "coverage":
            new_count += _adopt_coverage(result, current_cov, base_cov)
            continue
        if result.name == "test":
            # Legacy adoption may grandfather attributable static debt, never a
            # fresh failed or incomplete execution result.
            new_count += result.error_count()
            continue
        if result.status != "fail":
            continue
        kept = 0
        for item in result.findings:
            if item.severity != "error":
                continue
            if identities.get(id(item), fingerprint(item)) in known:
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


def _apply_exceptions(results: list[GateResult], config: QualityConfig) -> None:
    """Apply narrow, expiring, attributable exceptions before policy evaluation."""
    for exception in config.policy_exceptions:
        if not _valid_exception(exception):
            continue
        for result in results:
            for finding in result.findings:
                if finding.severity != "error" or not _matches(exception, finding):
                    continue
                finding.severity = "warning"
                finding.reason = (
                    f"approved exception by {exception['owner']}: {exception['reason']} "
                    f"(expires {exception['expires']})"
                )
            if result.status == "fail" and not result.error_count():
                result.status = "pass"
                result.notes.append(
                    "all blocking findings covered by active policy exception"
                )


def _valid_exception(exception: dict[str, Any]) -> bool:
    required = ("owner", "approved_by", "reason", "expires")
    if any(
        not isinstance(exception.get(key), str) or not exception[key].strip()
        for key in required
    ):
        return False
    try:
        expires = datetime.fromisoformat(exception["expires"].replace("Z", "+00:00"))
    except ValueError:
        return False
    if expires.tzinfo is None:
        return False
    return expires > datetime.now(UTC)


def _matches(exception: dict[str, Any], finding: Finding) -> bool:
    for key, value in (
        ("gate", finding.gate),
        ("rule", finding.rule),
        ("path", finding.path),
    ):
        expected = exception.get(key)
        if expected is not None and expected != value:
            return False
    return True


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
    digest = build_digest(results, policy=policy, report_dir=root / ".quality-reports")
    lines = [
        "## Quality report",
        "",
        f"Policy: `{policy}` · this job **"
        + ("fails the PR" if digest.failed else "does not block merge")
        + f"**. Errors: **{digest.errors}**. Warnings: **{digest.warnings}**.",
        "",
        "| Gate | Status | Errors | Warnings |",
        "| --- | --- | ---: | ---: |",
    ]
    for item in digest.results:
        lines.append(
            f"| {item.name} | {item.status} | {item.error_count()} | {item.warning_count()} |"
        )
    lines += ["", "### Performance", ""]
    lines.extend(performance_bullets(digest.performance, digest.results))
    issues = [finding for finding in digest.issues() if finding.severity == "error"]
    if issues:
        lines += ["", "### Blocking", ""]
        for finding in issues[:30]:
            loc = finding.path or finding.gate
            if finding.line:
                loc = f"{loc}:{finding.line}"
            lines.append(f"- `{loc}` — {finding.message}")
    if digest.recommendations:
        lines += ["", "### Recommendations", ""]
        for item in digest.recommendations[:8]:
            cmd = f" `{item.command}`" if item.command else ""
            lines.append(f"- **{item.priority} — {item.title}.** {item.detail}{cmd}")
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
    lines.append(
        f"Baseline: `{config.policy_baseline}`. "
        "Full printout: `.quality-reports/quality-report.md` / `quality-report.html`."
    )
    lines.append("")
    lines.append("_Posted by quality-gates._")
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
