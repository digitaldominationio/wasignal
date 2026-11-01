"""The partner's own thread with the main agent.

Same pipeline as WhatsApp — that is the point: a dashboard message is just an
inbound message with a different source.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import repo
from ..deps import current_account, room_or_404
from ..schemas import ChatSendBody
from ..services.inbound import handle_inbound

router = APIRouter(prefix="/dashboard/chat", tags=["chat"])


def _default_room(account: dict) -> dict:
    system = repo.system_room(int(account["id"]))
    if system is not None:
        return system
    rooms = repo.list_rooms(int(account["id"]))
    if not rooms:
        raise HTTPException(status_code=404, detail="no_rooms")
    for room in rooms:
        if room["kind"] == "dm":
            return room
    return rooms[0]


@router.get("/messages")
def list_messages(
    limit: int = Query(default=50, ge=1, le=200),
    before_ts: Optional[int] = None,
    after_ts: Optional[int] = None,
    room_id: Optional[int] = None,
    account: dict = Depends(current_account),
) -> dict:
    room = room_or_404(account, room_id) if room_id else _default_room(account)
    items = repo.list_messages(int(room["id"]), limit=limit, before_ts=before_ts)
    if after_ts is not None:
        items = [item for item in items if int(item["ts"]) >= int(after_ts)]
    return {"room_id": room["id"], "items": items, "cursor": items[0]["ts"] if items else None}


@router.post("/messages")
async def send_message(body: ChatSendBody, account: dict = Depends(current_account)) -> dict:
    if not (body.text or body.media_url):
        raise HTTPException(status_code=422, detail="text_or_media_required")
    room = room_or_404(account, body.room_id) if body.room_id else _default_room(account)
    media = [{"url": body.media_url, "type": "image"}] if body.media_url else []
    result = await handle_inbound(
        account, room,
        text=body.text or "(media)",
        sender="dashboard", sender_name="Owner",
        media=media, source="dashboard",
    )
    payload = result.as_dict()
    # Mirror the observed contract: 200 only when the turn was admitted.
    if not result.accepted:
        if result.stage == "subscription_inactive":
            raise HTTPException(status_code=402, detail="subscription_inactive")
        if result.stage == "failed":
            raise HTTPException(status_code=503, detail={"stage": "agent", "reason": result.reason})
        raise HTTPException(status_code=409, detail=result.stage)
    return payload
