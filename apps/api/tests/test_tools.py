"""Capabilities, knowledge retrieval, memory, webhook schema validation."""
from __future__ import annotations

import asyncio

from app import repo
from app.agent.tools import ToolContext, execute
from app.services import knowledge


def test_send_to_another_room_requires_send_other(fresh_account):
    account = fresh_account
    source = repo.ensure_room(int(account["id"]), "911111120001@s.whatsapp.net", "dm", "Lead")
    target = repo.ensure_room(int(account["id"]), "120363000000000777@g.us", "group", "Team")
    agent = repo.create_agent(int(account["id"]), {
        "name": "No cross-chat",
        "system_prompt": "x",
        "capabilities": ["read", "send"],
    })
    ctx = ToolContext(account=account, room=source, agent=agent)

    result = asyncio.run(execute("send_to_room", {"room_id": target["id"], "text": "hello"}, ctx))
    assert result["ok"] is False
    assert "not permitted" in result["error"]


def test_sending_to_the_trigger_room_is_allowed(fresh_account):
    account = fresh_account
    source = repo.ensure_room(int(account["id"]), "911111120002@s.whatsapp.net", "dm", "Lead")
    agent = repo.create_agent(int(account["id"]), {
        "name": "Same-chat send",
        "system_prompt": "x",
        "capabilities": ["read", "send"],
    })
    ctx = ToolContext(account=account, room=source, agent=agent)

    result = asyncio.run(execute("send_to_room", {"room_id": source["id"], "text": "hi there"}, ctx))
    assert result["ok"] is True
    assert any(row["text"] == "hi there" for row in repo.queued_outbox())


def test_cross_chat_send_queues_message(fresh_account):
    account = fresh_account
    source = repo.ensure_room(int(account["id"]), "911111120003@s.whatsapp.net", "dm", "Lead")
    target = repo.ensure_room(int(account["id"]), "120363000000000778@g.us", "group", "Team")
    agent = repo.create_agent(int(account["id"]), {
        "name": "Cross-chat",
        "system_prompt": "x",
        "capabilities": ["read", "send", "send_other"],
    })
    ctx = ToolContext(account=account, room=source, agent=agent)

    result = asyncio.run(execute("send_to_room", {"room_id": target["id"], "text": "lead is hot"}, ctx))
    assert result["ok"] is True
    assert any(row["room_id"] == target["id"] and row["text"] == "lead is hot" for row in repo.queued_outbox())


def test_knowledge_search_finds_seeded_entry(account):
    hits = knowledge.search(int(account["id"]), "NEET dropper batch fee")
    assert hits
    assert "1,45,000" in hits[0]["content"]


def test_memory_roundtrip(fresh_account):
    account = fresh_account
    room = repo.ensure_room(int(account["id"]), "911111120004@s.whatsapp.net", "dm", "Lead")
    agent = repo.create_agent(int(account["id"]), {"name": "Memory", "system_prompt": "x", "room_id": room["id"]})
    repo.set_memory(agent["id"], "budget", "1.4 lakh")
    assert repo.memory_block(agent["id"], 1000) == "budget: 1.4 lakh"
    assert repo.delete_memory(agent["id"], "budget") is True
    assert repo.memory_block(agent["id"], 1000) == ""


def test_webhook_missing_required_field_fails_before_network(fresh_account):
    account = fresh_account
    room = repo.ensure_room(int(account["id"]), "911111120005@s.whatsapp.net", "dm", "Lead")
    webhook = repo.create_webhook(int(account["id"]), {
        "name": "Strict hook",
        "description": "always fails validation",
        "url": "https://httpbin.org/post",
        "method": "POST",
        "body_fields": [
            {"key": "phone", "description": "phone", "type": "string", "required": True, "source": "agent"},
        ],
    })
    agent = {"id": 0, "account_id": account["id"], "capabilities": ["read", "send"]}
    ctx = ToolContext(account=account, room=room, agent=agent)

    result = asyncio.run(execute(f"webhook_{webhook['id']}", {}, ctx))
    assert result["ok"] is False
    assert "missing required fields" in result["error"]
