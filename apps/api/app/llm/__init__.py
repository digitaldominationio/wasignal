"""LLM selection per agent, with tenant-provided keys.

Resolution lives in `services/providers.resolve`: agent override → organization
default → deployment default, and organization credential → deployment env key.
"""
from __future__ import annotations

from typing import Any, Optional

from ..config import settings
from ..services import providers
from .anthropic import AnthropicLLM
from .base import LLM, LLMError
from .echo import EchoLLM
from .openai_compat import OpenAICompatLLM


def openrouter_llm(model: str | None = None, api_key: str | None = None) -> OpenAICompatLLM:
    key = api_key or settings.openrouter_key
    if not key:
        raise LLMError("openrouter_not_configured")
    return OpenAICompatLLM(
        model=model or settings.openrouter_model,
        base_url=settings.openrouter_base_url,
        api_key=key,
        provider="openrouter",
        extra_headers={
            "HTTP-Referer": settings.openrouter_referer,
            "X-Title": settings.openrouter_title,
        },
    )


def get_llm(agent: dict[str, Any] | None = None, org_id: Optional[int] = None) -> LLM:
    resolved = providers.resolve(org_id, agent)
    provider = resolved["provider"]

    if resolved["adapter"] == "echo":
        return EchoLLM()

    if not resolved["api_key"]:
        raise LLMError(f"{provider}_not_configured")

    if resolved["adapter"] == "anthropic":
        return AnthropicLLM(
            model=resolved["model"] or "claude-sonnet-4-5",
            api_key=resolved["api_key"],
            base_url=resolved["base_url"] or "https://api.anthropic.com",
        )

    extra_headers = {}
    if provider == "openrouter":
        extra_headers = {
            "HTTP-Referer": settings.openrouter_referer,
            "X-Title": settings.openrouter_title,
        }
    return OpenAICompatLLM(
        model=resolved["model"],
        base_url=resolved["base_url"],
        api_key=resolved["api_key"],
        provider=provider,
        extra_headers=extra_headers,
    )


__all__ = ["LLM", "LLMError", "EchoLLM", "OpenAICompatLLM", "AnthropicLLM", "get_llm", "openrouter_llm"]
