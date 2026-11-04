"""Tenant AI providers: bring your own key, org defaults, validation."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import repo
from ..deps import admin_only, current_org, current_partner
from ..services import providers

router = APIRouter(prefix="/dashboard", tags=["providers"])


class ProviderKeyBody(BaseModel):
    api_key: str = Field(min_length=8, max_length=400)
    base_url: Optional[str] = Field(default=None, max_length=300)
    default_model: Optional[str] = Field(default=None, max_length=200)


class ProviderDefaultsBody(BaseModel):
    provider: str = Field(min_length=2, max_length=40)
    model: Optional[str] = Field(default=None, max_length=200)


def _defaults(org_id: int) -> dict:
    provider, model = providers.organisation_defaults(org_id)
    return {"default_provider": provider, "default_model": model}


@router.get("/providers")
def list_providers(org: dict = Depends(current_org)) -> dict:
    return {
        "items": providers.list_providers(org["org_id"]),
        **_defaults(org["org_id"]),
    }


@router.put("/providers/{provider}")
def set_provider_key(provider: str, body: ProviderKeyBody, org: dict = Depends(admin_only),
                     partner_pid: int = Depends(current_partner)) -> dict:
    try:
        providers.get_provider(provider)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown_provider") from None

    result = providers.save_key(
        org["org_id"], provider, body.api_key.strip(), body.base_url, partner_pid,
    )

    default_provider, _ = providers.organisation_defaults(org["org_id"])
    if body.default_model:
        repo.set_org_defaults(org["org_id"], default_provider or provider, body.default_model)
    elif default_provider is None and result["valid"]:
        repo.set_org_defaults(org["org_id"], provider, None)

    return {**result, **_defaults(org["org_id"])}


@router.delete("/providers/{provider}")
def delete_provider_key(provider: str, org: dict = Depends(admin_only)) -> dict:
    try:
        providers.get_provider(provider)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown_provider") from None
    providers.revoke_key(org["org_id"], provider)
    default_provider, _ = providers.organisation_defaults(org["org_id"])
    if default_provider == provider:
        repo.set_org_defaults(org["org_id"], None, None)
    return {"provider": provider, "revoked": True, **_defaults(org["org_id"])}


@router.post("/providers/{provider}/test")
def test_provider_key(provider: str, org: dict = Depends(admin_only)) -> dict:
    try:
        providers.get_provider(provider)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown_provider") from None

    credential = repo.get_credential(org["org_id"], provider)
    if credential is None:
        raise HTTPException(status_code=409, detail="provider_not_configured")
    api_key = providers.credential_key(org["org_id"], provider)
    if api_key is None:
        raise HTTPException(status_code=409, detail="provider_key_unreadable")

    ok, message, count = providers.validate_key(provider, api_key, credential.get("base_url"))
    repo.update_credential(
        org["org_id"], provider,
        status="active" if ok else "invalid",
        last_validated_at=int(__import__("time").time()),
    )
    return {"provider": provider, "valid": ok, "message": message, "models": count}


@router.put("/providers/defaults")
def set_defaults(body: ProviderDefaultsBody, org: dict = Depends(admin_only)) -> dict:
    try:
        providers.get_provider(body.provider)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown_provider") from None
    repo.set_org_defaults(org["org_id"], body.provider, body.model)
    return _defaults(org["org_id"])
