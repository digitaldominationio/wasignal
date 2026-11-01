"""Deterministic offline provider.

Good for tests, demos and CI: no keys, no network, same input -> same output.
It still *uses tools*, so the agent loop, capability gates and webhook plumbing
are exercised end to end.
"""
from __future__ import annotations

import json
from typing import Any

from .base import LLMResponse, ToolCall, estimate_tokens

HANDOVER_WORDS = ("human", "agent", "manager", "call me", "talk to someone", "real person")
PRICE_WORDS = (
    "price", "cost", "rate", "fee", "fees", "how much", "catalogue", "catalog",
    "hostel", "batch", "scholarship", "discount", "available", "availability",
    "timing", "timings", "slot", "address", "syllabus", "location",
)
LEAD_WORDS = ("book", "order", "buy", "lead", "demo", "qualified", "interested")


class EchoLLM:
    provider = "echo"

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        tool_names = {tool["name"] for tool in tools}
        last = messages[-1] if messages else {"role": "user", "content": ""}

        # Second pass: a tool just ran -> turn its result into the reply.
        if last.get("role") == "tool":
            return LLMResponse(text=self._from_tool(last), tokens=estimate_tokens(messages))

        text = self._incoming(last.get("content") or "")
        lowered = text.lower()

        if "request_handover" in tool_names and any(word in lowered for word in HANDOVER_WORDS):
            return LLMResponse(tool_calls=[ToolCall(id="call_handover", name="request_handover",
                                                    arguments={"reason": "customer asked for a human"})])

        if "search_knowledge" in tool_names and any(word in lowered for word in PRICE_WORDS):
            return LLMResponse(tool_calls=[ToolCall(id="call_knowledge", name="search_knowledge",
                                                    arguments={"query": text[:200]})])

        for name in tool_names:
            if name.startswith("webhook_") and any(word in lowered for word in LEAD_WORDS):
                return LLMResponse(tool_calls=[ToolCall(id=f"call_{name}", name=name,
                                                        arguments={"note": text[:300]})])

        return LLMResponse(text=self._smalltalk(text), tokens=estimate_tokens(messages))

    @staticmethod
    def _incoming(content: str) -> str:
        """build_messages puts history and the new message in one user turn.

        A stub must reason about the new message only, or words in the
        transcript ("talk to a human") will trigger the wrong tool.
        """
        marker = "New message from "
        index = content.rfind(marker)
        if index == -1:
            return content.strip()
        tail = content[index:]
        newline = tail.find("\n")
        return tail[newline + 1:].strip() if newline != -1 else ""

    @staticmethod
    def _smalltalk(text: str) -> str:
        stripped = text.strip()
        lowered = stripped.lower()
        if not stripped:
            return "Hi! How can I help today?"
        if lowered.startswith(("hi", "hello", "hey", "namaste")):
            return "Hi! How can I help today?"
        if "?" in stripped:
            return f"Good question — let me check on that. You asked: {stripped[:160]}"
        return f"Got it — noted: {stripped[:160]}. Anything else you'd like to know?"

    @staticmethod
    def _from_tool(message: dict[str, Any]) -> str:
        name = str(message.get("name") or "")
        raw = message.get("content") or ""
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            payload = {"raw": raw}

        # tool results arrive wrapped as {ok, result|error}
        if isinstance(payload, dict) and isinstance(payload.get("result"), dict):
            payload = payload["result"]
        if isinstance(payload, dict) and payload.get("ok") is False:
            return "Let me get a colleague to confirm that for you."

        if name == "search_knowledge":
            entries = payload.get("entries") or []
            if not entries:
                return "I don't have that in the knowledge base yet — let me get a human to confirm."
            first = entries[0]
            title = first.get("title") or "Details"
            content = first.get("content") or ""
            return f"{title}: {content}"[:600]
        if name == "request_handover":
            return "Sure — I've passed this to the team and someone will reply here shortly."
        if name.startswith("webhook_"):
            return "Done — I've logged that with the team."
        return "Noted."
