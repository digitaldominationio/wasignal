"""Inbound pipeline: gate -> match -> assemble -> run -> admit.

The order is the design. Persist before you prepare, admit before you deliver,
and never let a gate fail *after* the model has seen the message.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from .. import repo
from ..config import settings
from . import billing, outbound
from ..agent.capabilities import can
from ..agent.runtime import run_agent


@dataclass
class InboundResult:
    accepted: bool
    stage: str
    reason: Optional[str] = None
    room_id: Optional[int] = None
    message_id: Optional[int] = None
    agent_id: Optional[int] = None
    run_id: Optional[int] = None
    reply: str = ""
    delivery: str = "none"
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "stage": self.stage,
            "reason": self.reason,
            "room_id": self.room_id,
            "message_id": self.message_id,
            "agent_id": self.agent_id,
            "run_id": self.run_id,
            "reply": self.reply,
            "delivery": self.delivery,
            **self.meta,
        }


_STOPWORDS = {"the", "and", "for", "with", "that", "this", "when", "then", "asks", "about", "someone", "message", "chat", "any", "all"}


def matches_condition(condition: Optional[str], text: str) -> bool:
    """Naive stand-in for the product's plain-English matcher.

    Comma/semicolon separated phrases; a phrase matches when any of its words
    (longer than 3 chars, not a stopword) appears in the message.
    """
    if not condition or not condition.strip():
        return True
    lowered = text.lower()
    for phrase in condition.replace(";", ",").split(","):
        words = [w.strip(" .!?\n\t").lower() for w in phrase.split()]
        candidates = [w for w in words if len(w) > 3 and w not in _STOPWORDS]
        if candidates and any(word in lowered for word in candidates):
            return True
        if phrase.strip().lower() in lowered:
            return True
    return False


def _agent_matches(agent: dict[str, Any], room: dict[str, Any], text: str) -> bool:
    if agent["status"] != "active":
        return False
    if agent["trigger_type"] == "scheduled":
        return False  # only the scheduler may fire these
    if agent.get("room_id") and int(agent["room_id"]) != int(room["id"]):
        return False
    if int(room["id"]) in [int(x) for x in agent.get("excluded_room_ids") or []]:
        return False
    chat_type = agent.get("chat_type") or "all"
    if chat_type != "all" and chat_type != room["kind"]:
        return False
    # A room-scoped agent lives in that chat: the condition narrows topics, not
    # whether it may answer its own room's messages.
    if agent.get("trigger_scope") == "topic":
        return matches_condition(agent.get("trigger_condition"), text)
    return True


async def handle_inbound(
    account: dict[str, Any],
    room: dict[str, Any],
    *,
    text: str,
    sender: str = "",
    sender_name: str = "",
    media: Optional[list[dict[str, Any]]] = None,
    source: str = "whatsapp",
    is_human_owner: bool = False,
    timestamp: Optional[int] = None,
) -> InboundResult:
    # 0. transcripts, before the new row exists (so the prompt sees history only)
    history = repo.history(int(room["id"]), settings.history_limit)

    message = repo.add_message(
        int(account["id"]), int(room["id"]), "in", text,
        sender=sender, sender_name=sender_name, media=media or [],
        source="owner" if is_human_owner else source,
        status="delivered", ts=timestamp,
    )
    base = {"room_id": room["id"], "message_id": message["id"]}

    # 1. gates
    if room.get("is_excluded"):
        return InboundResult(False, "excluded", "room is excluded", **base)

    if repo.human_pause_enabled(int(account["id"])) and repo.owner_spoke_recently(
        int(account["id"]), int(room["id"]), settings.human_active_pause_seconds
    ):
        return InboundResult(False, "paused", "human_active_pause", **base)

    if (account.get("subscription_status") or "active") not in {"active", "trial", "trialing"}:
        return InboundResult(False, "subscription_inactive", account.get("subscription_status"), **base)

    # 2. match
    agents = [agent for agent in repo.list_agents(int(account["id"]), include_paused=False)
              if _agent_matches(agent, room, text)]
    if not agents:
        return InboundResult(False, "no_agent", "no matching active agent", **base)

    agent = agents[0]
    lane_key = "main"

    # 3. run
    outcome = await run_agent(
        agent, account, room,
        text=text, history=history, sender_name=sender_name,
        trigger="event", lane_key=lane_key,
    )

    if outcome.status == "handover" and not outcome.reply:
        return InboundResult(False, "handover", outcome.reason, agent_id=agent["id"], run_id=outcome.run_id, **base)
    if outcome.status == "error":
        return InboundResult(False, "failed", outcome.reason, agent_id=agent["id"], run_id=outcome.run_id, **base)

    reply = (outcome.reply or "").strip()
    if not reply or not can(agent, "send"):
        return InboundResult(False, "read_only" if not can(agent, "send") else "empty",
                             outcome.reason, agent_id=agent["id"], run_id=outcome.run_id, **base)

    # 4. quota gate: the plan limit is enforced at the send boundary
    org_id = int(account["org_id"]) if account.get("org_id") else None
    if org_id:
        try:
            billing.check(org_id, "messages")
        except billing.QuotaExceeded as exc:
            return InboundResult(
                False, "quota_exceeded", f"{exc.metric}_limit_reached",
                agent_id=agent["id"], run_id=outcome.run_id, **base,
            )

    # 5. admit: persist, then queue for the channel worker
    outbound_message = repo.add_message(
        int(account["id"]), int(room["id"]), "out", reply,
        source="whatsapp", agent_id=agent["id"], run_id=outcome.run_id, status="accepted",
    )
    outbound.enqueue(int(account["id"]), int(room["id"]), reply, message_id=outbound_message["id"])
    if org_id:
        billing.record(org_id, "messages", 1, f"room:{room['id']}")

    return InboundResult(
        True, "admitted", outcome.reason,
        agent_id=agent["id"], run_id=outcome.run_id, reply=reply, delivery="queued",
        **base,
    )


async def handle_owner_reply(account: dict[str, Any], room: dict[str, Any], text: str, sender_name: str = "Owner") -> InboundResult:
    """Record that the human answered. This is what arms human-active-pause."""
    return await handle_inbound(
        account, room, text=text, sender=sender_name, sender_name=sender_name,
        source="owner", is_human_owner=True,
    )


def now() -> int:
    return int(time.time())
