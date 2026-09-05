"""Public third-party eval adapters (Martian CRB + reconstructed Macroscope samples).

Macroscope's 118-bug set is not published as a downloadable corpus. Their
engineering post documents one sample (apache/commons-math GCD overflow). We
reconstruct that sample here from the public description and Apache-2.0 source
shape, and we fetch Martian's MIT-licensed golden comments for an
apples-to-apples public comparison against Macroscope, Bugbot, Greptile, and
Sourcery on the same PRs.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

MARTIAN_RAW = (
    "https://raw.githubusercontent.com/withmartian/code-review-benchmark/main/"
    "offline/golden_comments"
)
MARTIAN_FILES = (
    "sentry.json",
    "grafana.json",
    "cal.json",
    "discourse.json",
    "keycloak.json",
)
MACROSCOPE_SAMPLE = {
    "id": "macroscope-commons-math-gcd",
    "source": "https://macroscope.com/blog/code-review-benchmark",
    "repository": "https://github.com/apache/commons-math",
    "fix_commit": "dabf3a5beb9ab697d570154b9961078a8586c787",
    "introducing_commit": "746892442f75845426e16f258d42498ad1de154b",
    "description": (
        "MathUtils.gcd incorrectly detects zero operands by testing u * v == 0, "
        "which can overflow to zero for non-zero inputs (e.g., 65536 * 65536)."
    ),
    "needles": ["overflow", "gcd", "zero", "u * v"],
}


def cache_dir(root: Path) -> Path:
    path = root / ".quality-reports" / "eval"
    path.mkdir(parents=True, exist_ok=True)
    return path


def download_martian(root: Path, *, force: bool = False) -> dict[str, Any]:
    dest = cache_dir(root) / "martian"
    dest.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    errors: list[str] = []
    for name in MARTIAN_FILES:
        path = dest / name
        if path.is_file() and not force:
            saved.append(name)
            continue
        url = f"{MARTIAN_RAW}/{name}"
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                body = response.read()
            path.write_bytes(body)
            saved.append(name)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            errors.append(f"{name}: {exc}")
    catalog = load_martian_catalog(dest)
    (dest / "catalog.json").write_text(
        json.dumps(catalog, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "suite": "martian",
        "license": "MIT",
        "citation": "https://github.com/withmartian/code-review-benchmark",
        "dir": str(dest),
        "files": saved,
        "prs": len(catalog),
        "goldens": sum(len(item["comments"]) for item in catalog),
        "errors": errors,
        "note": (
            "Macroscope's 118-bug JSON is not public. Martian CRB is the "
            "open apples-to-apples set (includes Macroscope, Bugbot, Greptile, "
            "Sourcery reviews on the same 50 PRs)."
        ),
    }


def load_martian_catalog(directory: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not directory.is_dir():
        return rows
    for path in sorted(directory.glob("*.json")):
        if path.name in {"catalog.json", "score.json"}:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, list):
            continue
        for item in payload:
            if not isinstance(item, dict):
                continue
            comments = []
            for comment in item.get("comments") or []:
                if isinstance(comment, dict) and comment.get("comment"):
                    comments.append(
                        {
                            "comment": comment["comment"],
                            "severity": comment.get("severity"),
                            "category": comment.get("category"),
                        }
                    )
            rows.append(
                {
                    "repo_file": path.name,
                    "title": item.get("pr_title"),
                    "url": item.get("original_url") or item.get("url"),
                    "comments": comments,
                }
            )
    return rows


def score_against_goldens(
    findings: list[dict[str, Any]],
    goldens: list[dict[str, Any]],
) -> dict[str, Any]:
    """Lexical overlap judge (no LLM). A golden hits if enough tokens overlap."""
    messages = [str(item.get("message") or "") for item in findings]
    matched = 0
    details: list[dict[str, Any]] = []
    for golden in goldens:
        text = str(golden.get("comment") or "")
        hit = _overlap(text, messages)
        if hit:
            matched += 1
        details.append({"golden": text[:180], "matched": bool(hit)})
    extra = max(0, len(findings) - matched)
    recall = round(matched / len(goldens), 4) if goldens else None
    precision = round(matched / len(findings), 4) if findings else None
    return {
        "goldens": len(goldens),
        "findings": len(findings),
        "matched": matched,
        "unmatched_findings": extra,
        "recall": recall,
        "precision": precision,
        "details": details[:40],
    }


def macroscope_reconstructed() -> dict[str, Any]:
    return {
        "suite": "macroscope-reconstructed",
        "public_json": False,
        "reason": (
            "Macroscope published methodology and one sample (commons-math GCD "
            "overflow) but not the 118-row dataset. Use Martian CRB for a public "
            "head-to-head that already scored Macroscope."
        ),
        "sample": MACROSCOPE_SAMPLE,
        "compare_with": "https://github.com/withmartian/code-review-benchmark",
    }


def llm_eval_enabled() -> bool:
    flag = os.environ.get("QUALITY_REVIEW_EVAL", "").strip().lower()
    if flag in {"1", "true", "yes"}:
        return True
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY"))


def _overlap(golden: str, messages: list[str]) -> bool:
    tokens = {part for part in _tokens(golden) if len(part) > 3}
    if not tokens:
        return False
    need = max(2, min(4, len(tokens) // 8 or 2))
    for message in messages:
        got = _tokens(message)
        if len(tokens & got) >= need:
            return True
    return False


def _tokens(text: str) -> set[str]:
    return {
        part.lower()
        for part in text.replace("/", " ").replace(".", " ").split()
        if part
    }
