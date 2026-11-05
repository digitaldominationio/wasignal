"""Workspace API used by the SaaS shell: overview, connections, team, billing."""
from __future__ import annotations

import random

from fastapi.testclient import TestClient

from app.main import app


def _login(client: TestClient, phone: str = "9999000001") -> None:
    otp = client.post("/dashboard/auth/request-otp", json={"phone": phone})
    if otp.status_code == 404:
        client.post("/dashboard/auth/signup", json={"name": "Test Workspace", "phone": phone})
        otp = client.post("/dashboard/auth/request-otp", json={"phone": phone})
    code = otp.json()["dev_code"]
    client.post("/dashboard/auth/verify-otp", json={"phone": phone, "otp": code}).raise_for_status()


def test_overview_shape():
    with TestClient(app) as client:
        _login(client)
        body = client.get("/dashboard/overview").json()
        assert {"active_agents", "messages_today", "runs_today"} <= set(body["stats"])
        assert isinstance(body["attention"], list)


def test_connections_grouped_and_seeded_whatsapp():
    with TestClient(app) as client:
        _login(client)
        body = client.get("/dashboard/connections").json()
        assert body["whatsapp"]["required"] is True
        assert body["whatsapp"]["connected"] is True  # demo tenant is linked
        groups = {group["group"]: group for group in body["groups"]}
        assert {"Google", "Other"} <= set(groups)
        assert {item["id"] for item in groups["Google"]["items"]} >= {"gmail", "google_calendar"}


def test_new_account_starts_disconnected():
    phone = f"9888{random.randint(100000, 999999)}"
    with TestClient(app) as client:
        _login(client, phone)
        body = client.get("/dashboard/connections").json()
        assert body["whatsapp"]["connected"] is False

        started = client.post("/dashboard/connections/whatsapp/connect").json()
        assert started["state"] in {"pending", "connecting", "connected"}

        connected = client.get("/dashboard/whatsapp/link-status").json()
        assert connected["state"] in {"pending", "connecting", "connected"}


def test_oauth_connect_is_honest_about_not_being_configured():
    with TestClient(app) as client:
        _login(client)
        response = client.post("/dashboard/connections/gmail/connect")
        assert response.status_code == 501
        assert response.json()["detail"] == "oauth_not_configured"


def test_team_and_billing():
    with TestClient(app) as client:
        _login(client)
        team = client.get("/dashboard/team").json()
        assert team["members"][0]["role"] == "owner"
        assert team["members"][0]["is_owner"] is True
        assert team["organization"]["name"]

        plans = client.get("/dashboard/billing/plans").json()["items"]
        assert [plan["id"] for plan in plans] == ["trial", "growth", "scale"]

        status = client.get("/dashboard/billing/status").json()
        assert status["plan"]["id"] in {"trial", "growth", "scale"}
        assert "limits" in status and "usage" in status


def test_inbox_records_otp_and_link_events():
    phone = f"9777{random.randint(100000, 999999)}"
    with TestClient(app) as client:
        _login(client, phone)  # signup path

        # the assistant thread is the default room and has the OTP notification
        inbox = client.get("/dashboard/chat/messages?limit=30").json()
        assert any("Your dashboard OTP is" in message["text"] for message in inbox["items"])
        assert any(message["source"] == "otp" for message in inbox["items"])

        # linking writes the QR instruction with an attachment
        client.post("/dashboard/connections/whatsapp/connect")
        after_connect = client.get("/dashboard/chat/messages?limit=30").json()["items"]
        qr = next(message for message in after_connect if message["text"].startswith("Scan this QR code"))
        assert qr["media"][0]["type"] == "qr"

        # unlinking writes the disconnect alert
        client.delete("/dashboard/connections/whatsapp")
        after_disconnect = client.get("/dashboard/chat/messages?limit=30").json()["items"]
        alert = next(
            message for message in after_disconnect
            if message["text"].startswith("[WHATSAPP_ACCOUNT_DISCONNECTED]")
        )
        assert alert["source"] == "system"


def test_tenant_isolation_between_partners():
    """Tenant B must not read or mutate tenant A's data by guessing ids."""
    phone_b = f"9666{random.randint(100000, 999999)}"

    with TestClient(app) as alice, TestClient(app) as bob:
        _login(alice)
        alice_agents = alice.get("/dashboard/agents").json()["items"]
        alice_rooms = alice.get("/dashboard/rooms").json()["items"]
        assert alice_agents and alice_rooms
        agent_id = alice_agents[0]["id"]
        room_id = alice_rooms[0]["id"]

        _login(bob, phone_b)
        bob_account = bob.get("/dashboard/accounts").json()["items"][0]
        alice_account = alice.get("/dashboard/accounts").json()["items"][0]

        # no agents yet; rooms contain only bob's own inbox, never alice's
        assert bob.get("/dashboard/agents").json()["items"] == []
        bob_rooms = bob.get("/dashboard/rooms").json()["items"]
        assert all(room["account_id"] == bob_account["id"] for room in bob_rooms)
        assert room_id not in {room["id"] for room in bob_rooms}

        # guessed ids are 404, not data
        assert bob.get(f"/dashboard/agents/{agent_id}").status_code == 404
        assert bob.post(f"/dashboard/agents/{agent_id}/toggle-status").status_code == 404
        assert bob.get(f"/dashboard/chat/messages?room_id={room_id}").status_code == 404

        # asking for another tenant's account is 404 even if you are logged in
        assert bob.get(f"/dashboard/agents?account_pid={alice_account['id']}").status_code == 404

        # and the owner still sees their data untouched
        assert alice.get(f"/dashboard/agents/{agent_id}").status_code == 200


def test_onboarding_status():
    with TestClient(app) as client:
        _login(client)
        body = client.get("/dashboard/onboarding").json()
        assert body["whatsapp"]["connected"] is True  # demo tenant is linked
        assert [m["id"] for m in body["whatsapp"]["methods"]] == ["qr", "official", "meta"]
        assert set(body["google"]) >= {"calendar", "gmail", "broker_configured"}
