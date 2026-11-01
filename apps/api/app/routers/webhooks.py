"""Webhooks are agent tools with a schema the model can read."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import repo
from ..agent.tools import ToolContext, _call_webhook
from ..deps import current_account, webhook_or_404
from ..schemas import WebhookBody, WebhookPatch

router = APIRouter(prefix="/dashboard/webhooks", tags=["webhooks"])


@router.get("")
def list_webhooks(account: dict = Depends(current_account)) -> dict:
    return {"items": repo.list_webhooks(int(account["id"]))}


@router.post("", status_code=201)
def create_webhook(body: WebhookBody, account: dict = Depends(current_account)) -> dict:
    return repo.create_webhook(int(account["id"]), body.model_dump())


@router.get("/{webhook_id}")
def get_webhook(webhook_id: int, account: dict = Depends(current_account)) -> dict:
    return webhook_or_404(account, webhook_id)


@router.patch("/{webhook_id}")
def patch_webhook(webhook_id: int, body: WebhookPatch, account: dict = Depends(current_account)) -> dict:
    webhook_or_404(account, webhook_id)
    return repo.update_webhook(int(account["id"]), webhook_id,
                               {k: v for k, v in body.model_dump().items() if v is not None})


@router.delete("/{webhook_id}")
def delete_webhook(webhook_id: int, account: dict = Depends(current_account)) -> dict:
    webhook_or_404(account, webhook_id)
    try:
        repo.delete_webhook(int(account["id"]), webhook_id)
    except ValueError:
        raise HTTPException(status_code=409, detail="webhook_in_use") from None
    return {"deleted": webhook_id}


@router.post("/{webhook_id}/test")
async def test_webhook(webhook_id: int, account: dict = Depends(current_account)) -> dict:
    webhook = webhook_or_404(account, webhook_id)
    rooms = repo.list_rooms(int(account["id"]))
    if not rooms:
        raise HTTPException(status_code=422, detail="no_room_available")
    agent = {"id": 0, "account_id": account["id"], "capabilities": ["read", "send"]}
    ctx = ToolContext(account=account, room=rooms[0], agent=agent)
    return await _call_webhook(f"webhook_{webhook['id']}", {}, ctx)


@router.get("/{webhook_id}/deliveries")
def deliveries(webhook_id: int, limit: int = 50, account: dict = Depends(current_account)) -> dict:
    webhook_or_404(account, webhook_id)
    return {"items": repo.list_deliveries(int(account["id"]), webhook_id, limit)}


@router.get("/{webhook_id}/deliveries/{delivery_id}")
def delivery(webhook_id: int, delivery_id: int, account: dict = Depends(current_account)) -> dict:
    webhook_or_404(account, webhook_id)
    items = [item for item in repo.list_deliveries(int(account["id"]), webhook_id, 200)
             if int(item["id"]) == delivery_id]
    if not items:
        raise HTTPException(status_code=404, detail="delivery_not_found")
    return items[0]
