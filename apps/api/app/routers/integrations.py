"""Integration broker: tenant Composio key, connections, audit."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from .. import repo
from ..config import settings
from ..deps import admin_only, current_org, manager_up
from ..services import integrations

router = APIRouter(prefix="/dashboard/integrations", tags=["integrations"])


class BrokerKeyBody(BaseModel):
    api_key: str = Field(min_length=8, max_length=400)
    base_url: Optional[str] = Field(default=None, max_length=300)


@router.get("/callback")
def callback(connected: str | None = None) -> RedirectResponse:
    target = f"{settings.public_web_url}/dashboard/connections?connected={connected or '1'}"
    return RedirectResponse(target, status_code=302)


@router.get("")
def list_integrations(org: dict = Depends(current_org)) -> dict:
    is_configured = integrations.configured(org["org_id"])
    services = integrations.sync(org["org_id"]) if is_configured else integrations.services_for_org(org["org_id"])
    return {
        "configured": is_configured,
        "broker": integrations.broker_status(org["org_id"]),
        "services": services,
        "catalogue": integrations.action_catalogue(),
    }


@router.put("/broker")
def save_broker(body: BrokerKeyBody, org: dict = Depends(admin_only)) -> dict:
    try:
        result = integrations.save_broker_key(org["org_id"], body.api_key, body.base_url)
    except integrations.NotConfigured as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except integrations.BrokerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:300]) from None
    return {**result, "broker": integrations.broker_status(org["org_id"])}


@router.delete("/broker")
def delete_broker(org: dict = Depends(admin_only)) -> dict:
    integrations.revoke_broker_key(org["org_id"])
    return {"configured": False, "revoked": True}


@router.post("/{service}/connect")
def connect(service: str, org: dict = Depends(manager_up)) -> dict:
    try:
        return integrations.connect(org["org_id"], service)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown_service") from None
    except integrations.NotConfigured as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except integrations.BrokerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:300]) from None


@router.delete("/{service}")
def disconnect(service: str, org: dict = Depends(manager_up)) -> dict:
    try:
        integrations.disconnect(org["org_id"], service)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown_service") from None
    return {"service": service, "connected": False}


@router.get("/actions")
def list_actions(org: dict = Depends(current_org), limit: int = 100) -> dict:
    return {"items": repo.list_integration_actions(org["org_id"], min(max(limit, 1), 200))}
