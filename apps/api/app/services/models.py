"""Model catalogue per provider.

OpenRouter publishes its catalogue publicly; the others need the tenant's key.
Results are normalised to one shape and cached in Redis (per tenant for
private providers), degrading to the cache when a refresh fails.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Optional

import httpx

from ..config import settings
from ..storage.cache import cache
from . import providers

Fetcher = Callable[[], Awaitable[dict[str, Any]]]


def _normalise_openrouter(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw in payload.get("data") or []:
        pricing = raw.get("pricing") or {}
        architecture = raw.get("architecture") or {}
        try:
            prompt = float(pricing.get("prompt") or 0)
            completion = float(pricing.get("completion") or 0)
        except (TypeError, ValueError):
            prompt = completion = 0.0
        modalities = architecture.get("input_modalities") or ["text"]
        items.append({
            "id": raw.get("id", ""),
            "name": raw.get("name") or raw.get("id", ""),
            "context_length": int(raw.get("context_length") or 0),
            "prompt_usd_per_mtok": round(prompt * 1_000_000, 4),
            "completion_usd_per_mtok": round(completion * 1_000_000, 4),
            "free": prompt == 0 and completion == 0,
            "multimodal": any(modality != "text" for modality in modalities),
            "modalities": modalities,
        })
    items.sort(key=lambda item: item["name"].lower())
    return items


def _normalise_simple(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [{
        "id": item["id"],
        "name": item.get("name") or item["id"],
        "context_length": int(item.get("context_length") or 0),
        "prompt_usd_per_mtok": 0,
        "completion_usd_per_mtok": 0,
        "free": False,
        "multimodal": False,
        "modalities": ["text"],
    } for item in items if item.get("id")]
    rows.sort(key=lambda item: item["name"].lower())
    return rows


async def _fetch_openrouter() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(f"{settings.openrouter_base_url}/models")
    response.raise_for_status()
    return response.json()


def _org_key(org_id: Optional[int], provider: str) -> tuple[Optional[str], Optional[str]]:
    key = providers.credential_key(org_id, provider) if org_id else None
    if key is None:
        key = providers.ENV_KEYS.get(provider, lambda: "")()
    credential = None
    if org_id:
        try:
            credential = providers.repo.get_credential(org_id, provider)
        except Exception:
            credential = None
    return key, (credential or {}).get("base_url")


async def list_models(
    *,
    provider: str = "openrouter",
    org_id: Optional[int] = None,
    q: Optional[str] = None,
    limit: int = 200,
    refresh: bool = False,
    fetcher: Optional[Fetcher] = None,
) -> dict[str, Any]:
    key = provider.lower()
    try:
        spec = providers.get_provider(key)
    except KeyError:
        return {"provider": key, "items": [], "count": 0, "error": "unsupported_provider",
                "cached": False, "fetched_at": None}

    private = not spec["public_models"]
    cache_key = f"models:{key}:{org_id if private else 'public'}"
    now = time.time()
    cached = cache.get_json(cache_key)

    if refresh or cached is None:
        try:
            if fetcher is not None:
                items = _normalise_simple((await fetcher()).get("data", [])) if key != "openrouter" else _normalise_openrouter(await fetcher())
            elif key == "openrouter":
                items = _normalise_openrouter(await _fetch_openrouter())
            else:
                api_key, base_url = _org_key(org_id, key)
                if not api_key:
                    return {"provider": key, "items": [], "count": 0, "cached": False,
                            "fetched_at": None, "error": "provider_not_configured"}
                raw = await asyncio.to_thread(providers.fetch_models, key, api_key, base_url)
                items = _normalise_simple(raw)
            cached = {"items": items, "fetched_at": int(now)}
            cache.set_json(cache_key, cached, settings.model_cache_seconds)
        except Exception as exc:
            if cached is not None:
                items = _filter(cached["items"], q, limit)
                return {
                    "provider": key, "items": items, "count": len(items),
                    "cached": True, "fetched_at": cached.get("fetched_at"),
                    "error": f"refresh_failed: {type(exc).__name__}",
                }
            return {"provider": key, "items": [], "count": 0, "cached": False,
                    "fetched_at": None, "error": f"{type(exc).__name__}"}

    items = _filter(cached["items"], q, limit)
    return {
        "provider": key,
        "items": items,
        "count": len(items),
        "total": len(cached["items"]),
        "cached": True,
        "fetched_at": cached.get("fetched_at"),
    }


def _filter(items: list[dict[str, Any]], q: Optional[str], limit: int) -> list[dict[str, Any]]:
    if q:
        needle = q.lower()
        items = [item for item in items if needle in item["id"].lower() or needle in item["name"].lower()]
    if limit and limit > 0:
        return items[:limit]
    return items


def clear_cache(provider: str = "openrouter", org_id: Optional[int] = None) -> None:
    cache.delete(f"models:{provider}:{org_id if org_id else 'public'}")
