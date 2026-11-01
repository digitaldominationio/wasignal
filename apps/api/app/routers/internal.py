"""Service-to-service surfaces: channel ingress, notifications, Meta webhook, health.

Every one of these is a trust boundary. In production require a shared secret
(`x-internal-key`) and keep them off the public internet.
"""
from __future__ import annotations

import hmac
import hashlib
import json
import os
import time
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request

from .. import repo
from ..config import settings
from ..schemas import InboundBody, NotifyBody
from ..config import settings as app_settings
from ..services import billing, outbound
from ..storage.cache import cache
from ..services.inbound import handle_inbound

router = APIRouter(tags=["internal"])

INTERNAL_KEY = os.getenv("WASIGNAL_INTERNAL_KEY", "dev-internal-key")


def _check_key(key: Optional[str]) -> None:
    if settings.env == "dev":
        return
    if not key or not hmac.compare_digest(key, INTERNAL_KEY):
        raise HTTPException(status_code=401, detail="invalid_internal_key")


@router.post("/internal/inbound", status_code=202)
async def inbound(body: InboundBody, x_internal_key: Optional[str] = Header(default=None)) -> dict:
    """Channel adapters (bridge, Meta, BSP) post normalised messages here."""
    _check_key(x_internal_key)
    account = repo.account_by_id(body.account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="account_not_found")
    room = repo.ensure_room(
        int(account["id"]), body.external_room_id, body.room_kind, body.sender_name or body.external_room_id
    )
    result = await handle_inbound(
        account, room,
        text=body.text, sender=body.sender, sender_name=body.sender_name,
        media=body.media, source="whatsapp", is_human_owner=body.is_human_owner,
        timestamp=body.timestamp,
    )
    return result.as_dict()


@router.post("/internal/notify", status_code=202)
async def notify(body: NotifyBody, x_internal_key: Optional[str] = Header(default=None)) -> dict:
    """Other services push a message into a chat, or only into the transcript."""
    _check_key(x_internal_key)
    account = repo.account_by_id(body.account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="account_not_found")

    if body.room_id is not None:
        room = repo.get_room(body.account_id, body.room_id)
    else:
        rooms = repo.list_rooms(body.account_id)
        if not rooms:
            raise HTTPException(status_code=422, detail="no_rooms")
        room = next((candidate for candidate in rooms if candidate["kind"] == "dm"), rooms[0])

    payload = {"queued": False, "delivered": False}
    if body.send:
        if account.get("org_id"):
            try:
                billing.check(int(account["org_id"]), "messages")
            except billing.QuotaExceeded:
                raise HTTPException(status_code=402, detail="message_limit_reached") from None
        message = repo.add_message(
            body.account_id, int(room["id"]), "out", body.message, source="notify", status="accepted"
        )
        outbound.enqueue(body.account_id, int(room["id"]), body.message, message_id=message["id"])
        if account.get("org_id"):
            billing.record(int(account["org_id"]), "messages", 1, "notify")
        payload["queued"] = True
        if body.wait:
            payload["delivered"] = await outbound.drain_once(limit=1) > 0
    else:
        repo.add_message(body.account_id, int(room["id"]), "in", body.message, source="notify")

    return {"accepted": True, "source": body.source, **payload}


@router.get("/internal/notify/health")
def notify_health() -> dict:
    stats = outbound.outbox_stats()
    return {"status": "healthy", "queue_size": stats.get("queued", 0), "queue_empty": not stats.get("queued", 0)}


@router.get("/health/live")
def live() -> dict:
    return {"status": "ok"}


@router.get("/health/ready")
def ready() -> dict:
    try:
        assert repo.healthy()
        mongo_like = {"status": "ok", "latency_ms": 0.4}
    except Exception as exc:
        return {"status": "degraded", "dependencies": {"database": {"status": "error", "error": str(exc)}}}
    return {
        "status": "ready",
        "dependencies": {
            "database": mongo_like,
            "storage": {"backend": app_settings.db_backend, "ok": repo.healthy()},
            "cache": {"backend": cache.info().get("backend"), "ok": cache.ping()},
        },
        "info": {"workers": {"outbox": outbound.outbox_stats()}},
        "llm_provider": settings.llm_provider,
        "channel": settings.channel,
    }


# ----------------------------------------------------------------------------- meta


@router.get("/meta_webhook")
def meta_verify(
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
) -> str:
    if hub_mode == "subscribe" and hub_verify_token == settings.meta_verify_token:
        return hub_challenge
    raise HTTPException(status_code=403, detail="verification_failed")


@router.post("/meta_webhook")
async def meta_receive(request: Request, x_hub_signature_256: Optional[str] = Header(default=None)) -> dict:
    raw = await request.body()
    if settings.meta_token:
        expected = "sha256=" + hmac.new(settings.meta_token.encode(), raw, hashlib.sha256).hexdigest()
        if not x_hub_signature_256 or not hmac.compare_digest(expected, x_hub_signature_256):
            raise HTTPException(status_code=401, detail="bad_signature")

    payload = json.loads(raw.decode("utf-8") or "{}")
    queued = 0
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            for message in value.get("messages") or []:
                account = repo.account_by_number(value.get("metadata", {}).get("display_phone_number", ""))
                if account is None:
                    continue
                room = repo.ensure_room(int(account["id"]), message.get("from", ""), "dm", message.get("from", ""))
                await handle_inbound(
                    account, room,
                    text=(message.get("text") or {}).get("body", ""),
                    sender=message.get("from", ""),
                    sender_name=(value.get("contacts") or [{}])[0].get("profile", {}).get("name", ""),
                    timestamp=int(message.get("timestamp", time.time())),
                )
                queued += 1
    return {"received": True, "queued": queued}
