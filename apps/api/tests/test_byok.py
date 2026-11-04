"""BYOK: encrypted keys, provider validation, resolution, adapters, metering."""
from __future__ import annotations

import asyncio
import json
import random

import pytest
from fastapi.testclient import TestClient

from app import repo
from app.config import settings
from app.llm import AnthropicLLM, OpenAICompatLLM, get_llm
from app.llm.anthropic import AnthropicLLM as AnthropicAdapter
from app.llm.anthropic import MAX_TOKENS
from app.main import app
from app.services import providers, secrets
from app.services import models as model_service


def _phone(prefix: str) -> str:
    return f"{prefix}{random.randint(100000, 999999)}"


def _tenant(client: TestClient, phone: str, name: str) -> dict:
    client.post("/dashboard/auth/signup", json={"name": name, "phone": phone}).raise_for_status()
    code = client.post("/dashboard/auth/request-otp", json={"phone": phone}).json()["dev_code"]
    client.post("/dashboard/auth/verify-otp", json={"phone": phone, "otp": code}).raise_for_status()
    return client.get("/dashboard/organizations").json()["items"][0]


def test_secrets_roundtrip_and_hint():
    ciphertext, nonce = secrets.encrypt("sk-or-v1-abcdef1234567890")
    assert secrets.decrypt(ciphertext, nonce) == "sk-or-v1-abcdef1234567890"
    assert secrets.hint("sk-or-v1-abcdef1234567890") == "sk-or…7890"
    with pytest.raises(secrets.SecretError):
        secrets.decrypt(ciphertext, secrets.encrypt("other")[1])


@pytest.fixture()
def fake_models(monkeypatch):
    calls: list[str] = []

    def fake(provider: str, api_key: str | None = None, base_url: str | None = None):
        calls.append(provider)
        if not api_key:
            raise PermissionError("missing key")
        return [{"id": "gpt-4o-mini", "name": "GPT-4o mini", "context_length": 128000},
                {"id": "o3-mini", "name": "o3 mini", "context_length": 200000}]

    monkeypatch.setattr(providers, "fetch_models", fake)
    return calls


def test_save_list_mask_and_isolation(fake_models):
    phone_a, phone_b = _phone("9400"), _phone("9401")
    with TestClient(app) as a, TestClient(app) as b:
        org_a = _tenant(a, phone_a, "Key Co A")
        _tenant(b, phone_b, "Key Co B")

        saved = a.put("/dashboard/providers/openai", json={
            "api_key": "sk-test-1234567890", "default_model": "gpt-4o-mini",
        })
        assert saved.status_code == 200, saved.text
        assert saved.json()["valid"] is True
        assert saved.json()["default_provider"] == "openai"

        listing = a.get("/dashboard/providers").json()
        openai = next(item for item in listing["items"] if item["id"] == "openai")
        assert openai["configured"] is True
        assert openai["key_hint"] == "sk-te…7890"
        assert "sk-test-1234567890" not in json.dumps(listing)

        # tenant B sees no key and no default
        listing_b = b.get("/dashboard/providers").json()
        openai_b = next(item for item in listing_b["items"] if item["id"] == "openai")
        assert openai_b["configured"] is False
        assert listing_b["default_provider"] is None

        # stored ciphertext is not the raw key
        raw = repo.get_credential(int(org_a["id"]), "openai")
        assert raw["encrypted_key"]
        assert "sk-test-1234567890" not in raw["encrypted_key"]


def test_member_cannot_write_provider_keys(fake_models):
    phone_owner, phone_member = _phone("9410"), _phone("9411")
    with TestClient(app) as owner, TestClient(app) as member:
        org = _tenant(owner, phone_owner, "Roles Co")
        _tenant(member, phone_member, "Member Own Org")

        partner = repo.partner_by_phone(phone_member)
        repo.add_membership(int(org["id"]), int(partner["pid"]), "member")

        response = member.put(
            f"/dashboard/providers/openai?org_id={org['id']}",
            json={"api_key": "sk-member-should-not"},
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "role_forbidden"


def test_models_use_tenant_key(fake_models):
    with TestClient(app) as client:
        org = _tenant(client, _phone("9420"), "Models Co")
        client.put("/dashboard/providers/openai", json={"api_key": "sk-test-abcdefgh"}).raise_for_status()

        response = client.get("/dashboard/models?provider=openai&refresh=true")
        assert response.status_code == 200
        body = response.json()
        assert body["provider"] == "openai"
        assert {item["id"] for item in body["items"]} == {"gpt-4o-mini", "o3-mini"}
        _ = org


def test_resolution_prefers_tenant_then_deployment(fake_models):
    with TestClient(app) as client:
        org = _tenant(client, _phone("9430"), "Resolve Co")
        client.put("/dashboard/providers/openai", json={"api_key": "sk-tenant-key-1234"}).raise_for_status()
        client.put("/dashboard/providers/anthropic", json={"api_key": "sk-ant-tenant-1234"}).raise_for_status()

        resolved = providers.resolve(int(org["id"]), {"llm_provider": "openai", "llm_model": "gpt-4o-mini"})
        assert resolved["source"] == "organisation"
        assert resolved["api_key"] == "sk-tenant-key-1234"

        llm = get_llm({"llm_provider": "openai", "llm_model": "gpt-4o-mini"}, int(org["id"]))
        assert isinstance(llm, OpenAICompatLLM)
        assert llm.api_key == "sk-tenant-key-1234"
        assert llm.base_url == "https://api.openai.com/v1"

        claude = get_llm({"llm_provider": "anthropic", "llm_model": "claude-sonnet-4-5"}, int(org["id"]))
        assert isinstance(claude, AnthropicLLM)

        # no key anywhere -> explicit error rather than a silent fake
        with pytest.raises(Exception):
            get_llm({"llm_provider": "deepseek"}, int(org["id"]))


def test_org_default_provider_used_when_agent_has_none(fake_models):
    with TestClient(app) as client:
        org = _tenant(client, _phone("9440"), "Default Co")
        client.put("/dashboard/providers/openai", json={
            "api_key": "sk-default-123456", "default_model": "gpt-4o-mini",
        }).raise_for_status()

        llm = get_llm({}, int(org["id"]))
        assert isinstance(llm, OpenAICompatLLM)
        assert llm.model == "gpt-4o-mini"


def test_anthropic_adapter_converts_history_and_tools(monkeypatch):
    captured: dict = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self) -> dict:
            return {
                "content": [
                    {"type": "text", "text": "Booked for 4pm."},
                    {"type": "tool_use", "id": "toolu_1", "name": "calendar_create_event",
                     "input": {"start": "2026-11-04T16:00:00"}},
                ],
                "usage": {"input_tokens": 30, "output_tokens": 12},
            }

    class FakeClient:
        def __init__(self, timeout: float | None = None) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: object) -> bool:
            return False

        async def post(self, url: str, headers: dict | None = None, json: dict | None = None) -> FakeResponse:
            captured.update({"url": url, "headers": headers, "body": json})
            return FakeResponse()

    monkeypatch.setattr("app.llm.anthropic.httpx.AsyncClient", FakeClient)

    llm = AnthropicAdapter(model="claude-sonnet-4-5", api_key="sk-ant-test")
    history = [
        {"role": "system", "content": "You are a calendar assistant."},
        {"role": "user", "content": "book 4pm"},
        {"role": "assistant", "content": "", "tool_calls": [{
            "id": "call_1", "type": "function",
            "function": {"name": "calendar_create_event", "arguments": "{\"start\":\"2026-11-04T16:00:00\"}"},
        }]},
        {"role": "tool", "tool_call_id": "call_1", "name": "calendar_create_event", "content": "{\"ok\":true}"},
    ]
    tools = [{"name": "calendar_create_event", "description": "Book", "parameters": {"type": "object", "properties": {}}}]
    response = asyncio.run(llm.complete(history, tools))

    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "sk-ant-test"
    assert captured["body"]["max_tokens"] == MAX_TOKENS
    assert captured["body"]["system"] == "You are a calendar assistant."
    assert captured["body"]["tools"][0]["name"] == "calendar_create_event"
    # tool_result is folded into a user turn
    assert captured["body"]["messages"][-1]["content"][0]["type"] == "tool_result"
    assert response.text == "Booked for 4pm."
    assert response.tool_calls[0].name == "calendar_create_event"
    assert response.tokens == 42


def test_token_usage_metered_per_org():
    with TestClient(app) as client:
        org = _tenant(client, _phone("9450"), "Tokens Co")
        agent = client.post("/dashboard/agents", json={
            "name": "Metered", "system_prompt": "Answer briefly.",
            "trigger_type": "event", "trigger_scope": "room", "chat_type": "all",
        }).json()
        turn = client.post("/dashboard/chat/messages", json={"text": "hello there"})
        assert turn.status_code == 200, turn.text

        status = client.get("/dashboard/billing/status").json()
        assert status["usage"]["tokens"] > 0
        _ = (org, agent)


def test_deleting_key_clears_defaults(fake_models):
    with TestClient(app) as client:
        _tenant(client, _phone("9460"), "Revoke Co")
        client.put("/dashboard/providers/openai", json={"api_key": "sk-revoke-123456"}).raise_for_status()
        deleted = client.delete("/dashboard/providers/openai").json()
        assert deleted["default_provider"] is None
        listing = client.get("/dashboard/providers").json()
        assert next(i for i in listing["items"] if i["id"] == "openai")["configured"] is False
