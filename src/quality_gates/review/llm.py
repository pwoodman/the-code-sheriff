"""LLM clients and the agentic / ensemble review loop."""

from __future__ import annotations

import json
import os
import random
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from quality_gates.config import QualityConfig
from quality_gates.models import Finding
from quality_gates.review.context import (
    grep_repo,
    read_repo_file,
    split_diff_files,
)
from quality_gates.review.parse import (
    findings_from_payload,
    majority_vote,
    parse_json_object,
)

SYSTEM = (
    "You are an aggressive software reviewer. Investigate every suspicious "
    "pattern: correctness, security, authorization, missing tests, overflow, "
    "error handling, and blast radius. Never restate formatter or linter nits "
    "(Prettier, gofmt, ruff, clippy style, indentation). Prefer concrete "
    "path:line findings with a reason, a fix, and a patch when the replacement "
    "is a few lines. Respond with a single JSON object."
)

SUBMIT_SCHEMA = """
Return JSON only, no markdown:
{
  "action": "submit" | "need",
  "summary": "2-4 sentences",
  "findings": [
    {
      "severity": "error" | "warning" | "info",
      "path": "relative/path",
      "line": 12,
      "rule": "short-rule-id",
      "message": "what is wrong",
      "reason": "why it matters",
      "suggestion": "how to fix",
      "patch": "replacement lines or a tiny unified diff",
      "verify": "command that proves the fix",
      "reproduce": "numbered steps a reviewer can follow to confirm the issue"
    }
  ],
  "files": ["optional extra files to read when action=need"],
  "grep": [{"pattern": "regex", "glob": "*.py"}]
}
Use action=need if a file or search is required to confirm a bug. Err on the
side of investigating. Do not request files already provided. Empty findings
is allowed when the change is truly clean.
""".strip()

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
DEFAULT_OPENAI_MODEL = "gpt-4.1"


@dataclass
class ChatTurn:
    role: str
    content: str


class ChatClient(Protocol):
    name: str

    def complete(
        self,
        messages: list[ChatTurn],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2400,
    ) -> str: ...


class OpenAICompatClient:
    def __init__(self, url: str, token: str, model: str, name: str) -> None:
        self.url = url
        self.token = token
        self.model = model
        self.name = name

    def complete(
        self,
        messages: list[ChatTurn],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2400,
    ) -> str:
        payload = json.dumps(
            {
                "model": self.model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": item.role, "content": item.content} for item in messages
                ],
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            body = json.loads(response.read().decode("utf-8"))
        return str(body["choices"][0]["message"]["content"])


class AnthropicClient:
    def __init__(self, token: str, model: str) -> None:
        self.token = token
        self.model = model
        self.name = "anthropic"

    def complete(
        self,
        messages: list[ChatTurn],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2400,
    ) -> str:
        system = ""
        chat: list[dict[str, str]] = []
        for item in messages:
            if item.role == "system":
                system = item.content
                continue
            role = "assistant" if item.role == "assistant" else "user"
            chat.append({"role": role, "content": item.content})
        payload = json.dumps(
            {
                "model": self.model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system or SYSTEM,
                "messages": chat,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "x-api-key": self.token,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            body = json.loads(response.read().decode("utf-8"))
        parts = body.get("content") or []
        return "".join(
            part.get("text", "") for part in parts if part.get("type") == "text"
        )


def _ollama_client(config: QualityConfig) -> ChatClient | None:
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    from quality_gates.tools import which

    if not which("ollama") and "OLLAMA_HOST" not in os.environ:
        return None
    model = config.review_model or os.environ.get("OLLAMA_MODEL") or "llama3.2"
    return OpenAICompatClient(
        f"{host}/v1/chat/completions",
        os.environ.get("OLLAMA_API_KEY", "ollama"),
        model,
        "ollama",
    )


def resolve_client(config: QualityConfig) -> ChatClient | None:
    provider = (config.review_provider or "auto").lower()
    if provider in {"off", "heuristic", "none"}:
        return None
    if config.offline or provider == "ollama":
        return _ollama_client(config)
    openai_key = os.environ.get("OPENAI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if provider == "auto":
        if anthropic_key:
            provider = "anthropic"
        elif openai_key:
            provider = "openai"
        else:
            return _ollama_client(config)
    if provider == "github-models":
        # Retired 2026-07-30. GITHUB_TOKEN on Actions is not an inference key.
        return None
    if provider == "anthropic" and anthropic_key:
        model = config.review_model or os.environ.get(
            "ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL
        )
        return AnthropicClient(anthropic_key, model)
    if provider == "openai" and openai_key:
        model = config.review_model or os.environ.get(
            "OPENAI_MODEL", DEFAULT_OPENAI_MODEL
        )
        return OpenAICompatClient(
            "https://api.openai.com/v1/chat/completions",
            openai_key,
            model,
            "openai",
        )
    return None


def _http_error_detail(exc: urllib.error.HTTPError, client: ChatClient) -> str:
    if exc.code == 410:
        return (
            "HTTP 410: GitHub Models was retired on 2026-07-30; "
            "set ANTHROPIC_API_KEY or OPENAI_API_KEY"
        )
    body = ""
    try:
        body = exc.read().decode("utf-8", errors="replace").strip()[:300]
    except OSError:
        body = ""
    model = getattr(client, "model", "") or ""
    parts = [f"HTTP {exc.code}: {exc.reason or exc}"]
    if model:
        parts.append(f"model={model}")
    if body:
        parts.append(body)
    return "; ".join(parts)


def run_llm_review(
    client: ChatClient,
    prompt: str,
    *,
    mode: str,
    config: QualityConfig,
    root,
    diff: str,
) -> tuple[str, list[Finding], str]:
    mode = (mode or "auto").lower()
    if mode == "auto":
        mode = "agentic"
    try:
        if mode == "ensemble":
            return _ensemble(client, prompt, diff, config)
        if mode == "single":
            summary, findings = _single(client, prompt)
            return summary, findings, "single"
        summary, findings = _agentic(client, prompt, config, root)
        return summary, findings, "agentic"
    except urllib.error.HTTPError as exc:
        return (
            f"LLM review failed ({_http_error_detail(exc, client)}); "
            "heuristic findings still apply.",
            [],
            "heuristic",
        )
    except (
        urllib.error.URLError,
        TimeoutError,
        RuntimeError,
        json.JSONDecodeError,
        KeyError,
    ) as exc:
        return (
            f"LLM review failed ({exc}); heuristic findings still apply.",
            [],
            "heuristic",
        )


def validate_findings(
    client: ChatClient | None,
    findings: list[Finding],
    *,
    enabled: bool,
    diff: str = "",
    root: Path | None = None,
) -> list[Finding]:
    if not enabled or client is None or not findings:
        return findings
    payload = {
        "findings": [
            {
                "severity": item.severity,
                "path": item.path,
                "line": item.line,
                "rule": item.rule,
                "message": item.message,
            }
            for item in findings
        ]
    }
    diff_context = ""
    if diff:
        clipped = diff[:6000] if len(diff) > 6000 else diff
        diff_context = f"\n\nChanged diff context:\n```diff\n{clipped}\n```\n"
    prompt = (
        "Verify candidate findings against the provided code and diff context. "
        "Confirm that each blocking finding identifies a real defect, clear trigger, "
        "consequence, and exact location. Model agreement alone is not sufficient; "
        "findings must correspond to actual behavior in the changed lines or their consumers. "
        "Drop false positives, unverified claims, and formatter/linter nits. "
        "Keep only bugs you would block a merge for, or high-value warnings. "
        'Return JSON {"action":"submit","summary":"","findings":[...]} using the same shape. '
        "Do not invent new issues."
        f"{diff_context}\nCandidate findings:\n" + json.dumps(payload)
    )
    try:
        text = client.complete(
            [ChatTurn("system", SYSTEM), ChatTurn("user", prompt)],
            temperature=0,
            max_tokens=1600,
        )
    except (
        urllib.error.URLError,
        TimeoutError,
        RuntimeError,
        json.JSONDecodeError,
        KeyError,
    ):
        return findings
    parsed = parse_json_object(text)
    if not parsed:
        return findings
    _summary, kept = findings_from_payload(parsed)
    return kept or findings


def _single(client: ChatClient, prompt: str) -> tuple[str, list[Finding]]:
    text = client.complete(
        [ChatTurn("system", SYSTEM), ChatTurn("user", prompt + "\n\n" + SUBMIT_SCHEMA)],
        max_tokens=2400,
    )
    parsed = parse_json_object(text)
    if not parsed:
        return text.strip()[:2000], []
    return findings_from_payload(parsed)


def _ensemble(
    client: ChatClient,
    prompt: str,
    diff: str,
    config: QualityConfig,
) -> tuple[str, list[Finding], str]:
    files = split_diff_files(diff)
    passes = max(2, min(8, config.review_passes))
    collected: list[list[Finding]] = []
    summaries: list[str] = []
    for index in range(passes):
        ordered = list(files)
        rng = random.Random(index + 1)
        rng.shuffle(ordered)
        shuffled = "".join(body for _path, body in ordered) if ordered else diff
        user = prompt.replace(diff, shuffled, 1) if diff and diff in prompt else prompt
        user += f"\n\nPass {index + 1}/{passes}. {SUBMIT_SCHEMA}"
        text = client.complete(
            [ChatTurn("system", SYSTEM), ChatTurn("user", user)],
            temperature=0.4,
            max_tokens=2000,
        )
        parsed = parse_json_object(text)
        if not parsed:
            continue
        summary, findings = findings_from_payload(parsed)
        if summary:
            summaries.append(summary)
        collected.append(findings)
    merged = majority_vote(collected)
    summary = summaries[0] if summaries else "Ensemble review (majority vote)."
    return summary, merged, "ensemble"


def _agentic(
    client: ChatClient, prompt: str, config: QualityConfig, root
) -> tuple[str, list[Finding]]:
    messages = [
        ChatTurn("system", SYSTEM),
        ChatTurn("user", prompt + "\n\n" + SUBMIT_SCHEMA),
    ]
    rounds = max(0, min(8, config.review_tool_rounds))
    for _ in range(rounds + 1):
        text = client.complete(messages, max_tokens=2400)
        parsed = parse_json_object(text)
        if not parsed:
            messages.append(ChatTurn("assistant", text))
            messages.append(
                ChatTurn("user", "Respond with the JSON object only. " + SUBMIT_SCHEMA)
            )
            continue
        action = str(parsed.get("action") or "submit").lower()
        if action != "need":
            return findings_from_payload(parsed)
        extra = _fulfill_need(parsed, config, root)
        messages.append(ChatTurn("assistant", text))
        messages.append(
            ChatTurn(
                "user",
                extra + "\n\nNow submit findings JSON. " + SUBMIT_SCHEMA,
            )
        )
    text = client.complete(messages, max_tokens=2400)
    parsed = parse_json_object(text)
    if not parsed:
        return text.strip()[:2000], []
    return findings_from_payload(parsed)


def _fulfill_need(payload: dict[str, object], config: QualityConfig, root) -> str:
    chunks: list[str] = []
    files = payload.get("files") or []
    if isinstance(files, list):
        for item in files[:8]:
            rel = str(item).strip()
            text = read_repo_file(
                root, rel, limit=max(2000, config.review_related_bytes // 4)
            )
            if text is None:
                chunks.append(f"## {rel}\n(unavailable)")
            else:
                chunks.append(f"## {rel}\n```\n{text}\n```")
    greps = payload.get("grep") or []
    if isinstance(greps, list):
        for spec in greps[:4]:
            if not isinstance(spec, dict):
                continue
            pattern = str(spec.get("pattern") or "").strip()
            if not pattern:
                continue
            glob = str(spec.get("glob") or "*")
            hits = grep_repo(root, config, pattern, glob=glob)
            chunks.append(
                f"## grep {pattern} ({glob})\n" + ("\n".join(hits) or "(no hits)")
            )
    return "\n\n".join(chunks) or "No extra context found."
