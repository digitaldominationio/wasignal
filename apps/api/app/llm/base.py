"""Provider-neutral LLM contract.

Messages use the OpenAI chat format:
  {"role": "system"|"user"|"assistant"|"tool", "content": str, ...}
so swapping providers is a serialisation detail, not a rewrite.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


class LLMError(RuntimeError):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tokens: int = 0


class LLM(Protocol):
    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse: ...


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    chars = 0
    for message in messages:
        chars += len(str(message.get("content") or ""))
        for call in message.get("tool_calls") or []:
            chars += len(str(call))
    return max(1, chars // 4)


def as_tool_specs(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Our internal tool dicts -> OpenAI function-calling schema."""
    specs = []
    for tool in tools:
        specs.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("parameters") or {"type": "object", "properties": {}},
            },
        })
    return specs


def first_text(messages: list[dict[str, Any]]) -> Optional[str]:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return None
