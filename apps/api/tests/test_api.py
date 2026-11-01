"""HTTP contract: OTP login, agent listing, dashboard chat, health."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def _login(client: TestClient) -> None:
    otp = client.post("/dashboard/auth/request-otp", json={"phone": "9999000001"})
    assert otp.status_code == 200, otp.text
    code = otp.json()["dev_code"]

    verified = client.post("/dashboard/auth/verify-otp", json={"phone": "9999000001", "otp": code})
    assert verified.status_code == 200, verified.text
    assert verified.json()["authenticated"] is True


def test_login_and_agent_listing():
    with TestClient(app) as client:
        assert client.get("/dashboard/agents").status_code == 401
        _login(client)
        agents = client.get("/dashboard/agents")
        assert agents.status_code == 200
        assert agents.json()["items"]
        assert client.get("/dashboard/auth/session").json()["pid"] == 1


def test_login_returns_bearer_token_and_it_authenticates():
    with TestClient(app) as client:
        otp = client.post("/dashboard/auth/request-otp", json={"phone": "9999000001"}).json()
        verified = client.post("/dashboard/auth/verify-otp",
                               json={"phone": "9999000001", "otp": otp["dev_code"]}).json()
        token = verified["access_token"]
        assert token

        # cookies must not be what authenticates this call
        client.cookies.clear()
        with_token = client.get("/dashboard/agents", headers={"authorization": f"Bearer {token}"})
        assert with_token.status_code == 200
        assert with_token.json()["items"]

        assert client.get("/dashboard/agents").status_code == 401


def test_cors_preflight_for_split_deployment():
    with TestClient(app) as client:
        response = client.options(
            "/dashboard/agents",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert response.status_code in (200, 204)
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
        assert response.headers["access-control-allow-credentials"] == "true"


def test_dashboard_chat_runs_the_agent():
    with TestClient(app) as client:
        _login(client)
        response = client.post("/dashboard/chat/messages", json={"text": "What is the JEE crash course fee?"})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["accepted"] is True
        assert payload["delivery"] == "queued"
        assert payload["reply"]


def test_health():
    with TestClient(app) as client:
        assert client.get("/health/live").json() == {"status": "ok"}
        ready = client.get("/health/ready").json()
        assert ready["status"] == "ready"
