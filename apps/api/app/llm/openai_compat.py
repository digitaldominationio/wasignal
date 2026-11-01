"""Any OpenAI-compatible chat-completions endpoint.

Covers OpenAI, OpenRouter, vLLM, Groq, Together and friends: they all speak the
same wire format, so the only per-provider differences are base URL, key and a
couple of optional headers.
"""
from __future__ import annotations

import json
import time
from typing import Any

import httpx

from ..config import settings
from .base import LLMError, LLMResponse, ToolCall, as_tool_specs, estimate_tokens


class OpenAICompatLLM:
    provider = "openai"

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        extra_headers: dict[str, str] | None = None,
        provider: str | None = None,
    ) -> None:
        self.model = model or settings.llm_model
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.llm_api_key
        self.extra_headers = dict(extra_headers or {})
        if provider:
            self.provider = provider
        if not self.api_key:
            raise LLMError("missing API key for the LLM provider")

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.3,
        }
        if tools:
            body["tools"] = as_tool_specs(tools)
            body["tool_choice"] = "auto"

        started = time.monotonic()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise LLMError(f"transport: {exc}") from exc

        if response.status_code >= 400:
            raise LLMError(f"provider {response.status_code}: {response.text[:300]}")

        data = response.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        calls: list[ToolCall] = []
        for index, call in enumerate(message.get("tool_calls") or []):
            function = call.get("function") or {}
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except ValueError:
                arguments = {}
            calls.append(ToolCall(
                id=call.get("id") or f"call_{index}",
                name=function.get("name") or "",
                arguments=arguments if isinstance(arguments, dict) else {},
            ))

        usage = data.get("usage") or {}
        tokens = int(usage.get("total_tokens") or estimate_tokens(messages))
        _ = started
        return LLMResponse(text=(message.get("content") or "").strip(), tool_calls=calls, tokens=tokens)
