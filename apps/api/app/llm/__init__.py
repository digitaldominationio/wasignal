"""LLM selection per agent.

The agent row can pin a provider/model; otherwise the deployment default applies.
"""
from __future__ import annotations

from typing import Any

from ..config import settings
from .base import LLM, LLMError
from .echo import EchoLLM
from .openai_compat import OpenAICompatLLM


def openrouter_llm(model: str | None = None) -> OpenAICompatLLM:
    if not settings.openrouter_key:
        raise LLMError("OPENROUTER_API_KEY is not set (add it to .env and restart)")
    return OpenAICompatLLM(
        model=model or settings.openrouter_model,
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_key,
        provider="openrouter",
        extra_headers={
            # OpenRouter uses these for attribution / rankings; both are optional.
            "HTTP-Referer": settings.openrouter_referer,
            "X-Title": settings.openrouter_title,
        },
    )


def get_llm(agent: dict[str, Any] | None = None) -> LLM:
    provider = ((agent or {}).get("llm_provider") or settings.llm_provider or "").lower()
    model = (agent or {}).get("llm_model") or None

    if provider in {"echo", "stub", "offline"}:
        return EchoLLM()
    if provider == "openrouter":
        return openrouter_llm(model)
    if provider in {"openai", "openai-compatible", "openrouter-compatible", "groq", "vllm", "together"}:
        return OpenAICompatLLM(model=model, provider=provider)
    raise LLMError(f"unknown llm provider: {provider}")


__all__ = ["LLM", "LLMError", "EchoLLM", "OpenAICompatLLM", "get_llm", "openrouter_llm"]
