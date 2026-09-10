"""Finding explanation template and diff Q&A helpers."""

from __future__ import annotations

from quality_gates.models import Finding
from quality_gates.review.severity import taxonomy_level


def explain_finding(item: Finding) -> str:
    level = taxonomy_level(item)
    speculative = (item.confidence or "").upper() == "LOW"
    lines = [
        f"**{item.rule or 'review'}** ({item.severity} · {level}"
        + (" · speculative" if speculative else "")
        + ")",
        "",
        f"What is wrong: {item.message}",
    ]
    if item.reason:
        lines.append(f"Why it matters here: {item.reason}")
    evidence = item.snippet or (f"{item.path}:{item.line}" if item.path else "")
    if evidence:
        lines.append(f"Evidence: `{evidence}`")
    lines.append(f"Confidence: {item.confidence or 'HIGH'}")
    if item.suggestion:
        lines.append(f"Smallest safe fix: {item.suggestion}")
    return "\n".join(lines)


def explain_diff(question: str, paths: list[str], related: str = "") -> str:
    topic = question.strip() or "What does this change do?"
    files = ", ".join(paths[:12]) or "the current diff"
    extra = f"\n\nRelated context:\n{related}" if related else ""
    return f"{topic}\n\nThis explanation is grounded in {files}.{extra}\n"
