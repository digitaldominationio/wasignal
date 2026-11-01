"""Organizations, roles, invitations, seats, plan limits and provider webhooks."""
from __future__ import annotations

import random

from fastapi.testclient import TestClient

from app import repo
from app.main import app
from app.services import billing


def _phone(prefix: str) -> str:
    return f"{prefix}{random.randint(100000, 999999)}"


def _tenant(client: TestClient, phone: str, name: str) -> dict:
    client.post("/dashboard/auth/signup", json={"name": name, "phone": phone}).raise_for_status()
    code = client.post("/dashboard/auth/request-otp", json={"phone": phone}).json()["dev_code"]
    client.post("/dashboard/auth/verify-otp", json={"phone": phone, "otp": code}).raise_for_status()
    return client.get("/dashboard/organizations").json()["items"][0]


def test_invite_accept_and_role_enforcement():
    phone_a, phone_b = _phone("9500"), _phone("9501")
    with TestClient(app) as a, TestClient(app) as b:
        org_a = _tenant(a, phone_a, "Alpha Academy")
        _tenant(b, phone_b, "Beta Studio")

        # trial has one seat: upgrade first so an invite fits
        assert a.post("/dashboard/billing/checkout", json={"plan_id": "growth"}).status_code == 200

        invite = a.post("/dashboard/organization/invitations",
                        json={"phone": phone_b, "role": "member"}).json()
        accepted = b.post(f"/dashboard/invitations/{invite['token']}/accept")
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["role"] == "member"

        # the member now sees both organizations and can read Alpha's data
        org_ids = {org["id"] for org in b.get("/dashboard/organizations").json()["items"]}
        assert {org_a["id"]} <= org_ids
        assert b.get(f"/dashboard/agents?org_id={org_a['id']}").status_code == 200

        # ... but cannot invite (admin-only)
        assert b.post(f"/dashboard/organization/invitations?org_id={org_a['id']}",
                      json={"phone": _phone("9502"), "role": "member"}).status_code == 403

        # demote to viewer: writes are refused, reads still work
        team = a.get(f"/dashboard/team?org_id={org_a['id']}").json()
        member = next(m for m in team["members"] if m["phone"] == phone_b)
        assert a.patch(f"/dashboard/organization/members/{member['pid']}?org_id={org_a['id']}",
                       json={"role": "viewer"}).status_code == 200

        write = b.post(f"/dashboard/agents?org_id={org_a['id']}", json={
            "name": "Blocked", "system_prompt": "x", "trigger_type": "event", "trigger_scope": "room",
        })
        assert write.status_code == 403
        assert write.json()["detail"] == "read_only_role"
        assert b.get(f"/dashboard/agents?org_id={org_a['id']}").status_code == 200


def test_seat_limit_on_trial_plan():
    with TestClient(app) as a:
        _tenant(a, _phone("9510"), "Solo Co")
        response = a.post("/dashboard/organization/invitations",
                          json={"phone": _phone("9511"), "role": "member"})
        assert response.status_code == 402
        assert response.json()["detail"]["code"] == "seat_limit_reached"


def test_wrong_account_cannot_accept_invitation():
    with TestClient(app) as a, TestClient(app) as b:
        _tenant(a, _phone("9520"), "Inviter Co")
        a.post("/dashboard/billing/checkout", json={"plan_id": "growth"})
        invite = a.post("/dashboard/organization/invitations",
                        json={"phone": _phone("9521"), "role": "member"}).json()

        _tenant(b, _phone("9522"), "Stranger Co")
        response = b.post(f"/dashboard/invitations/{invite['token']}/accept")
        assert response.status_code == 403
        assert response.json()["detail"] == "invitation_wrong_account"


def test_number_limit_then_upgrade():
    with TestClient(app) as a:
        _tenant(a, _phone("9530"), "Numbers Co")
        blocked = a.post("/dashboard/accounts", json={"name": "Second number"})
        assert blocked.status_code == 402
        assert blocked.json()["detail"]["code"] == "number_limit_reached"

        assert a.post("/dashboard/billing/checkout", json={"plan_id": "growth"}).status_code == 200
        created = a.post("/dashboard/accounts", json={"name": "Second number"})
        assert created.status_code == 201
        assert created.json()["name"] == "Second number"


def test_message_quota_blocks_admission():
    with TestClient(app) as a:
        org = _tenant(a, _phone("9540"), "Quota Co")
        assert a.post("/dashboard/agents", json={
            "name": "Responder", "system_prompt": "Answer briefly.",
            "trigger_type": "event", "trigger_scope": "room", "chat_type": "all",
        }).status_code == 201
        repo.add_usage(int(org["id"]), "messages", 500)

        response = a.post("/dashboard/chat/messages", json={"text": "hello?"})
        assert response.status_code == 409
        assert response.json()["detail"] == "quota_exceeded"

        status = a.get("/dashboard/billing/status").json()
        assert "messages" in status["exhausted"]
        assert status["usage"]["messages"] >= 500


def test_provider_webhook_updates_subscription():
    with TestClient(app) as a:
        org = _tenant(a, _phone("9550"), "Webhook Co")
        event = {
            "type": "customer.subscription.updated",
            "data": {"object": {
                "id": "sub_test",
                "status": "active",
                "plan_id": "scale",
                "current_period_end": 4_102_444_800,
                "metadata": {"org_id": str(org["id"]), "plan_id": "scale"},
            }},
        }
        assert a.post("/webhook/stripe", json=event).status_code == 200
        status = a.get("/dashboard/billing/status").json()
        assert status["plan"]["id"] == "scale"
        assert status["subscription"]["provider"] == "stripe"


def test_owner_cannot_be_demoted_or_removed():
    with TestClient(app) as a:
        org = _tenant(a, _phone("9560"), "Owner Co")
        team = a.get("/dashboard/team").json()
        owner = next(member for member in team["members"] if member["role"] == "owner")
        assert a.patch(f"/dashboard/organization/members/{owner['pid']}",
                       json={"role": "admin"}).status_code == 409
        assert a.delete(f"/dashboard/organization/members/{owner['pid']}").status_code == 409


def test_entitlements_shape():
    with TestClient(app) as a:
        org = _tenant(a, _phone("9570"), "Ent Co")
        billing.ensure_plans()
        state = billing.entitlements(int(org["id"]))
        assert set(state["limits"]) == {"numbers", "seats", "messages"}
        assert state["plan"]["id"] == "trial"
        assert state["usage"]["seats"] == 1
