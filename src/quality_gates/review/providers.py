"""BYOK model providers: Azure, Bedrock, Gemini, OpenRouter, OpenAI-compat."""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from quality_gates.config import QualityConfig
from quality_gates.review.llm import AnthropicClient, ChatClient, OpenAICompatClient

PROVIDERS = (
    "auto",
    "anthropic",
    "openai",
    "azure",
    "bedrock",
    "gemini",
    "openrouter",
    "ollama",
    "compat",
    "off",
    "heuristic",
)


class GeminiClient:
    name = "gemini"

    def __init__(self, token: str, model: str, url: str) -> None:
        self.token = token
        self.model = model
        self.url = url

    def complete(
        self,
        messages: list[Any],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2400,
    ) -> str:
        contents = []
        for item in messages:
            role = "user" if getattr(item, "role", "user") != "assistant" else "model"
            contents.append({"role": role, "parts": [{"text": item.content}]})
        payload = json.dumps(
            {
                "contents": contents,
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens,
                },
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.url}?key={self.token}",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            body = json.loads(response.read().decode("utf-8"))
        parts = (
            ((body.get("candidates") or [{}])[0].get("content") or {}).get("parts")
        ) or []
        return "".join(part.get("text", "") for part in parts)


def resolve_extended_client(
    config: QualityConfig, *, model: str | None = None
) -> ChatClient | None:
    provider = (config.review_provider or "auto").lower()
    chosen = (model or config.review_model or "").strip()
    base = (
        os.environ.get("QUALITY_REVIEW_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or getattr(config, "review_base_url", "")
        or ""
    ).rstrip("/")

    if provider in {"compat", "vllm", "litellm"} or (
        provider in {"auto", "openai"} and base and "openai.com" not in base
    ):
        token = (
            os.environ.get("OPENAI_API_KEY")
            or os.environ.get("QUALITY_REVIEW_API_KEY")
            or "local"
        )
        if not base:
            return None
        return OpenAICompatClient(
            f"{base}/chat/completions"
            if not base.endswith("/chat/completions")
            else base,
            token,
            chosen or os.environ.get("OPENAI_MODEL") or "local",
            "compat",
        )

    if provider == "azure" or os.environ.get("AZURE_OPENAI_API_KEY"):
        key = os.environ.get("AZURE_OPENAI_API_KEY")
        endpoint = (os.environ.get("AZURE_OPENAI_ENDPOINT") or base).rstrip("/")
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT") or chosen or "gpt-4o"
        if key and endpoint:
            url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version=2024-06-01"
            return OpenAICompatClient(url, key, deployment, "azure")

    if provider == "openrouter" or os.environ.get("OPENROUTER_API_KEY"):
        key = os.environ.get("OPENROUTER_API_KEY")
        if key:
            return OpenAICompatClient(
                "https://openrouter.ai/api/v1/chat/completions",
                key,
                chosen or "openrouter/auto",
                "openrouter",
            )

    if (
        provider == "gemini"
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
    ):
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        gemini_model = chosen or os.environ.get("GEMINI_MODEL") or "gemini-2.0-flash"
        if key:
            return GeminiClient(
                key,
                gemini_model,
                f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent",
            )

    if provider == "bedrock" or os.environ.get("AWS_BEDROCK_API_KEY"):
        key = os.environ.get("AWS_BEDROCK_API_KEY") or os.environ.get(
            "AWS_SECRET_ACCESS_KEY"
        )
        url = os.environ.get("BEDROCK_ENDPOINT") or base
        if key and url:
            return OpenAICompatClient(
                f"{url.rstrip('/')}/chat/completions",
                key,
                chosen or os.environ.get("BEDROCK_MODEL") or "anthropic.claude-sonnet",
                "bedrock",
            )

    if provider == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY")
        if key:
            return AnthropicClient(
                key, chosen or os.environ.get("ANTHROPIC_MODEL") or "claude-sonnet-4-6"
            )
    return None


def task_model(config: QualityConfig, task: str, *, cheap: str, full: str) -> str:
    if (config.review_model or "").strip():
        return config.review_model.strip()
    if task in {"summary", "triage", "style", "explain"}:
        return config.review_cheap_model or cheap
    return config.review_full_model or full
