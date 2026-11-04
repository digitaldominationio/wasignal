"""Model catalogue for the dashboard picker."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from ..config import settings
from ..deps import current_org
from ..services import models, providers

router = APIRouter(prefix="/dashboard", tags=["models"])


@router.get("/models")
async def list_models(
    provider: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None, max_length=120),
    limit: int = Query(default=200, ge=0, le=1000),
    refresh: bool = Query(default=False),
    org: dict = Depends(current_org),
) -> dict:
    if provider is None:
        provider, _ = providers.organisation_defaults(org["org_id"])
        if provider is None:
            provider = settings.llm_provider if settings.llm_provider not in {"echo", ""} else "openrouter"
    return await models.list_models(
        provider=provider, org_id=org["org_id"], q=q, limit=limit, refresh=refresh,
    )


@router.get("/models/providers")
def providers_status(org: dict = Depends(current_org)) -> dict:
    default_provider, default_model = providers.organisation_defaults(org["org_id"])
    return {
        "provider": default_provider or settings.llm_provider,
        "default_provider": default_provider,
        "default_model": default_model,
        "providers": providers.list_providers(org["org_id"]),
    }
