"""Integration broker facade: connections, action execution, confirmations, audit.

Composio is the first broker. Everything below the facade is broker-neutral:
`get_broker()` returns an object with link/list_accounts/execute/disconnect.
"""
from __future__ import annotations

import json
import re
import secrets
import time
from typing import Any, Optional

from ... import repo
from ...config import settings
from .composio import BrokerError, ComposioBroker, NotConfigured

SERVICES: dict[str, dict[str, Any]] = {
    "google_calendar": {
        "id": "google_calendar",
        "label": "Google Calendar",
        "description": "Read availability, find slots, create events.",
        "capability": "calendar",
    },
    "gmail": {
        "id": "gmail",
        "label": "Gmail",
        "description": "Search mail, read threads, draft and send replies.",
        "capability": "email",
    },
}

ACTION_SLUGS: dict[str, dict[str, str]] = {
    "google_calendar": {
        "calendar_list_events": "GOOGLECALENDAR_EVENTS_LIST",
        "calendar_find_slot": "GOOGLECALENDAR_FIND_FREE_SLOTS",
        "calendar_create_event": "GOOGLECALENDAR_CREATE_EVENT",
    },
    "gmail": {
        "gmail_search": "GMAIL_FETCH_EMAILS",
        "gmail_read": "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID",
        "gmail_draft": "GMAIL_CREATE_EMAIL_DRAFT",
        "gmail_send": "GMAIL_SEND_EMAIL",
    },
}

# Actions that must be confirmed by the human before they touch the world.
CONFIRM_REQUIRED = {"calendar_create_event", "gmail_send"}
SAFE_ACTIONS = {"calendar_list_events", "calendar_find_slot", "gmail_search", "gmail_read", "gmail_draft"}

PENDING_TTL = 15 * 60
AFFIRMATIVE = re.compile(r"^(yes|yep|yeah|yup|sure|ok|okay|confirm|confirmed|go ahead|do it|book it|send it)\b", re.I)
NEGATIVE = re.compile(r"^(no|nope|nah|cancel|don'?t|do not|stop)\b", re.I)


def get_broker() -> Optional[ComposioBroker]:
    try:
        return ComposioBroker()
    except NotConfigured:
        return None


def configured() -> bool:
    return bool(settings.composio_api_key)


def _service(service: str) -> dict[str, Any]:
    spec = SERVICES.get(service)
    if spec is None:
        raise KeyError("unknown_service")
    return spec


def is_connected(org_id: int, service: str) -> bool:
    row = repo.get_connected_account(org_id, service)
    return bool(row and row.get("status") == "active")


def connected_services(org_id: int) -> dict[str, bool]:
    rows = {row["service"]: row for row in repo.list_connected_accounts(org_id)}
    return {service: bool(rows.get(service, {}).get("status") == "active") for service in SERVICES}


def services_for_org(org_id: int) -> list[dict[str, Any]]:
    rows = {row["service"]: row for row in repo.list_connected_accounts(org_id)}
    items = []
    for service, spec in SERVICES.items():
        row = rows.get(service)
        items.append({
            **spec,
            "connected": bool(row and row.get("status") == "active"),
            "status": (row or {}).get("status", "not_connected"),
            "key_hint": None,
            "provider": (row or {}).get("provider", "composio"),
            "connected_at": (row or {}).get("created_at"),
        })
    return items


# ------------------------------------------------------------------ lifecycle


def connect(org_id: int, service: str) -> dict[str, Any]:
    _service(service)
    broker = get_broker()
    if broker is None:
        raise NotConfigured("composio_api_key_missing")
    callback = f"{settings.public_web_url}/dashboard/connections?connected={service}"
    link = broker.link(org_id, service, callback)
    repo.upsert_connected_account(
        org_id, service, broker.toolkit_slugs[service], link.get("external_id"), "pending",
    )
    return {"service": service, **link}


def sync(org_id: int) -> list[dict[str, Any]]:
    broker = get_broker()
    if broker is None:
        return services_for_org(org_id)
    try:
        accounts = broker.list_accounts(org_id)
    except BrokerError:
        return services_for_org(org_id)
    for account in accounts:
        repo.upsert_connected_account(
            org_id, account["service"], account["toolkit"], account["external_id"],
            "active" if account["status"] in {"active", "connected"} else account["status"],
        )
    return services_for_org(org_id)


def disconnect(org_id: int, service: str) -> None:
    broker = get_broker()
    if broker is not None:
        try:
            broker.disconnect(org_id, service)
        except BrokerError:
            pass
    repo.delete_connected_account(org_id, service)


# ------------------------------------------------------------------- actions


def execute(org_id: int, service: str, action: str, arguments: dict[str, Any],
            *, agent_id: Optional[int] = None, room_id: Optional[int] = None) -> dict[str, Any]:
    """Run one broker action and write an audit row. Safe actions only — writes
    must go through propose() + confirm_pending()."""
    _service(service)
    slug = ACTION_SLUGS.get(service, {}).get(action)
    if slug is None:
        return {"ok": False, "error": "unknown_action"}
    broker = get_broker()
    if broker is None:
        return {"ok": False, "error": "broker_not_configured"}
    row = repo.get_connected_account(org_id, service)
    if not row or row.get("status") != "active":
        return {"ok": False, "error": f"{service}_not_connected"}

    result = broker.execute(org_id, slug, arguments, row.get("external_id"))
    repo.add_integration_action(
        org_id, service, action, arguments, "ok" if result.get("ok") else "error",
        result=result.get("data") if isinstance(result.get("data"), dict) else {"value": result.get("data")},
        error=result.get("error"), account_id=int(row["id"]), agent_id=agent_id, room_id=room_id,
    )
    return result


def propose(org_id: int, agent_id: int, room_id: int, lane_key: str, service: str, action: str,
            arguments: dict[str, Any]) -> dict[str, Any]:
    """Store a write action and ask the human to confirm it."""
    _service(service)
    if action not in CONFIRM_REQUIRED:
        return {"ok": False, "error": "action_does_not_require_confirmation"}
    token = secrets.token_urlsafe(12)
    pending = repo.create_pending_action(
        org_id, agent_id, room_id, lane_key, service, action, arguments, token,
        int(time.time()) + PENDING_TTL,
    )
    repo.add_integration_action(
        org_id, service, action, arguments, "proposed",
        result={"summary": describe(action, arguments)}, agent_id=agent_id, room_id=room_id,
    )
    return {
        "ok": True,
        "result": {
            "needs_confirmation": True,
            "token": token,
            "summary": describe(action, arguments),
            "instruction": "Ask the customer to confirm. Do not claim it is done yet.",
        },
        "pending_id": pending["id"],
    }


def confirm_pending(pending: dict[str, Any]) -> dict[str, Any]:
    result = execute(
        int(pending["org_id"]), pending["service"], pending["action"], pending["args"],
        agent_id=int(pending["agent_id"]), room_id=int(pending["room_id"]),
    )
    repo.resolve_pending_action(int(pending["id"]), "executed" if result.get("ok") else "failed")
    return result


def reject_pending(pending: dict[str, Any]) -> None:
    repo.resolve_pending_action(int(pending["id"]), "cancelled")
    repo.add_integration_action(
        int(pending["org_id"]), pending["service"], pending["action"], pending["args"],
        "proposed", result={"cancelled": True}, agent_id=int(pending["agent_id"]),
        room_id=int(pending["room_id"]),
    )


def describe(action: str, arguments: dict[str, Any]) -> str:
    if action == "calendar_create_event":
        title = arguments.get("summary") or arguments.get("title") or "event"
        start = arguments.get("start_datetime") or arguments.get("start") or "?"
        return f'create calendar event "{title}" at {start}'
    if action == "gmail_send":
        to = arguments.get("recipient_email") or arguments.get("to") or "the recipient"
        subject = arguments.get("subject") or "(no subject)"
        return f'send an email to {to} with subject "{subject}"'
    return f"run {action}"


def confirm_intent(text: str) -> Optional[bool]:
    stripped = (text or "").strip()
    if AFFIRMATIVE.match(stripped):
        return True
    if NEGATIVE.match(stripped):
        return False
    return None


def action_catalogue() -> dict[str, Any]:
    return {
        "services": SERVICES,
        "actions": ACTION_SLUGS,
        "confirm_required": sorted(CONFIRM_REQUIRED),
        "safe_actions": sorted(SAFE_ACTIONS),
    }
