"""Tools the model can call, and the only place side effects are allowed.

Every tool declares its own capability requirement. Adding a new outward action
means adding a tool here — not teaching the prompt a new trick.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .. import repo
from ..llm.base import estimate_tokens
from . import capabilities as caps
from ..services import integrations
from ..services import knowledge as knowledge_service


@dataclass
class ToolContext:
    account: dict[str, Any]
    room: dict[str, Any]
    agent: dict[str, Any]
    lane_key: str = "main"

    def context_values(self) -> dict[str, str]:
        return {
            "room_id": str(self.room["id"]),
            "room_name": self.room.get("display_name", ""),
            "account_id": str(self.account["id"]),
            "account_name": self.account.get("name", ""),
            "timezone": self.account.get("timezone", ""),
            "handed_over": "true" if self.agent.get("_handed_over") else "false",
        }


def _iso(description: str) -> dict[str, Any]:
    return {"type": "string", "description": description}


CALENDAR_TOOLS = [
    ("calendar_list_events", "List calendar events between two ISO-8601 timestamps.",
     {"time_min": _iso("Start of the window, ISO-8601"), "time_max": _iso("End of the window, ISO-8601")},
     ["time_min", "time_max"]),
    ("calendar_find_slot", "Find free calendar slots for a meeting.",
     {"duration_minutes": {"type": "integer", "description": "Meeting length in minutes"},
      "after": _iso("Search from this ISO-8601 time"),
      "before": _iso("Search until this ISO-8601 time")},
     ["duration_minutes", "after", "before"]),
    ("calendar_create_event", "Book a calendar event. Requires human confirmation.",
     {"summary": _iso("Event title"),
      "start_datetime": _iso("Start, ISO-8601 with timezone"),
      "end_datetime": _iso("End, ISO-8601 with timezone"),
      "description": _iso("Optional details")},
     ["summary", "start_datetime", "end_datetime"]),
]

EMAIL_TOOLS = [
    ("gmail_search", "Search the inbox. Returns message ids and snippets.",
     {"query": _iso("Gmail search query, e.g. from:meera newer_than:7d"),
      "max_results": {"type": "integer", "description": "How many messages (default 5)"}},
     ["query"]),
    ("gmail_read", "Read one message by id.",
     {"message_id": _iso("Message id from gmail_search")}, ["message_id"]),
    ("gmail_draft", "Create a draft reply (does not send).",
     {"recipient_email": _iso("To address"), "subject": _iso("Subject"), "body": _iso("Plain-text body")},
     ["recipient_email", "subject", "body"]),
    ("gmail_send", "Send an email. Requires human confirmation.",
     {"recipient_email": _iso("To address"), "subject": _iso("Subject"), "body": _iso("Plain-text body")},
     ["recipient_email", "subject", "body"]),
]


def _connected(org_id: int | None, service: str) -> bool:
    return bool(org_id and integrations.is_connected(int(org_id), service))


def tool_specs(agent: dict[str, Any], org_id: int | None = None) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = [
        {
            "name": "search_knowledge",
            "description": "Look up products, prices, policies or anything the business saved. Use before answering factual questions.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "What to look for"}},
                "required": ["query"],
            },
        },
        {
            "name": "set_memory",
            "description": "Remember one durable fact about this customer (name, budget, preference).",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                },
                "required": ["key", "value"],
            },
        },
        {
            "name": "get_memory",
            "description": "Read a previously stored fact about this customer.",
            "parameters": {
                "type": "object",
                "properties": {"key": {"type": "string"}},
                "required": ["key"],
            },
        },
        {
            "name": "request_handover",
            "description": "Stop replying and hand this chat to a human. Use when unsure, when asked for a human, or for anything you cannot verify.",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        },
    ]

    if caps.can(agent, "send_other"):
        specs.append({
            "name": "send_to_room",
            "description": "Send a message to another chat, for example an internal team group.",
            "parameters": {
                "type": "object",
                "properties": {
                    "room_id": {"type": "integer"},
                    "text": {"type": "string"},
                },
                "required": ["room_id", "text"],
            },
        })

    connections = agent.get("_connections") or {}
    for capability, service, catalogue in (
        ("calendar", "google_calendar", CALENDAR_TOOLS),
        ("email", "gmail", EMAIL_TOOLS),
    ):
        if not caps.can(agent, capability):
            continue
        if not (connections.get(service) or _connected(org_id, service)):
            continue
        for name, description, properties, required in catalogue:
            specs.append({
                "name": name,
                "description": description,
                "parameters": {"type": "object", "properties": properties, "required": required},
            })

    account_id = agent.get("account_id")
    for webhook_id in agent.get("webhook_ids") or []:
        try:
            webhook = repo.raw_webhook(account_id, int(webhook_id))
        except KeyError:
            continue
        properties: dict[str, Any] = {}
        required: list[str] = []
        for field in webhook.get("body_fields") or []:
            key = field.get("key")
            if not key or field.get("source") == "context":
                continue
            properties[key] = {
                "type": "string" if field.get("type") in (None, "string") else field.get("type"),
                "description": field.get("description", ""),
            }
            if field.get("required"):
                required.append(key)
        specs.append({
            "name": f"webhook_{webhook['id']}",
            "description": webhook.get("description") or webhook.get("name") or "Call an external service",
            "parameters": {"type": "object", "properties": properties, "required": required},
        })
    return specs


async def execute(name: str, arguments: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    agent = ctx.agent
    try:
        if name == "search_knowledge":
            source_ids = repo.agent_knowledge_ids(agent["id"]) or None
            entries = knowledge_service.search(ctx.account["id"], str(arguments.get("query", "")), source_ids=source_ids)
            return {"ok": True, "result": {"entries": entries, "count": len(entries)}}

        if name == "set_memory":
            key = str(arguments.get("key", "")).strip()[:120]
            value = str(arguments.get("value", ""))[:2000]
            if not key:
                return {"ok": False, "error": "key is required"}
            repo.set_memory(agent["id"], key, value)
            return {"ok": True, "result": {"stored": key}}

        if name == "get_memory":
            key = str(arguments.get("key", "")).strip()
            row = next((m for m in repo.list_memory(agent["id"]) if m["key"] == key), None)
            return {"ok": True, "result": {"key": key, "value": row["value"] if row else None}}

        if name == "request_handover":
            caps.require(agent, "read")
            repo.set_handover(agent["id"], ctx.room["id"], True, ctx.lane_key)
            return {"ok": True, "result": {"handed_over": True, "reason": str(arguments.get("reason", ""))[:300]}}

        if name == "send_to_room":
            caps.require(agent, "send")
            target_raw = arguments.get("room_id")
            text = str(arguments.get("text", "")).strip()
            if not text:
                return {"ok": False, "error": "text is required"}
            try:
                target = repo.get_room(ctx.account["id"], int(target_raw))
            except (KeyError, TypeError, ValueError):
                return {"ok": False, "error": "unknown room_id"}
            if int(target["id"]) != int(ctx.room["id"]):
                caps.require(agent, "send_other")
                if target["is_excluded"]:
                    return {"ok": False, "error": "room is excluded"}
            message = repo.add_message(
                ctx.account["id"], target["id"], "out", text,
                source="whatsapp", agent_id=agent["id"], status="accepted",
            )
            repo.enqueue_outbox(ctx.account["id"], target["id"], text, message_id=message["id"])
            return {"ok": True, "result": {"queued": True, "room_id": target["id"]}}

        if name in {tool[0] for tool in CALENDAR_TOOLS} | {tool[0] for tool in EMAIL_TOOLS}:
            service = "google_calendar" if name.startswith("calendar_") else "gmail"
            capability = "calendar" if service == "google_calendar" else "email"
            caps.require(agent, capability)
            org_id = int(ctx.account["org_id"]) if ctx.account.get("org_id") else None
            if not org_id or not integrations.is_connected(org_id, service):
                return {"ok": False, "error": f"{service}_not_connected", "result": {
                    "instruction": "Tell the customer this integration still needs to be connected in Settings.",
                }}
            if name in integrations.CONFIRM_REQUIRED:
                return integrations.propose(
                    org_id, int(agent["id"]), int(ctx.room["id"]), ctx.lane_key, service, name, arguments,
                )
            return integrations.execute(
                org_id, service, name, arguments,
                agent_id=int(agent["id"]), room_id=int(ctx.room["id"]),
            )

        if name.startswith("webhook_"):
            caps.require(agent, "send")
            return await _call_webhook(name, arguments, ctx)

        return {"ok": False, "error": f"unknown tool {name}"}
    except caps.CapabilityError as exc:
        return {"ok": False, "error": f"not permitted: {exc}"}
    except Exception as exc:  # a tool must never crash the turn
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


async def _call_webhook(name: str, arguments: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    try:
        webhook_id = int(name.split("_", 1)[1])
        webhook = repo.raw_webhook(ctx.account["id"], webhook_id)
    except (IndexError, ValueError, KeyError):
        return {"ok": False, "error": "webhook not found"}

    context = ctx.context_values()
    payload: dict[str, Any] = {}
    missing: list[str] = []
    for field in webhook.get("body_fields") or []:
        key = field.get("key")
        if not key:
            continue
        if field.get("source") == "context":
            if field.get("context_key") and field["context_key"] in context:
                payload[key] = context[field["context_key"]]
            elif field.get("value") is not None:
                payload[key] = field["value"]
            if field.get("required") and key not in payload:
                missing.append(key)
            continue
        value = arguments.get(key, field.get("value"))
        if value in (None, "") and field.get("required"):
            missing.append(key)
        elif value not in (None, ""):
            payload[key] = value

    if missing:
        return {"ok": False, "error": f"missing required fields: {', '.join(missing)}"}

    headers = {
        header["name"]: header.get("value", "")
        for header in webhook.get("headers") or []
        if header.get("name") and header.get("value") is not None
    }
    method = webhook.get("method", "POST").upper()
    started = time.monotonic()
    status_code: int | None = None
    error: str | None = None
    body_preview = ""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            if method in {"GET", "HEAD", "DELETE"}:
                response = await client.request(method, webhook["url"], headers=headers, params=payload)
            else:
                response = await client.request(method, webhook["url"], headers=headers, json=payload)
        status_code = response.status_code
        body_preview = response.text[:500]
        if response.status_code >= 400:
            error = f"http {response.status_code}"
    except httpx.HTTPError as exc:
        error = f"transport: {exc}"

    repo.add_delivery(
        webhook["id"], ctx.account["id"], "agent", status_code,
        int((time.monotonic() - started) * 1000), error,
    )
    if error:
        return {"ok": False, "error": error, "result": {"status": status_code, "body": body_preview}}
    return {"ok": True, "result": {"status": status_code, "body": body_preview}}


def tool_result_content(result: dict[str, Any]) -> str:
    """Compact JSON for the model; keep it small, it sits in the context window."""
    return json.dumps(result, ensure_ascii=False)[:4000]


def estimate_tool_tokens(result: dict[str, Any]) -> int:
    return estimate_tokens([{"content": tool_result_content(result)}])
