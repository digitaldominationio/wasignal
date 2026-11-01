"""Agents (the dashboard calls them automations), their lanes, memory and follow-ups."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import repo
from ..agent.runtime import run_agent
from ..deps import agent_or_404, current_account, room_or_404
from ..schemas import (
    AgentBody,
    AgentPatch,
    FollowUpRulesBody,
    FollowUpWindowBody,
    LaneResetBody,
    TestRunBody,
)

router = APIRouter(prefix="/dashboard", tags=["agents"])

BUILT_IN_SUITES = [
    {"id": "messaging", "name": "Messaging", "description": "Read the chat, reply, send media"},
    {"id": "media", "name": "Media", "description": "Send images, video and PDFs"},
    {"id": "contacts", "name": "Contacts", "description": "Look up customers and groups"},
    {"id": "scheduling", "name": "Scheduling", "description": "Set reminders and scheduled sends"},
    {"id": "knowledge", "name": "Knowledge", "description": "Search the attached knowledge sources"},
    {"id": "labels", "name": "Labels", "description": "Read WhatsApp labels and follow-up state"},
]


@router.get("/agents")
def list_agents(include_paused: bool = True, account: dict = Depends(current_account)) -> dict:
    return {"items": repo.list_agents(int(account["id"]), include_paused)}


@router.post("/agents", status_code=201)
def create_agent(body: AgentBody, account: dict = Depends(current_account)) -> dict:
    payload = body.model_dump()
    if payload.get("room_id") is not None:
        room_or_404(account, int(payload["room_id"]))
    return repo.create_agent(int(account["id"]), payload)


@router.get("/agents/{agent_id}")
def get_agent(agent_id: int, account: dict = Depends(current_account)) -> dict:
    return agent_or_404(account, agent_id)


@router.patch("/agents/{agent_id}")
def patch_agent(agent_id: int, body: AgentPatch, account: dict = Depends(current_account)) -> dict:
    agent_or_404(account, agent_id)
    patch = {key: value for key, value in body.model_dump().items() if value is not None}
    return repo.update_agent(int(account["id"]), agent_id, patch)


@router.post("/agents/{agent_id}/toggle-status")
def toggle(agent_id: int, account: dict = Depends(current_account)) -> dict:
    agent_or_404(account, agent_id)
    return repo.toggle_agent(int(account["id"]), agent_id)


@router.post("/agents/test-run")
async def test_run(body: TestRunBody, account: dict = Depends(current_account)) -> dict:
    """Dry run: the agent never writes to WhatsApp here.

    Side effects that remain real: memory writes and handover flags. Keep that
    in mind when testing against production data.
    """
    if body.agent_id is None:
        raise HTTPException(status_code=422, detail="agent_id_required_for_test_run")
    agent = dict(agent_or_404(account, body.agent_id))
    agent["system_prompt"] = body.system_prompt
    agent["capabilities"] = [cap for cap in agent["capabilities"] if cap != "send_other"]
    agent["webhook_ids"] = []

    rooms = repo.list_rooms(int(account["id"]))
    if body.room_id is not None:
        room = room_or_404(account, body.room_id)
    elif agent.get("room_id"):
        room = room_or_404(account, int(agent["room_id"]))
    elif rooms:
        room = rooms[0]
    else:
        raise HTTPException(status_code=422, detail="no_room_available")

    history = repo.history(int(room["id"]), 20)
    outcome = await run_agent(
        agent, account, room,
        text=body.test_message or body.trigger_message,
        history=history, sender_name="Test customer", trigger="test",
    )
    return {
        "run_id": outcome.run_id,
        "status": outcome.status,
        "reply": outcome.reply,
        "iterations": outcome.iterations,
        "tokens": outcome.tokens,
        "reason": outcome.reason,
        "test": True,
    }


@router.get("/agent-tools")
def agent_tools(account: dict = Depends(current_account)) -> dict:
    return {
        "built_in": BUILT_IN_SUITES,
        "webhooks": repo.list_webhooks(int(account["id"])),
    }


@router.get("/runs")
def list_runs(limit: int = 50, agent_id: Optional[int] = None, account: dict = Depends(current_account)) -> dict:
    return {"items": repo.list_runs(int(account["id"]), agent_id, limit)}


@router.get("/agents/{agent_id}/runs")
def agent_runs(agent_id: int, limit: int = 50, account: dict = Depends(current_account)) -> dict:
    agent_or_404(account, agent_id)
    return {"items": repo.list_runs(int(account["id"]), agent_id, limit)}


# ------------------------------------------------------------------------ lanes


@router.get("/agents/{agent_id}/lanes")
def lanes(agent_id: int, account: dict = Depends(current_account)) -> dict:
    agent_or_404(account, agent_id)
    return {"items": repo.list_lanes(agent_id)}


@router.post("/agents/{agent_id}/lanes/reset")
def reset_lane(agent_id: int, body: LaneResetBody, account: dict = Depends(current_account)) -> dict:
    agent_or_404(account, agent_id)
    rooms = [room_or_404(account, body.room_id)] if body.room_id else repo.list_rooms(int(account["id"]))
    lane_key = body.lane or "main"
    for room in rooms:
        repo.reset_lane(agent_id, int(room["id"]), lane_key)
    return {"reset": len(rooms), "lane": lane_key}


@router.post("/agents/{agent_id}/lanes/clear-handover")
def clear_handover(agent_id: int, body: LaneResetBody, account: dict = Depends(current_account)) -> dict:
    agent_or_404(account, agent_id)
    rooms = [room_or_404(account, body.room_id)] if body.room_id else repo.list_rooms(int(account["id"]))
    for room in rooms:
        repo.set_handover(agent_id, int(room["id"]), False, body.lane or "main")
    return {"cleared": len(rooms)}


# ----------------------------------------------------------------------- memory


@router.get("/agents/{agent_id}/memory")
def get_memory(agent_id: int, key: Optional[str] = None, room_id: Optional[int] = None,
               lane: Optional[str] = None, account: dict = Depends(current_account)) -> dict:
    agent_or_404(account, agent_id)
    items = repo.list_memory(agent_id)
    if key is not None:
        items = [item for item in items if item["key"] == key]
    payload: dict[str, Any] = {"items": items}
    if room_id is not None:
        lane_row = repo.get_lane(agent_id, room_id, lane or "main")
        payload["session_memory"] = lane_row["session_memory"]
        payload["pending_steps"] = lane_row["pending_steps"]
        payload["handed_over"] = bool(lane_row["handed_over"])
    return payload


@router.put("/agents/{agent_id}/memory/{key}")
def put_memory(agent_id: int, key: str, body: dict, account: dict = Depends(current_account)) -> dict:
    agent_or_404(account, agent_id)
    value = str(body.get("value", ""))
    if len(value) > 10_000:
        raise HTTPException(status_code=422, detail="value_too_long")
    repo.set_memory(agent_id, key[:120], value)
    return {"key": key, "stored": True}


@router.delete("/agents/{agent_id}/memory/{key}")
def delete_memory(agent_id: int, key: str, account: dict = Depends(current_account)) -> dict:
    agent_or_404(account, agent_id)
    return {"key": key, "deleted": repo.delete_memory(agent_id, key)}


# -------------------------------------------------------------------- knowledge


@router.put("/agents/{agent_id}/knowledge")
def attach_knowledge(agent_id: int, body: dict, account: dict = Depends(current_account)) -> dict:
    agent_or_404(account, agent_id)
    source_ids = [int(value) for value in body.get("source_ids", [])]
    repo.set_agent_knowledge(agent_id, source_ids)
    return {"source_ids": source_ids}


@router.get("/agents/{agent_id}/knowledge")
def get_agent_knowledge(agent_id: int, account: dict = Depends(current_account)) -> dict:
    agent_or_404(account, agent_id)
    return {"items": repo.agent_knowledge_sources(agent_id), "source_ids": repo.agent_knowledge_ids(agent_id)}


# -------------------------------------------------------------------- followups


@router.get("/agents/{agent_id}/follow-up-rules")
def get_followup_rules(agent_id: int, account: dict = Depends(current_account)) -> dict:
    agent_or_404(account, agent_id)
    return repo.get_followup_rules(agent_id)


@router.put("/agents/{agent_id}/follow-up-rules")
def put_followup_rules(agent_id: int, body: FollowUpRulesBody, account: dict = Depends(current_account)) -> dict:
    agent_or_404(account, agent_id)
    return repo.put_followup_rules(int(account["id"]), agent_id, body.model_dump())


@router.get("/agents/{agent_id}/follow-up-runs")
def followup_runs(agent_id: int, limit: int = 50, account: dict = Depends(current_account)) -> dict:
    agent_or_404(account, agent_id)
    return {"items": repo.list_followup_runs(agent_id, limit)}


@router.get("/agents/{agent_id}/follow-up-window")
def get_window(agent_id: int, account: dict = Depends(current_account)) -> dict:
    agent_or_404(account, agent_id)
    return {"send_window": repo.get_followup_rules(agent_id).get("send_window")}


@router.put("/agents/{agent_id}/follow-up-window")
def put_window(agent_id: int, body: FollowUpWindowBody, account: dict = Depends(current_account)) -> dict:
    agent_or_404(account, agent_id)
    current = repo.get_followup_rules(agent_id)
    current["send_window"] = body.model_dump(exclude_none=True)
    return repo.put_followup_rules(int(account["id"]), agent_id, current)
