"""Channel contract.

A channel is the only place that knows how bytes reach WhatsApp. Everything
upstream (agent runtime, scheduler, notifier) writes to the outbox and lets the
worker choose a channel per account. Implement this to plug in:

  * a linked-device bridge (whatsmeow / Baileys / mautrix-whatsapp)
  * Meta WhatsApp Cloud API (see meta.py)
  * a BSP such as Plivo/Twilio

`send` must be idempotent per (room, text, media) if your transport can retry,
or the worker will duplicate messages on a crash between send and commit.
"""
from __future__ import annotations

from typing import Any, Protocol


class ChannelError(RuntimeError):
    pass


class Channel(Protocol):
    name: str

    async def send(self, account: dict[str, Any], room: dict[str, Any], text: str,
                   media: list[dict[str, Any]] | None = None) -> str:
        """Deliver one outbound message. Return a transport id or 'ok'."""

    async def start_link(self, account: dict[str, Any], method: str = "qr") -> dict[str, Any]:
        """Begin linking a number. Return {state, qr_image_base64?}."""

    async def link_status(self, account: dict[str, Any]) -> dict[str, Any]:
        """One of pending | connecting | connected | expired | failed | idle."""

    async def disconnect(self, account: dict[str, Any]) -> dict[str, Any]:
        """Unlink the number. Best effort; local cleanup is the caller's job."""
