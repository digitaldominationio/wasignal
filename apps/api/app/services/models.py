"""Model catalogue.

OpenRouter publishes every model it fronts at GET /models (no auth needed), so
the picker can stay current without shipping a hardcoded list. We cache the
normalised result in-process and degrade to an empty list with an error code
when the network is unavailable.
"""
from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Optional

import httpx

from ..config import settings
from ..storage.cache import cache

Fetcher = Callable[[], Awaitable[dict[str, Any]]]


def _normalise(payload: dict[str, Any]) -> list[dict[str, Any]]:
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


async def _fetch_openrouter() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(f"{settings.openrouter_base_url}/models")
    response.raise_for_status()
    return response.json()


async def list_models(
    *,
    provider: str = "openrouter",
    q: Optional[str] = None,
    limit: int = 200,
    refresh: bool = False,
    fetcher: Optional[Fetcher] = None,
) -> dict[str, Any]:
    now = time.time()
    key = provider.lower()
    cache_key = f"models:{key}"

    cached = cache.get_json(cache_key)
    if refresh or cached is None:
        if key != "openrouter":
            return {"provider": key, "items": [], "count": 0, "error": "unsupported_provider",
                    "cached": False, "fetched_at": None}
        try:
            payload = await (fetcher or _fetch_openrouter)()
            items = _normalise(payload)
            cached = {"items": items, "fetched_at": int(now)}
            cache.set_json(cache_key, cached, settings.model_cache_seconds)
        except Exception as exc:  # network, HTTP, bad JSON
            if cached is not None:
                items = _filter(cached["items"], q, limit)
                return {
                    "provider": key, "items": items, "count": len(items),
                    "cached": True, "fetched_at": cached.get("fetched_at"),
                    "error": f"refresh_failed: {type(exc).__name__}",
                }
            return {"provider": key, "items": [], "count": 0, "cached": False,
                    "fetched_at": None, "error": "openrouter_unavailable"}

    data = cached
    items = _filter(data["items"], q, limit)
    return {
        "provider": key,
        "items": items,
        "count": len(items),
        "total": len(data["items"]),
        "cached": True,
        "fetched_at": data.get("fetched_at"),
    }


def _filter(items: list[dict[str, Any]], q: Optional[str], limit: int) -> list[dict[str, Any]]:
    if q:
        needle = q.lower()
        items = [item for item in items if needle in item["id"].lower() or needle in item["name"].lower()]
    if limit and limit > 0:
        return items[:limit]
    return items


def clear_cache() -> None:
    cache.delete("models:openrouter")


def provider_status() -> dict[str, Any]:
    return {
        "provider": settings.llm_provider,
        "openrouter": {
            "configured": bool(settings.openrouter_key),
            "base_url": settings.openrouter_base_url,
            "default_model": settings.openrouter_model,
        },
    }
