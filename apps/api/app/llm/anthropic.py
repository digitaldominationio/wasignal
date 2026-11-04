"""Anthropic Messages API adapter with tool use.

Translates the runtime's OpenAI-shaped history into Anthropic content blocks and
back, so the agent loop stays provider-neutral.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from ..config import settings
from .base import LLMError, LLMResponse, ToolCall, estimate_tokens

ANTHROPIC_VERSION = "2023-06-01"
MAX_TOKENS = 2048


class AnthropicLLM:
    provider = "anthropic"

    def __init__(self, model: str, api_key: str, base_url: str = "https://api.anthropic.com") -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        if not api_key:
            raise LLMError("anthropic key missing")

    # --------------------------------------------------------------- convert

    @staticmethod
    def _convert(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        system_parts: list[str] = []
        converted: list[dict[str, Any]] = []
        pending_tool_results: list[dict[str, Any]] = []

        def flush_tools() -> None:
            nonlocal pending_tool_results
            if pending_tool_results:
                converted.append({"role": "user", "content": pending_tool_results})
                pending_tool_results = []

        for message in messages:
            role = message.get("role")
            if role == "system":
                system_parts.append(str(message.get("content") or ""))
                continue
            if role == "tool":
                pending_tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": message.get("tool_call_id"),
                    "content": str(message.get("content") or "")[:6000],
                })
                continue

            flush_tools()
            if role == "user":
                converted.append({"role": "user", "content": [{"type": "text", "text": str(message.get("content") or "")}]})
                continue
            if role == "assistant":
                blocks: list[dict[str, Any]] = []
                if message.get("content"):
                    blocks.append({"type": "text", "text": str(message["content"])})
                for call in message.get("tool_calls") or []:
                    function = call.get("function") or {}
                    try:
                        arguments = json.loads(function.get("arguments") or "{}")
                    except ValueError:
                        arguments = {}
                    blocks.append({
                        "type": "tool_use",
                        "id": call.get("id") or "call",
                        "name": function.get("name") or "",
                        "input": arguments if isinstance(arguments, dict) else {},
                    })
                converted.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})

        flush_tools()
        return "\n\n".join(part for part in system_parts if part), converted

    @staticmethod
    def _tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "input_schema": tool.get("parameters") or {"type": "object", "properties": {}},
            }
            for tool in tools
        ]

    # ------------------------------------------------------------------ call

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        system, converted = self._convert(messages)
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "messages": converted,
        }
        if system:
            body["system"] = system
        if tools:
            body["tools"] = self._tools(tools)

        try:
            async with httpx.AsyncClient(timeout=settings.provider_validation_timeout * 4) as client:
                response = await client.post(
                    f"{self.base_url}/v1/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": ANTHROPIC_VERSION,
                        "content-type": "application/json",
                    },
                    json=body,
                )
        except httpx.HTTPError as exc:
            raise LLMError(f"transport: {exc}") from exc

        if response.status_code >= 400:
            raise LLMError(f"provider {response.status_code}: {response.text[:300]}")

        data = response.json()
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for block in data.get("content") or []:
            if block.get("type") == "text":
                text_parts.append(block.get("text") or "")
            elif block.get("type") == "tool_use":
                calls.append(ToolCall(
                    id=block.get("id") or "call",
                    name=block.get("name") or "",
                    arguments=block.get("input") or {},
                ))

        usage = data.get("usage") or {}
        tokens = int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
        return LLMResponse(
            text="\n".join(part for part in text_parts if part).strip(),
            tool_calls=calls,
            tokens=tokens or estimate_tokens(messages),
        )
