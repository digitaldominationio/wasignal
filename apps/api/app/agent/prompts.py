"""Prompt assembly.

Keep this in one place: the system prompt is the most-edited artifact in a
product like this, and diffing one function beats hunting f-strings.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from . import capabilities

WHATSAPP_STYLE = (
    "You reply inside WhatsApp. Write like a person: short paragraphs, no markdown, "
    "no headings, no bullet lists unless the customer asked for options. Never invent "
    "prices, stock or delivery dates — if it is not in the knowledge tool, say you will check."
)


def _now(agent: dict[str, Any]) -> str:
    timezone = agent.get("timezone") or "Asia/Kolkata"
    try:
        return datetime.now(ZoneInfo(timezone)).strftime("%A %d %B %Y, %H:%M %Z")
    except Exception:
        return datetime.utcnow().strftime("%A %d %B %Y, %H:%M UTC")


def build_system_prompt(agent: dict[str, Any], *, memory_block: str = "", knowledge_titles: list[str] | None = None) -> str:
    parts = [
        agent.get("system_prompt", "").strip(),
        "",
        WHATSAPP_STYLE,
        "",
        f"Current time: {_now(agent)}.",
        "",
        "Your permissions in this chat:",
        capabilities.describe(agent),
    ]
    if knowledge_titles:
        parts += ["", "Knowledge you can search: " + ", ".join(knowledge_titles)]
    if memory_block:
        parts += ["", "Things you already know about this customer:", memory_block]
    return "\n".join(parts).strip()


def render_line(message: dict[str, Any]) -> str:
    if message["direction"] == "out":
        return f"(YOU): {message['text']}"
    who = message.get("sender_name") or message.get("sender") or "Customer"
    return f"{who}: {message['text']}"


def build_messages(
    agent: dict[str, Any],
    *,
    history: list[dict[str, Any]],
    text: str,
    sender_name: str,
    memory_block: str = "",
    knowledge_titles: list[str] | None = None,
) -> list[dict[str, Any]]:
    transcript = "\n".join(render_line(message) for message in history if message.get("text"))
    system = build_system_prompt(agent, memory_block=memory_block, knowledge_titles=knowledge_titles)
    user = (
        "Recent conversation:\n" + (transcript or "(no previous messages)") +
        f"\n\nNew message from {sender_name or 'the customer'}:\n{text}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
