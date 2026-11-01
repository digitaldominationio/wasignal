"""OpenRouter wiring: catalogue normalisation/cache, provider headers, endpoint."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.llm import LLMError, get_llm
from app.llm import openai_compat
from app.main import app
from app.services import models

SAMPLE = {
    "data": [
        {
            "id": "openai/gpt-4o-mini",
            "name": "OpenAI: GPT-4o mini",
            "context_length": 128000,
            "pricing": {"prompt": "0.00000015", "completion": "0.0000006"},
            "architecture": {"input_modalities": ["text", "image"]},
        },
        {
            "id": "meta-llama/llama-3.3-70b-instruct:free",
            "name": "Meta: Llama 3.3 70B (free)",
            "context_length": 65536,
            "pricing": {"prompt": "0", "completion": "0"},
            "architecture": {"input_modalities": ["text"]},
        },
    ]
}


def test_catalogue_normalises_and_filters():
    models.clear_cache()

    async def fake() -> dict:
        return SAMPLE

    result = asyncio.run(models.list_models(refresh=True, fetcher=fake))
    assert result["total"] == 2
    assert result["count"] == 2

    cheap = next(item for item in result["items"] if item["id"] == "openai/gpt-4o-mini")
    assert cheap["prompt_usd_per_mtok"] == 0.15
    assert cheap["completion_usd_per_mtok"] == 0.6
    assert cheap["multimodal"] is True
    assert cheap["free"] is False

    free = next(item for item in result["items"] if "free" in item["id"])
    assert free["free"] is True
    assert free["multimodal"] is False

    filtered = asyncio.run(models.list_models(q="llama"))
    assert filtered["count"] == 1


def test_catalogue_falls_back_to_cache_on_failure():
    models.clear_cache()

    async def fake() -> dict:
        return SAMPLE

    asyncio.run(models.list_models(refresh=True, fetcher=fake))

    async def boom() -> dict:
        raise RuntimeError("network down")

    result = asyncio.run(models.list_models(refresh=True, fetcher=boom))
    assert result["cached"] is True
    assert result["count"] == 2
    assert result["error"].startswith("refresh_failed")


def test_openrouter_provider_uses_key_and_attribution_headers():
    original = settings.openrouter_key
    try:
        object.__setattr__(settings, "openrouter_key", "sk-or-test")
        llm = get_llm({"llm_provider": "openrouter", "llm_model": "openai/gpt-4o-mini"})
        assert llm.base_url == settings.openrouter_base_url
        assert llm.model == "openai/gpt-4o-mini"
        assert llm.extra_headers["X-Title"] == settings.openrouter_title

        object.__setattr__(settings, "openrouter_key", "")
        with pytest.raises(LLMError):
            get_llm({"llm_provider": "openrouter"})
    finally:
        object.__setattr__(settings, "openrouter_key", original)


def test_openrouter_request_shape(monkeypatch):
    captured: dict = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self) -> dict:
            return {
                "choices": [{"message": {"content": "hello", "tool_calls": [{
                    "id": "call_1",
                    "function": {"name": "search_knowledge", "arguments": "{\"query\":\"fee\"}"},
                }]}}],
                "usage": {"total_tokens": 42},
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

    monkeypatch.setattr(openai_compat.httpx, "AsyncClient", FakeClient)

    llm = openai_compat.OpenAICompatLLM(
        model="openai/gpt-4o-mini",
        base_url="https://openrouter.ai/api/v1",
        api_key="sk-or-test",
        provider="openrouter",
        extra_headers={"HTTP-Referer": "http://localhost:3000", "X-Title": "Wasignal"},
    )
    response = asyncio.run(llm.complete([{"role": "user", "content": "fee?"}], [{"name": "search_knowledge"}]))

    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-or-test"
    assert captured["headers"]["X-Title"] == "Wasignal"
    assert captured["body"]["model"] == "openai/gpt-4o-mini"
    assert captured["body"]["tools"][0]["function"]["name"] == "search_knowledge"
    assert response.text == "hello"
    assert response.tool_calls[0].name == "search_knowledge"
    assert response.tool_calls[0].arguments == {"query": "fee"}
    assert response.tokens == 42


def test_models_endpoint(monkeypatch):
    models.clear_cache()

    async def fake() -> dict:
        return SAMPLE

    monkeypatch.setattr(models, "_fetch_openrouter", fake)
    monkeypatch.setattr(models, "settings", models.settings)

    with TestClient(app) as client:
        otp = client.post("/dashboard/auth/request-otp", json={"phone": "9999000001"}).json()
        client.post("/dashboard/auth/verify-otp",
                    json={"phone": "9999000001", "otp": otp["dev_code"]}).raise_for_status()

        response = client.get("/dashboard/models?refresh=true")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert body["items"][0]["id"]
