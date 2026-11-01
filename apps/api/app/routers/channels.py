"""WhatsApp connection lifecycle (QR / pairing code).

The stub channel fakes the clock so the UI can be built without a bridge.
See docs/BRIDGE.md for what a real adapter must implement.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import repo
from ..channels import get_channel
from ..deps import current_account
from ..services import notifications

router = APIRouter(prefix="/dashboard/whatsapp", tags=["whatsapp"])


class StartLinkBody(BaseModel):
    login_method: str = "qr"


@router.post("/start-link")
async def start_link(body: StartLinkBody | None = None, account: dict = Depends(current_account)) -> dict:
    channel = get_channel()
    method = (body.login_method if body else "qr") or "qr"
    result = await channel.start_link(account, method)
    return {**result, "account_id": account["id"]}


@router.get("/link-status")
async def link_status(account: dict = Depends(current_account)) -> dict:
    channel = get_channel()
    result = await channel.link_status(account)
    if result.get("state") == "connected" and not account.get("wa_number"):
        number = "+910000000000"
        repo.set_account_number(int(account["id"]), number)
        repo.set_wa_linked(int(account["partner_pid"]), True)
        notifications.whatsapp_connected_message({**account, "wa_number": number}, number)
    return result


@router.delete("")
async def disconnect(account: dict = Depends(current_account)) -> dict:
    channel = get_channel()
    result = await channel.disconnect(account)
    repo.set_account_number(int(account["id"]), "")
    repo.set_wa_linked(int(account["partner_pid"]), False)
    notifications.whatsapp_disconnected_message(account)
    return result


@router.get("/lists")
def lists(account: dict = Depends(current_account)) -> dict:
    """WhatsApp labels, for label-scoped follow-ups."""
    return {"lists": [], "has_label_data": False,
            "note": "labels come from the bridge; no label state held yet"}
