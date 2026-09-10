"""Token accounting, budgets, retention GC, and latency breakdown."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

COST_FILE = "cost.json"
AUDIT_FILE = "audit.jsonl"
DEFAULT_RATES = {
    "anthropic": 3.0 / 1_000_000,
    "openai": 2.0 / 1_000_000,
    "azure": 2.0 / 1_000_000,
    "gemini": 0.5 / 1_000_000,
    "bedrock": 3.0 / 1_000_000,
    "openrouter": 2.0 / 1_000_000,
    "ollama": 0.0,
}


def empty_cost() -> dict[str, Any]:
    return {
        "runs": [],
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_usd": 0.0,
    }


def load_cost(root: Path) -> dict[str, Any]:
    path = root / ".quality-reports" / COST_FILE
    if not path.is_file():
        return empty_cost()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_cost()
    return data if isinstance(data, dict) else empty_cost()


def estimate_usd(provider: str, tokens: int) -> float:
    rate = DEFAULT_RATES.get((provider or "openai").lower(), 2.0 / 1_000_000)
    return round(tokens * rate, 6)


def record_usage(
    root: Path,
    *,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    workflow: str = "review",
    mode: str = "standard",
) -> dict[str, Any]:
    data = load_cost(root)
    tokens = max(0, input_tokens) + max(0, output_tokens)
    usd = estimate_usd(provider, tokens)
    event = {
        "at": datetime.now(UTC).isoformat(),
        "provider": provider,
        "model": model,
        "workflow": workflow,
        "mode": mode,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "usd": usd,
    }
    data.setdefault("runs", []).append(event)
    data["total_input_tokens"] = int(data.get("total_input_tokens") or 0) + input_tokens
    data["total_output_tokens"] = (
        int(data.get("total_output_tokens") or 0) + output_tokens
    )
    data["total_usd"] = round(float(data.get("total_usd") or 0) + usd, 6)
    _write(root, COST_FILE, data)
    return event


def within_budget(
    root: Path,
    *,
    monthly_cap: float = 0,
    per_pr_tokens: int = 0,
    next_tokens: int = 0,
) -> tuple[bool, str]:
    data = load_cost(root)
    if monthly_cap > 0:
        month = datetime.now(UTC).strftime("%Y-%m")
        spent = sum(
            float(item.get("usd") or 0)
            for item in data.get("runs") or []
            if str(item.get("at") or "").startswith(month)
        )
        if spent >= monthly_cap:
            return False, "monthly cost cap reached"
    if per_pr_tokens > 0:
        last = (data.get("runs") or [{}])[-1]
        used = int(last.get("input_tokens") or 0) + int(last.get("output_tokens") or 0)
        if used + next_tokens > per_pr_tokens:
            return False, "per-PR token budget reached"
    return True, "ok"


def gc_reports(root: Path, *, days: int) -> dict[str, Any]:
    reports = root / ".quality-reports"
    if days <= 0 or not reports.is_dir():
        return {"removed": 0, "kept": 0, "days": days}
    cutoff = time.time() - days * 86400
    removed = 0
    kept = 0
    ephemeral = {"prompts", "logs", "tmp"}
    for path in reports.rglob("*"):
        if not path.is_file():
            continue
        if path.name in {AUDIT_FILE, COST_FILE, "quality-report.json"}:
            kept += 1
            continue
        if path.stat().st_mtime >= cutoff and path.parent.name not in ephemeral:
            kept += 1
            continue
        if path.parent.name in ephemeral or (
            days > 0 and path.stat().st_mtime < cutoff
        ):
            if (
                path.suffix in {".log", ".txt", ".prompt"}
                or path.parent.name in ephemeral
            ):
                path.unlink(missing_ok=True)
                removed += 1
            else:
                kept += 1
        else:
            kept += 1
    return {"removed": removed, "kept": kept, "days": days}


def latency_breakdown(
    *,
    queue_ms: int = 0,
    retrieval_ms: int = 0,
    model_ms: int = 0,
    complete_ms: int | None = None,
) -> dict[str, int]:
    total = (
        complete_ms if complete_ms is not None else queue_ms + retrieval_ms + model_ms
    )
    return {
        "queue_ms": queue_ms,
        "retrieval_ms": retrieval_ms,
        "model_ms": model_ms,
        "complete_ms": total,
    }


def append_audit(root: Path, event: dict[str, Any]) -> None:
    reports = root / ".quality-reports"
    reports.mkdir(parents=True, exist_ok=True)
    payload = dict(event)
    payload.setdefault("at", datetime.now(UTC).isoformat())
    with (reports / AUDIT_FILE).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, separators=(",", ":")) + "\n")


def _write(root: Path, name: str, data: dict[str, Any]) -> None:
    reports = root / ".quality-reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
