"""Model catalogue and provider status for the dashboard picker."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..deps import current_account
from ..services import models

router = APIRouter(prefix="/dashboard", tags=["models"])


@router.get("/models")
async def list_models(
    provider: str = Query(default="openrouter"),
    q: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=200, ge=0, le=1000),
    refresh: bool = Query(default=False),
    _account: dict = Depends(current_account),
) -> dict:
    return await models.list_models(provider=provider, q=q, limit=limit, refresh=refresh)


@router.get("/models/providers")
def providers(_account: dict = Depends(current_account)) -> dict:
    return models.provider_status()
