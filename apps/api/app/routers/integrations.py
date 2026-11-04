"""Integration broker endpoints: connect Google, list status, audit actions."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse

from ..config import settings
from ..deps import current_org, manager_up
from ..services import integrations

router = APIRouter(prefix="/dashboard/integrations", tags=["integrations"])


@router.get("/callback")
def callback(connected: str | None = None) -> RedirectResponse:
    target = f"{settings.public_web_url}/dashboard/connections?connected={connected or '1'}"
    return RedirectResponse(target, status_code=302)


@router.get("")
def list_integrations(org: dict = Depends(current_org)) -> dict:
    services = integrations.sync(org["org_id"]) if integrations.configured() else integrations.services_for_org(org["org_id"])
    return {
        "configured": integrations.configured(),
        "provider": "composio",
        "services": services,
        "catalogue": integrations.action_catalogue(),
    }


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
    from .. import repo

    return {"items": repo.list_integration_actions(org["org_id"], min(max(limit, 1), 200))}
