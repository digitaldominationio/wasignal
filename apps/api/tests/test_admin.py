"""Platform admin: tenant inventory, impersonation (read+write), audit."""
from __future__ import annotations

import random

from fastapi.testclient import TestClient

from app.main import app


def _phone(prefix: str) -> str:
    return f"{prefix}{random.randint(100000, 999999)}"


def _signup(client: TestClient, phone: str, name: str) -> dict:
    client.post("/dashboard/auth/signup", json={"name": name, "phone": phone}).raise_for_status()
    code = client.post("/dashboard/auth/request-otp", json={"phone": phone}).json()["dev_code"]
    client.post("/dashboard/auth/verify-otp", json={"phone": phone, "otp": code}).raise_for_status()
    return client.get("/dashboard/organizations").json()["items"][0]


def _login_admin(client: TestClient) -> None:
    code = client.post("/dashboard/auth/request-otp", json={"phone": "9999000001"}).json()["dev_code"]
    client.post("/dashboard/auth/verify-otp", json={"phone": "9999000001", "otp": code}).raise_for_status()


def test_superadmin_lists_tenants_and_non_admin_is_refused():
    with TestClient(app) as admin_client, TestClient(app) as tenant:
        _login_admin(admin_client)
        me = admin_client.get("/dashboard/me").json()
        assert me["is_superadmin"] is True
        assert me["impersonating"] is False

        org = _signup(tenant, _phone("9600"), "Tenant List Co")
        tenants = admin_client.get("/admin/tenants").json()["items"]
        assert any(item["id"] == org["id"] for item in tenants)

        assert tenant.get("/admin/tenants").status_code == 403


def test_impersonation_sees_and_acts_as_the_tenant():
    with TestClient(app) as admin_client, TestClient(app) as tenant:
        _login_admin(admin_client)
        org = _signup(tenant, _phone("9601"), "Impersonation Co")

        created = tenant.post("/dashboard/agents", json={
            "name": "Tenant Agent", "system_prompt": "x",
            "trigger_type": "event", "trigger_scope": "room",
        })
        assert created.status_code == 201

        token = admin_client.post(f"/admin/tenants/{org['id']}/impersonate").json()["access_token"]

        with TestClient(app) as as_tenant:
            as_tenant.headers.update({"authorization": f"Bearer {token}"})
            me = as_tenant.get("/dashboard/me").json()
            assert me["impersonating"] is True
            assert me["org"]["id"] == org["id"]

            agents = as_tenant.get("/dashboard/agents").json()["items"]
            assert [agent["name"] for agent in agents] == ["Tenant Agent"]

            # impersonation allows writes (admin troubleshooting)
            fixed = as_tenant.post("/dashboard/agents", json={
                "name": "Fixed By Admin", "system_prompt": "x",
                "trigger_type": "event", "trigger_scope": "room",
            })
            assert fixed.status_code == 201

            assert as_tenant.post("/admin/impersonation/stop").status_code == 200
            assert as_tenant.get("/dashboard/me").status_code == 401

        audit = admin_client.get("/admin/audit").json()["items"]
        assert any(row["action"] == "impersonate_start" and row["org_id"] == org["id"] for row in audit)
        assert any(row["action"] == "impersonate_stop" for row in audit)
        assert any(row["action"] == "impersonated_write" for row in audit)


def test_impersonation_cannot_be_used_by_a_normal_session():
    with TestClient(app) as tenant:
        _signup(tenant, _phone("9602"), "No Admin Co")
        response = tenant.post("/admin/tenants/1/impersonate")
        assert response.status_code == 403
        assert response.json()["detail"] == "superadmin_required"

        me = tenant.get("/dashboard/me").json()
        assert me["is_superadmin"] is False
