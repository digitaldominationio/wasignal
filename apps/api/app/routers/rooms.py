"""Rooms, transcripts and exclusions."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import repo
from ..deps import current_account, room_or_404
from ..schemas import ExclusionBody

router = APIRouter(prefix="/dashboard", tags=["rooms"])


@router.get("/rooms")
def list_rooms(account: dict = Depends(current_account)) -> dict:
    return {"items": repo.list_rooms(int(account["id"]))}


@router.get("/rooms/{room_id}/messages")
def room_messages(
    room_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    before_ts: int | None = Query(default=None),
    account: dict = Depends(current_account),
) -> dict:
    room_or_404(account, room_id)
    messages = repo.list_messages(room_id, limit=limit, before_ts=before_ts)
    return {"items": messages, "room_id": room_id}


@router.post("/chat-exclusions")
def create_exclusions(body: ExclusionBody, account: dict = Depends(current_account)) -> dict:
    for room_id in body.room_ids:
        room_or_404(account, room_id)
        repo.set_exclusion(int(account["id"]), room_id, True)
    return {"excluded": body.room_ids}


@router.get("/chat-exclusions")
def list_exclusions(account: dict = Depends(current_account)) -> dict:
    rooms = [room for room in repo.list_rooms(int(account["id"])) if room["is_excluded"]]
    return {"items": rooms}


@router.delete("/chat-exclusions/{room_id}")
def delete_exclusion(room_id: int, account: dict = Depends(current_account)) -> dict:
    room_or_404(account, room_id)
    repo.set_exclusion(int(account["id"]), room_id, False)
    return {"room_id": room_id, "excluded": False}


@router.get("/contacts")
def contacts(q: str = Query(default="", max_length=100), account: dict = Depends(current_account)) -> dict:
    rooms = repo.list_rooms(int(account["id"]))
    needle = q.lower().strip()
    items = [
        {"room_id": room["id"], "name": room["display_name"], "kind": room["kind"], "external_id": room["external_id"]}
        for room in rooms
        if not needle or needle in room["display_name"].lower()
    ]
    return {"items": items[:20]}


@router.post("/rooms/{room_id}/owner-reply")
async def owner_reply(room_id: int, text: str, account: dict = Depends(current_account)) -> dict:
    """Simulates the human typing in WhatsApp — arms human-active-pause."""
    from ..services.inbound import handle_owner_reply

    room = room_or_404(account, room_id)
    result = await handle_owner_reply(account, room, text)
    return result.as_dict()
