"""Meta WhatsApp Cloud API adapter (the official path).

Only outbound text is implemented: inbound arrives on /meta_webhook. Wiring it
up requires a Meta app, a phone number id and a permanent token.
"""
from __future__ import annotations

from typing import Any

import httpx

from ..config import settings
from .base import ChannelError

GRAPH = "https://graph.facebook.com/v21.0"


class MetaCloudChannel:
    name = "meta"

    def __init__(self) -> None:
        if not settings.meta_token or not settings.meta_phone_number_id:
            raise ChannelError("Meta channel needs WASIGNAL_META_TOKEN and WASIGNAL_META_PHONE_NUMBER_ID")

    async def send(self, account: dict[str, Any], room: dict[str, Any], text: str,
                   media: list[dict[str, Any]] | None = None) -> str:
        to = room["external_id"].split("@")[0]
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{GRAPH}/{settings.meta_phone_number_id}/messages",
                headers={"Authorization": f"Bearer {settings.meta_token}"},
                json=payload,
            )
        if response.status_code >= 400:
            raise ChannelError(f"meta {response.status_code}: {response.text[:300]}")
        data = response.json()
        messages = data.get("messages") or [{}]
        return str(messages[0].get("id") or "ok")

    async def start_link(self, account: dict[str, Any], method: str = "qr") -> dict[str, Any]:
        raise ChannelError("Cloud API numbers are provisioned in Meta Business Manager, not linked by QR")

    async def link_status(self, account: dict[str, Any]) -> dict[str, Any]:
        return {"state": "connected" if account.get("wa_number") else "idle"}

    async def disconnect(self, account: dict[str, Any]) -> dict[str, Any]:
        raise ChannelError("Unlink the number in Meta Business Manager")
