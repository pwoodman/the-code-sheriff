from __future__ import annotations

import json
from pathlib import Path

from quality_gates.config import QualityConfig, is_pr_event
from quality_gates.models import Finding, GateResult
from quality_gates.review.context import (
    active_rules,
    audit_digest,
    changed_paths,
    collect_diff,
    impact_digest,
    new_side_lines,
    prior_digest,
    related_files,
    render_rules,
)
from quality_gates.review.heuristic import heuristic_review
from quality_gates.review.llm import resolve_client, run_llm_review, validate_findings
from quality_gates.review.parse import drop_style_nits, merge_findings
from quality_gates.review.resolve import resolution_stats, rotate_previous

STANDARDS_BRIEF = """
Mechanical gates already own format, lint, and copy-paste. Do not mention style.
Review for correctness, error handling, tests, authorization, injection, secrets,
and blast radius (callers of changed symbols that were not updated).
""".strip()


def run_review(
    root: Path,
    config: QualityConfig,
    languages: list[str],
    *,
    base: str | None,
    post: bool,
    prior: list[GateResult] | None = None,
) -> GateResult:
    if config.ai_review == "never":
        return GateResult(name="review", status="skip", notes=["ai_review = never"])
    if config.ai_review == "pr-only" and not is_pr_event() and not base:
        return GateResult(
            name="review",
            status="skip",
            notes=[
                "AI review runs on pull requests (set ai_review = always to override)",
            ],
        )

    diff = collect_diff(root, base, config.max_diff_bytes)
    if not diff.strip():
        return GateResult(
            name="review",
            status="skip",
            notes=["no diff against the review base"],
        )

    prior = prior or []
    paths = changed_paths(diff)
    heuristic = heuristic_review(diff, languages, prior)
    rules = active_rules(root, config, paths)
    related = related_files(root, config, paths)
    allowed = set(paths) | {path for path, _text in related}
    prompt = _prompt(
        diff=diff,
        languages=languages,
        heuristic=heuristic,
        prior=prior,
        root=root,
        rules=rules,
        related=related,
    )

    mode = (config.review_mode or "auto").lower()
    client = None if mode == "heuristic" else resolve_client(config)
    provider = "heuristic"
    llm_summary = ""
    llm_findings: list[Finding] = []
    if client is not None:
        llm_summary, llm_findings, provider = run_llm_review(
            client,
            prompt,
            mode=mode,
            config=config,
            root=root,
            diff=diff,
        )
        llm_findings = validate_findings(
            client, llm_findings, enabled=config.review_validate
        )

    llm_findings = drop_style_nits(llm_findings, allowed_paths=allowed or None)
    heuristic_kept = [item for item in heuristic if item.rule not in {"languages"}]
    findings = merge_findings(heuristic_kept, llm_findings)
    findings = drop_style_nits(findings, allowed_paths=None)

    report_dir = root / ".quality-reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    previous = rotate_previous(report_dir)
    resolution = resolution_stats(previous, findings)
    payload = {
        "schema_version": "1.0.0",
        "provider": provider,
        "mode": mode if client else "heuristic",
        "summary": llm_summary,
        "languages": languages,
        "rules": [rule.source for rule in rules],
        "related_files": [path for path, _text in related],
        "resolution": resolution,
        "findings": [_finding_dict(item) for item in findings],
    }
    (report_dir / "review.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    body = render_review(
        findings,
        summary=llm_summary,
        provider=provider,
        languages=languages,
        resolution=resolution,
        rules=len(rules),
    )
    (report_dir / "review.md").write_text(body, encoding="utf-8")
    notes = [
        f"provider: {provider}",
        f"mode: {mode if client else 'heuristic'}",
        f"rules: {len(rules)}",
        f"related_files: {len(related)}",
        "wrote .quality-reports/review.json and review.md",
    ]
    if resolution.get("rate") is not None:
        notes.append(
            f"resolution: {resolution['resolved']}/{resolution['previous']} "
            f"({resolution['rate']})"
        )
    if post:
        from quality_gates.github_comment import post_review

        notes.extend(
            post_review(
                body,
                findings,
                diff_lines=new_side_lines(diff),
                inline=config.review_inline,
                check_run=config.review_check_run,
                fail_on_review="review" in config.fail_on,
            )
        )

    return GateResult(name="review", status="pass", findings=findings, notes=notes)


def render_review(
    findings: list[Finding],
    *,
    summary: str,
    provider: str,
    languages: list[str],
    resolution: dict[str, object],
    rules: int,
) -> str:
    lines = [
        "## AI code review",
        "",
        f"Provider: `{provider}` · languages: `{', '.join(languages) or 'none'}`"
        f" · rules: `{rules}`",
        "",
    ]
    rate = resolution.get("rate")
    if rate is not None:
        lines.extend(
            [
                f"Resolution vs previous review: **{resolution.get('resolved')}** of "
                f"**{resolution.get('previous')}** findings gone "
                f"(rate `{rate}`). New: **{resolution.get('new')}**.",
                "",
            ]
        )
    if summary:
        lines.extend([summary.strip(), ""])
    blockers = [item for item in findings if item.severity == "error"]
    warnings = [item for item in findings if item.severity == "warning"]
    infos = [item for item in findings if item.severity == "info"]
    if blockers:
        lines.append("### Blocking")
        lines.append("")
        lines.extend(_bullets(blockers))
        lines.append("")
    if warnings:
        lines.append("### Please consider")
        lines.append("")
        lines.extend(_bullets(warnings))
        lines.append("")
    if infos and not summary:
        lines.append("### Notes")
        lines.append("")
        lines.extend(_bullets(infos))
        lines.append("")
    if provider == "heuristic" and not summary:
        lines.append(
            '_No LLM key configured (or `quality.review.mode = "heuristic"` / '
            "offline). Set `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or use GitHub "
            "Models on Actions. Heuristic flags, impact/audit context, and "
            "`.quality/rules` still run._"
        )
    return "\n".join(lines).strip() + "\n"


def _bullets(items: list[Finding]) -> list[str]:
    lines = []
    for item in items:
        loc = (
            f"{item.path}:{item.line}"
            if item.path and item.line
            else (item.path or "repo")
        )
        extra = f" — {item.suggestion}" if item.suggestion else ""
        lines.append(f"- `{loc}` {item.message}{extra}")
    return lines


def _finding_dict(item: Finding) -> dict[str, object]:
    payload: dict[str, object] = {
        "severity": item.severity,
        "message": item.message,
        "rule": item.rule,
    }
    if item.path:
        payload["path"] = item.path
    if item.line is not None:
        payload["line"] = item.line
    if item.suggestion:
        payload["suggestion"] = item.suggestion
    return payload


def _prompt(
    *,
    diff: str,
    languages: list[str],
    heuristic: list[Finding],
    prior: list[GateResult],
    root: Path,
    rules,
    related: list[tuple[str, str]],
) -> str:
    bullets = "\n".join(
        f"- [{item.severity}] {item.path or ''}:{item.line or ''} {item.message}"
        for item in heuristic
        if item.rule != "languages"
    )
    related_block = (
        "\n\n".join(f"### {path}\n```\n{text}\n```" for path, text in related)
        or "- none"
    )
    extra = (
        "\n\n".join(
            part
            for part in (prior_digest(prior), impact_digest(root), audit_digest(root))
            if part
        )
        or "- none"
    )
    return f"""You are reviewing a change for bugs formatters and linters cannot prove.
Languages: {", ".join(languages) or "unknown"}.
{STANDARDS_BRIEF}

Custom repo rules (enforce these; they outrank generic style advice):
{render_rules(rules)}

Heuristic flags (do not repeat unless you can add new evidence):
{bullets or "- none"}

Prior gates, impact, and audit (do not restate format/lint):
{extra}

Related files from the import graph (callers/callees, not the full repo):
{related_block}

Diff:
```
{diff}
```
"""
