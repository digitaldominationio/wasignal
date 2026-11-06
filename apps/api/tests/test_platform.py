"""Platform sender: superadmin connects the number that delivers login OTPs."""
from __future__ import annotations

import json
import random
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import repo
from app.config import settings
from app.main import app
from app.services import platform


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = json.dumps(self._payload)

    def json(self) -> dict:
        return self._payload


@pytest.fixture()
def meta(monkeypatch):
    calls: list[dict[str, Any]] = []

    def fake_get(url: str, **kwargs: Any) -> FakeResponse:
        calls.append({"method": "GET", "url": url, **kwargs})
        return FakeResponse(200, {"display_phone_number": "+15550001111", "verified_name": "Wasignal"})

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        calls.append({"method": "POST", "url": url, **kwargs})
        return FakeResponse(200, {"messages": [{"id": "wamid.test"}]})

    monkeypatch.setattr(platform.httpx, "get", fake_get)
    monkeypatch.setattr(platform.httpx, "post", fake_post)
    return calls


def _phone(prefix: str) -> str:
    return f"{prefix}{random.randint(100000, 999999)}"


def _login_admin(client: TestClient) -> None:
    response = client.post("/dashboard/auth/request-otp", json={"phone": "9999000001"}).json()
    code = response.get("dev_code") or (repo.otp_get("9999000001") or {}).get("code")
    assert code, response
    client.post("/dashboard/auth/verify-otp", json={"phone": "9999000001", "otp": code}).raise_for_status()


def test_superadmin_configures_platform_sender(meta):
    with TestClient(app) as client:
        _login_admin(client)
        saved = client.put("/admin/platform/whatsapp", json={
            "phone_number_id": "712594308615206",
            "access_token": "EAAB-platform-token",
            "template_name": "wasignal_otp",
            "template_language": "en_US",
        })
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["is_active"] is True
        assert body["has_token"] is True

        row = repo.get_platform_settings()
        assert row["token_encrypted"]
        assert "EAAB-platform-token" not in row["token_encrypted"]
        from app.services import secrets
        assert secrets.decrypt(row["token_encrypted"], row["token_nonce"]) == "EAAB-platform-token"

        status = client.get("/admin/platform").json()["settings"]
        assert status["is_active"] is True
        assert status["template_name"] == "wasignal_otp"


def test_otp_is_delivered_from_platform_sender(meta):
    with TestClient(app) as client:
        _login_admin(client)
        client.put("/admin/platform/whatsapp", json={
            "phone_number_id": "712594308615206",
            "access_token": "EAAB-platform-token",
            "template_name": "wasignal_otp",
        }).raise_for_status()

        response = client.post("/dashboard/auth/request-otp", json={"phone": "9999000001"})
        assert response.status_code == 200, response.text
        assert "dev_code" not in response.json()

        sends = [call for call in meta if call["method"] == "POST"]
        assert sends, "no WhatsApp send attempted"
        payload = sends[-1]["json"]
        assert payload["type"] == "template"
        assert payload["template"]["name"] == "wasignal_otp"

        code = repo.otp_get("9999000001")["code"]
        verified = client.post("/dashboard/auth/verify-otp", json={"phone": "9999000001", "otp": code})
        assert verified.status_code == 200


def test_failed_delivery_returns_502(meta, monkeypatch):
    def failing_post(url: str, **kwargs: Any) -> FakeResponse:
        return FakeResponse(400, {"error": {"message": "invalid parameter"}})

    monkeypatch.setattr(platform.httpx, "post", failing_post)
    with TestClient(app) as client:
        _login_admin(client)
        client.put("/admin/platform/whatsapp", json={
            "phone_number_id": "712594308615206", "access_token": "EAAB-platform-token",
        }).raise_for_status()
        response = client.post("/dashboard/auth/request-otp", json={"phone": "9999000001"})
        assert response.status_code == 502
        assert response.json()["detail"]["code"] == "otp_delivery_failed"


def test_without_sender_only_bootstrap_can_log_in(monkeypatch):
    original_env = settings.env
    original_otp = settings.dev_otp
    object.__setattr__(settings, "env", "production")
    object.__setattr__(settings, "dev_otp", "445566")
    platform.disable()
    try:
        with TestClient(app) as client:
            ok = client.post("/dashboard/auth/request-otp", json={"phone": "9999000001"})
            assert ok.status_code == 200
            assert "dev_code" not in ok.json()
            assert client.post("/dashboard/auth/verify-otp",
                               json={"phone": "9999000001", "otp": "445566"}).status_code == 200

            stranger = _phone("9700")
            repo.create_partner(other := stranger, "Stranger")  # no org needed to test delivery
            blocked = client.post("/dashboard/auth/request-otp", json={"phone": other})
            assert blocked.status_code == 503
            assert blocked.json()["detail"] == "otp_delivery_unavailable"
    finally:
        object.__setattr__(settings, "env", original_env)
        object.__setattr__(settings, "dev_otp", original_otp)


def test_platform_sender_is_superadmin_only(meta):
    with TestClient(app) as client:
        phone = _phone("9701")
        client.post("/dashboard/auth/signup", json={"name": "Normal", "phone": phone})
        code = client.post("/dashboard/auth/request-otp", json={"phone": phone}).json()["dev_code"]
        client.post("/dashboard/auth/verify-otp", json={"phone": phone, "otp": code}).raise_for_status()

        assert client.get("/admin/platform").status_code == 403
        assert client.put("/admin/platform/whatsapp", json={
            "phone_number_id": "1", "access_token": "x",
        }).status_code == 403
