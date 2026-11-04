"""Provider registry, tenant key custody and model resolution.

Tenants bring their own keys. A key is encrypted at rest (`services/secrets`),
validated once against the provider's model endpoint, and only ever returned as
a hint. Resolution order for a turn:

    agent.llm_provider/model → organization default → deployment default
    key: organization credential → deployment env key → not configured
"""
from __future__ import annotations

from typing import Any, Optional

import httpx

from .. import repo
from ..config import settings
from . import secrets

PROVIDERS: dict[str, dict[str, Any]] = {
    "openrouter": {
        "label": "OpenRouter",
        "description": "One key, every model (OpenAI, Anthropic, Google, DeepSeek…).",
        "docs": "https://openrouter.ai/keys",
        "base_url": "https://openrouter.ai/api/v1",
        "key_prefix": "sk-or-",
        "adapter": "openai",
        "auth": "bearer",
        "models_path": "/models",
        "public_models": True,
        "default_model": "openai/gpt-4o-mini",
    },
    "openai": {
        "label": "OpenAI",
        "description": "Direct OpenAI key — GPT models, your own rate limits.",
        "docs": "https://platform.openai.com/api-keys",
        "base_url": "https://api.openai.com/v1",
        "key_prefix": "sk-",
        "adapter": "openai",
        "auth": "bearer",
        "models_path": "/models",
        "public_models": False,
        "default_model": "gpt-4o-mini",
    },
    "anthropic": {
        "label": "Anthropic",
        "description": "Claude models via the Messages API.",
        "docs": "https://console.anthropic.com/settings/keys",
        "base_url": "https://api.anthropic.com",
        "key_prefix": "sk-ant-",
        "adapter": "anthropic",
        "auth": "x-api-key",
        "models_path": "/v1/models",
        "public_models": False,
        "default_model": "claude-sonnet-4-5",
    },
    "deepseek": {
        "label": "DeepSeek",
        "description": "OpenAI-compatible DeepSeek endpoint.",
        "docs": "https://platform.deepseek.com/api_keys",
        "base_url": "https://api.deepseek.com/v1",
        "key_prefix": "sk-",
        "adapter": "openai",
        "auth": "bearer",
        "models_path": "/models",
        "public_models": False,
        "default_model": "deepseek-chat",
    },
}

ENV_KEYS = {
    "openrouter": lambda: settings.openrouter_key,
    "openai": lambda: settings.llm_api_key,
}


def provider_ids() -> list[str]:
    return list(PROVIDERS)


def get_provider(provider: str) -> dict[str, Any]:
    spec = PROVIDERS.get(provider)
    if spec is None:
        raise KeyError("unknown_provider")
    return spec


def _headers(provider: str, api_key: str) -> dict[str, str]:
    spec = get_provider(provider)
    if spec["auth"] == "x-api-key":
        return {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
    return {"Authorization": f"Bearer {api_key}"}


def _base(provider: str, base_url: Optional[str] = None) -> str:
    return (base_url or get_provider(provider)["base_url"]).rstrip("/")


def organisation_defaults(org_id: int) -> tuple[Optional[str], Optional[str]]:
    try:
        org = repo.get_org(org_id)
    except KeyError:
        return None, None
    return org.get("default_provider"), org.get("default_model")


def list_providers(org_id: int) -> list[dict[str, Any]]:
    """Registry plus this tenant's connection state. Never returns the key."""
    credentials = {row["provider"]: row for row in repo.list_credentials(org_id)}
    default_provider, default_model = organisation_defaults(org_id)
    items = []
    for provider, spec in PROVIDERS.items():
        credential = credentials.get(provider)
        deployment_key = bool(ENV_KEYS.get(provider, lambda: "")())
        items.append({
            "id": provider,
            "label": spec["label"],
            "description": spec["description"],
            "docs": spec["docs"],
            "configured": credential is not None and credential.get("status") == "active",
            "key_hint": credential.get("key_hint") if credential else None,
            "status": credential.get("status") if credential else ("deployment" if deployment_key else "unconfigured"),
            "base_url": credential.get("base_url") if credential else None,
            "default_model": spec["default_model"],
            "using_deployment_key": credential is None and deployment_key,
            "is_default": provider == default_provider,
        })
    return items


def fetch_models(provider: str, api_key: Optional[str] = None,
                 base_url: Optional[str] = None) -> list[dict[str, Any]]:
    spec = get_provider(provider)
    if not api_key and not spec["public_models"]:
        raise PermissionError(f"{provider}_key_missing")
    headers = _headers(provider, api_key) if api_key else {}
    url = f"{_base(provider, base_url)}{spec['models_path']}"
    with httpx.Client(timeout=settings.provider_validation_timeout) as client:
        response = client.get(url, headers=headers)
    if response.status_code >= 400:
        raise ValueError(f"provider returned {response.status_code}")
    payload = response.json()
    raw = payload.get("data") if isinstance(payload, dict) else payload
    models: list[dict[str, Any]] = []
    for item in raw or []:
        identifier = item.get("id") or item.get("name")
        if not identifier:
            continue
        models.append({
            "id": identifier,
            "name": item.get("display_name") or item.get("name") or identifier,
            "context_length": int(item.get("context_length") or 0),
        })
    return models


def validate_key(provider: str, api_key: str, base_url: Optional[str] = None) -> tuple[bool, str, int]:
    try:
        models = fetch_models(provider, api_key, base_url)
        return True, "ok", len(models)
    except PermissionError:
        return False, "key_missing", 0
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"[:200], 0


def save_key(org_id: int, provider: str, api_key: str, base_url: Optional[str] = None,
             created_by: Optional[int] = None) -> dict[str, Any]:
    get_provider(provider)
    ok, message, count = validate_key(provider, api_key, base_url)
    ciphertext, nonce = secrets.encrypt(api_key)
    repo.upsert_credential(
        org_id, provider, ciphertext, nonce, secrets.hint(api_key), base_url, created_by,
    )
    if not ok:
        repo.update_credential(org_id, provider, status="invalid")
    return {"provider": provider, "valid": ok, "message": message, "models": count,
            "key_hint": secrets.hint(api_key), "status": "active" if ok else "invalid"}


def revoke_key(org_id: int, provider: str) -> None:
    repo.delete_credential(org_id, provider)


def credential_key(org_id: int, provider: str) -> Optional[str]:
    row = repo.get_credential(org_id, provider)
    if row is None or row.get("status") != "active":
        return None
    try:
        return secrets.decrypt(row["encrypted_key"], row["nonce"])
    except secrets.SecretError:
        return None


def touch(org_id: int, provider: str) -> None:
    import time

    repo.update_credential(org_id, provider, last_used_at=int(time.time()))


def resolve(org_id: Optional[int], agent: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Everything the LLM layer needs for one turn, including the tenant key."""
    agent = agent or {}
    default_provider, default_model = organisation_defaults(org_id) if org_id else (None, None)
    provider = agent.get("llm_provider") or default_provider or settings.llm_provider or "echo"
    provider = provider.lower()

    if provider in {"echo", "stub", "offline"}:
        return {"provider": "echo", "adapter": "echo", "model": None, "api_key": None,
                "base_url": None, "source": "offline"}

    spec = get_provider(provider)
    model = agent.get("llm_model") or default_model or spec["default_model"]

    api_key = credential_key(org_id, provider) if org_id else None
    source = "organisation"
    if api_key is None:
        api_key = ENV_KEYS.get(provider, lambda: "")()
        source = "deployment"

    return {
        "provider": provider,
        "adapter": spec["adapter"],
        "model": model,
        "api_key": api_key,
        "base_url": _base(provider),
        "source": source if api_key else "unconfigured",
    }
