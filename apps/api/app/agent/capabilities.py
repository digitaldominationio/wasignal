"""Capabilities are permissions enforced at tool-execution time.

Never rely on the prompt to keep an agent from sending somewhere it shouldn't:
the prompt is advice, the executor is the boundary.
"""
from __future__ import annotations

from typing import Any

CAPABILITIES: dict[str, str] = {
    "read": "Read the scoped chat",
    "send": "Reply in the scoped chat (text and media)",
    "send_other": "Post into chats other than the trigger chat",
    "group_admin": "Add/remove group members, change group settings",
}

DEFAULT = ["read", "send"]


class CapabilityError(PermissionError):
    pass


def normalise(capabilities: list[str] | None) -> list[str]:
    if not capabilities:
        return list(DEFAULT)
    cleaned = [cap for cap in capabilities if cap in CAPABILITIES]
    if "send" in cleaned and "read" not in cleaned:
        cleaned.append("read")
    return cleaned


def can(agent: dict[str, Any], capability: str) -> bool:
    return capability in (agent.get("capabilities") or DEFAULT)


def require(agent: dict[str, Any], capability: str) -> None:
    if not can(agent, capability):
        raise CapabilityError(f"agent lacks capability '{capability}'")


def describe(agent: dict[str, Any]) -> str:
    caps = agent.get("capabilities") or DEFAULT
    lines = [f"- {cap}: {CAPABILITIES[cap]}" for cap in caps if cap in CAPABILITIES]
    return "\n".join(lines)
