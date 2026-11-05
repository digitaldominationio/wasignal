"""Integration broker: link, sync, tools, confirmations, audit."""
from __future__ import annotations

import asyncio
import random

import pytest
from fastapi.testclient import TestClient

from app import repo
from app.agent.runtime import run_agent
from app.agent.tools import ToolContext, execute, tool_specs
from app.config import settings
from app.main import app
from app.services import integrations


class FakeBroker:
    name = "composio"
    toolkit_slugs = {"google_calendar": "googlecalendar", "gmail": "gmail"}

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.linked: list[tuple[int, str]] = []
        self.accounts = [{
            "service": "google_calendar", "external_id": "ca_test", "status": "active",
            "toolkit": "googlecalendar",
        }]

    def link(self, org_id: int, auth_config_id: str, callback_url: str) -> dict:
        self.linked.append((org_id, auth_config_id))
        return {"redirect_url": "https://composio.test/connect", "external_id": "ca_pending"}

    def list_accounts(self, org_id: int) -> list[dict]:
        return list(self.accounts)

    def execute(self, org_id: int, tool_slug: str, arguments: dict, connected_account_id=None) -> dict:
        self.calls.append((tool_slug, arguments))
        return {"ok": True, "data": {"id": "evt_1", "summary": arguments.get("summary", "event")}}

    def disconnect(self, org_id: int, service: str) -> None:
        self.accounts = []


@pytest.fixture()
def broker(monkeypatch):
    fake = FakeBroker()
    monkeypatch.setattr(integrations, "get_broker", lambda org_id=None: fake)
    monkeypatch.setattr(integrations, "_auth_config", lambda org_id, service: f"ac_{service}")
    yield fake


def _phone(prefix: str) -> str:
    return f"{prefix}{random.randint(100000, 999999)}"


def _tenant(client: TestClient, phone: str, name: str) -> dict:
    client.post("/dashboard/auth/signup", json={"name": name, "phone": phone}).raise_for_status()
    code = client.post("/dashboard/auth/request-otp", json={"phone": phone}).json()["dev_code"]
    client.post("/dashboard/auth/verify-otp", json={"phone": phone, "otp": code}).raise_for_status()
    return client.get("/dashboard/organizations").json()["items"][0]


def _calendar_agent(account: dict, room: dict) -> dict:
    return repo.create_agent(int(account["id"]), {
        "name": "Scheduler",
        "system_prompt": "You are a scheduling assistant.",
        "trigger_type": "event",
        "trigger_scope": "room",
        "room_id": room["id"],
        "capabilities": ["read", "send", "calendar"],
    })


def test_connect_returns_redirect_and_records_pending(broker):
    with TestClient(app) as client:
        org = _tenant(client, _phone("9300"), "Connect Co")
        response = client.post("/dashboard/integrations/google_calendar/connect")
        assert response.status_code == 200, response.text
        assert response.json()["redirect_url"] == "https://composio.test/connect"

        row = repo.get_connected_account(int(org["id"]), "google_calendar")
        assert row["status"] == "pending"
        assert row["external_id"] == "ca_pending"

        # sync from the broker flips it to active
        listing = client.get("/dashboard/integrations").json()
        calendar = next(item for item in listing["services"] if item["id"] == "google_calendar")
        assert calendar["connected"] is True


def test_tools_appear_only_with_capability_and_connection(broker):
    with TestClient(app) as client:
        org = _tenant(client, _phone("9301"), "Tools Co")
        account = repo.list_org_accounts(int(org["id"]))[0]
        room = repo.ensure_room(int(account["id"]), "919900001111@s.whatsapp.net", "dm", "Lead")
        agent = _calendar_agent(account, room)

        names = {tool["name"] for tool in tool_specs(agent, int(org["id"]))}
        assert "calendar_create_event" not in names  # not connected yet

        repo.upsert_connected_account(
            int(org["id"]), "google_calendar", "googlecalendar", "ca_test", "active"
        )
        names = {tool["name"] for tool in tool_specs(agent, int(org["id"]))}
        assert {"calendar_list_events", "calendar_find_slot", "calendar_create_event"} <= names

        # read-only agent gets no calendar tools even when connected
        read_only = repo.create_agent(int(account["id"]), {
            "name": "Watcher", "system_prompt": "x", "room_id": room["id"], "capabilities": ["read"],
        })
        assert "calendar_create_event" not in {t["name"] for t in tool_specs(read_only, int(org["id"]))}


def test_safe_action_executes_and_audits(broker):
    with TestClient(app) as client:
        org = _tenant(client, _phone("9302"), "Safe Co")
        account = repo.list_org_accounts(int(org["id"]))[0]
        room = repo.ensure_room(int(account["id"]), "919900002222@s.whatsapp.net", "dm", "Lead")
        agent = _calendar_agent(account, room)
        repo.upsert_connected_account(int(org["id"]), "google_calendar", "googlecalendar", "ca_test", "active")

        ctx = ToolContext(account=account, room=room, agent=agent)
        result = asyncio.run(execute("calendar_list_events", {
            "time_min": "2026-11-04T00:00:00Z", "time_max": "2026-11-05T00:00:00Z",
        }, ctx))

        assert result["ok"] is True
        assert broker.calls[0][0] == "GOOGLECALENDAR_EVENTS_LIST"
        actions = repo.list_integration_actions(int(org["id"]))
        assert actions[0]["action"] == "calendar_list_events"
        assert actions[0]["status"] == "ok"


def test_write_action_requires_confirmation(broker):
    with TestClient(app) as client:
        org = _tenant(client, _phone("9303"), "Confirm Co")
        account = repo.list_org_accounts(int(org["id"]))[0]
        room = repo.ensure_room(int(account["id"]), "919900003333@s.whatsapp.net", "dm", "Lead")
        agent = _calendar_agent(account, room)
        repo.upsert_connected_account(int(org["id"]), "google_calendar", "googlecalendar", "ca_test", "active")

        ctx = ToolContext(account=account, room=room, agent=agent)
        result = asyncio.run(execute("calendar_create_event", {
            "summary": "Counselling", "start_datetime": "2026-11-05T16:00:00+05:30",
            "end_datetime": "2026-11-05T16:30:00+05:30",
        }, ctx))

        assert result["ok"] is True
        assert result["result"]["needs_confirmation"] is True
        assert broker.calls == []  # nothing executed yet
        pending = repo.pending_action_for_lane(int(agent["id"]), int(room["id"]), "main")
        assert pending is not None
        assert pending["action"] == "calendar_create_event"

        # confirming executes exactly once
        confirmed = integrations.confirm_pending(pending)
        assert confirmed["ok"] is True
        assert broker.calls[0][0] == "GOOGLECALENDAR_CREATE_EVENT"
        assert repo.pending_action_for_lane(int(agent["id"]), int(room["id"]), "main") is None


def test_runtime_confirms_pending_on_yes(broker):
    with TestClient(app) as client:
        org = _tenant(client, _phone("9304"), "Runtime Co")
        account = repo.list_org_accounts(int(org["id"]))[0]
        room = repo.ensure_room(int(account["id"]), "919900004444@s.whatsapp.net", "dm", "Lead")
        agent = _calendar_agent(account, room)
        repo.upsert_connected_account(int(org["id"]), "google_calendar", "googlecalendar", "ca_test", "active")
        repo.create_pending_action(
            int(org["id"]), int(agent["id"]), int(room["id"]), "main", "google_calendar",
            "calendar_create_event",
            {"summary": "Counselling", "start_datetime": "2026-11-05T16:00:00+05:30",
             "end_datetime": "2026-11-05T16:30:00+05:30"},
            "tok_test", int(__import__("time").time()) + 600,
        )

        outcome = asyncio.run(run_agent(
            agent, account, room, text="yes please book it", history=[], sender_name="Aarav",
        ))
        assert outcome.status in {"ok", "limit"}
        assert broker.calls[0][0] == "GOOGLECALENDAR_CREATE_EVENT"
        assert repo.pending_action_for_lane(int(agent["id"]), int(room["id"]), "main") is None


def test_confirm_intent():
    assert integrations.confirm_intent("yes book it") is True
    assert integrations.confirm_intent("Sure, go ahead") is True
    assert integrations.confirm_intent("no, cancel") is False
    assert integrations.confirm_intent("what time is it?") is None


class FakeComposioClass:
    created: list[str] = []
    toolkit_slugs = {"google_calendar": "googlecalendar", "gmail": "gmail"}

    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        self.api_key = api_key

    def validate(self) -> int:
        return 1

    def create_auth_config(self, toolkit_slug: str) -> str:
        FakeComposioClass.created.append(toolkit_slug)
        return f"ac_{toolkit_slug}"

    def list_accounts(self, org_id: int) -> list[dict]:
        return []

    def disconnect(self, org_id: int, service: str) -> None:
        return None


def test_tenant_saves_their_own_composio_key(monkeypatch):
    FakeComposioClass.created = []
    monkeypatch.setattr(integrations, "ComposioBroker", FakeComposioClass)
    phone_a, phone_b = _phone("9470"), _phone("9471")

    with TestClient(app) as a, TestClient(app) as b:
        org_a = _tenant(a, phone_a, "Broker Co A")
        _tenant(b, phone_b, "Broker Co B")

        saved = a.put("/dashboard/integrations/broker", json={"api_key": "ak_tenant_123456"})
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["configured"] is True
        assert body["auth_configs"] == {
            "google_calendar": "ac_googlecalendar",
            "gmail": "ac_gmail",
        }
        assert FakeComposioClass.created == ["googlecalendar", "gmail"]

        row = repo.get_broker_credential(int(org_a["id"]))
        assert row["encrypted_key"]
        assert "ak_tenant_123456" not in row["encrypted_key"]
        from app.services import secrets as secret_service
        assert secret_service.decrypt(row["encrypted_key"], row["nonce"]) == "ak_tenant_123456"

        assert a.get("/dashboard/integrations").json()["configured"] is True
        assert b.get("/dashboard/integrations").json()["configured"] is False

        revoked = a.delete("/dashboard/integrations/broker").json()
        assert revoked["configured"] is False


def test_member_cannot_save_broker_key(monkeypatch):
    monkeypatch.setattr(integrations, "ComposioBroker", FakeComposioClass)
    phone_owner, phone_member = _phone("9472"), _phone("9473")
    with TestClient(app) as owner, TestClient(app) as member:
        org = _tenant(owner, phone_owner, "Broker Roles")
        _tenant(member, phone_member, "Member Broker Own")
        partner = repo.partner_by_phone(phone_member)
        repo.add_membership(int(org["id"]), int(partner["pid"]), "member")

        response = member.put(
            f"/dashboard/integrations/broker?org_id={org['id']}",
            json={"api_key": "ak_member_should_fail"},
        )
        assert response.status_code == 403
