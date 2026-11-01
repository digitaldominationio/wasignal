"""System notifications in the assistant inbox.

OTPs, link events and account alerts are written as messages in the partner's
own thread, so the inbox is the single place you look when something needs you.
They are inserted directly (not through the inbound pipeline) so they never
trigger an agent or a reply.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from .. import repo


def system_message(
    account: dict[str, Any],
    text: str,
    *,
    media: Optional[list[dict[str, Any]]] = None,
    source: str = "system",
    timestamp: Optional[int] = None,
) -> dict[str, Any]:
    room = repo.ensure_system_room(int(account["id"]))
    return repo.add_message(
        int(account["id"]),
        int(room["id"]),
        "in",
        text,
        sender="wasignal",
        sender_name="Wasignal",
        media=media or [],
        source=source,
        ts=timestamp or int(time.time()),
    )


def otp_message(account: dict[str, Any], code: str) -> dict[str, Any]:
    text = f"Your dashboard OTP is {code}. Valid for the next 10 minutes."
    # A double-submitted login form must not stack identical OTPs in the inbox.
    existing = repo.recent_system_message(int(account["id"]), text, int(time.time()) - 60)
    if existing is not None:
        return existing
    return system_message(account, text, source="otp")


def whatsapp_qr_message(account: dict[str, Any]) -> dict[str, Any]:
    return system_message(
        account,
        "Scan this QR code in WhatsApp → Settings → Linked devices → Link a device",
        media=[{"type": "qr", "name": "WhatsApp QR code", "url": None}],
        source="system",
    )


def whatsapp_connected_message(account: dict[str, Any], number: str) -> dict[str, Any]:
    return system_message(
        account,
        f"WhatsApp connected · {number}. Your automations are live.",
        source="system",
    )


def whatsapp_disconnected_message(account: dict[str, Any]) -> dict[str, Any]:
    return system_message(
        account,
        "[WHATSAPP_ACCOUNT_DISCONNECTED] Your WhatsApp account has been disconnected from Wasignal. "
        "Please re-link your WhatsApp account to continue using Wasignal.",
        source="system",
    )
