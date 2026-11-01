"""Inbound pipeline: gates, admission, delivery states."""
from __future__ import annotations

import asyncio

from app import repo
from app.services import outbound
from app.services.inbound import handle_inbound


def _agent(account, room, **overrides):
    payload = {
        "name": "Counsellor",
        "system_prompt": "Answer admissions questions.",
        "trigger_type": "event",
        "trigger_scope": "room",
        "room_id": room["id"],
        "capabilities": ["read", "send"],
    }
    payload.update(overrides)
    return repo.create_agent(int(account["id"]), payload)


def test_inbound_runs_agent_and_delivers(fresh_account):
    account = fresh_account
    room = repo.ensure_room(int(account["id"]), "911111110001@s.whatsapp.net", "dm", "Aarav")
    _agent(account, room)

    result = asyncio.run(handle_inbound(
        account, room, text="What is the fee for the dropper batch?", sender_name="Aarav",
    ))

    assert result.accepted is True, result
    assert result.stage == "admitted"
    assert result.reply

    newest = repo.list_messages(int(room["id"]), limit=1)[0]
    assert newest["direction"] == "out"
    assert newest["status"] == "accepted"

    assert any(row["message_id"] == newest["id"] for row in repo.queued_outbox())

    asyncio.run(outbound.drain_once())
    assert repo.list_messages(int(room["id"]), limit=1)[0]["status"] == "delivered"


def test_excluded_room_never_reaches_agent(fresh_account):
    account = fresh_account
    room = repo.ensure_room(int(account["id"]), "911111110002@s.whatsapp.net", "dm", "Family")
    _agent(account, room)
    repo.set_exclusion(int(account["id"]), int(room["id"]), True)
    room = repo.get_room(int(account["id"]), int(room["id"]))

    result = asyncio.run(handle_inbound(account, room, text="fee?"))
    assert result.accepted is False
    assert result.stage == "excluded"
    assert result.reply == ""


def test_read_only_agent_is_not_allowed_to_send(fresh_account):
    account = fresh_account
    room = repo.ensure_room(int(account["id"]), "911111110003@s.whatsapp.net", "dm", "Watcher")
    _agent(account, room, name="Watcher", capabilities=["read"])

    result = asyncio.run(handle_inbound(account, room, text="fee?"))
    assert result.accepted is False
    assert result.stage == "read_only"


def test_human_pause_skips_automation(fresh_account):
    account = fresh_account
    room = repo.ensure_room(int(account["id"]), "911111110004@s.whatsapp.net", "dm", "Owner chat")
    _agent(account, room)

    asyncio.run(handle_inbound(account, room, text="I'll take this one", source="owner", is_human_owner=True))
    result = asyncio.run(handle_inbound(account, room, text="fee?"))

    assert result.accepted is False
    assert result.stage == "paused"


def test_handover_stops_further_replies(fresh_account):
    account = fresh_account
    room = repo.ensure_room(int(account["id"]), "911111110005@s.whatsapp.net", "dm", "Upset parent")
    agent = _agent(account, room)

    first = asyncio.run(handle_inbound(account, room, text="I want to speak to a human please"))
    assert first.accepted is True
    assert "team" in first.reply.lower()

    lane = repo.get_lane(agent["id"], int(room["id"]))
    assert lane["handed_over"] == 1

    second = asyncio.run(handle_inbound(account, room, text="hello?"))
    assert second.accepted is False
    assert second.stage == "handover"
