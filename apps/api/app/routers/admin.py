"""Platform admin: tenant inventory, impersonation, audit."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import repo, security
from ..config import settings
from ..deps import current_partner, current_superadmin
from ..services import admin, platform


router = APIRouter(tags=["admin"])


@router.get("/dashboard/me")
def me(request: Request, partner_pid: int = Depends(current_partner)) -> dict:
    record = security.session_record(request)
    emulated = record.get("emulated_org_id") if record else None
    org = repo.get_org(int(emulated)) if emulated else None
    partner = repo.partner(partner_pid) or {}
    return {
        "pid": partner_pid,
        "name": partner.get("name"),
        "is_superadmin": repo.is_superadmin(partner_pid),
        "impersonating": bool(emulated),
        "org": {"id": org["id"], "name": org["name"]} if org else None,
    }


@router.get("/admin/tenants")
def tenants(_actor: int = Depends(current_superadmin)) -> dict:
    return {"items": admin.tenant_summaries()}


@router.get("/admin/tenants/{org_id}")
def tenant(org_id: int, _actor: int = Depends(current_superadmin)) -> dict:
    try:
        return admin.tenant_detail(org_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="org_not_found") from None


@router.post("/admin/tenants/{org_id}/impersonate")
def impersonate(org_id: int, actor: int = Depends(current_superadmin)) -> dict:
    try:
        org = repo.get_org(org_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="org_not_found") from None

    token, expires_at = security.create_session(actor, emulated_org_id=org_id)
    repo.add_admin_audit(actor, org_id, "impersonate_start", {"org": org["name"]})
    return {
        "access_token": token,
        "expires_in": expires_at - int(__import__("time").time()),
        "org": {"id": org["id"], "name": org["name"]},
    }


@router.post("/admin/impersonation/stop")
def stop_impersonation(request: Request, actor: int = Depends(current_superadmin)) -> dict:
    record = security.session_record(request)
    org_id = record.get("emulated_org_id") if record else None
    if org_id:
        repo.add_admin_audit(actor, int(org_id), "impersonate_stop", {})
    token = security.token_from_request(request)
    if token:
        repo.session_delete(token)
    return {"stopped": True}


@router.get("/admin/audit")
def audit(limit: int = 100, _actor: int = Depends(current_superadmin)) -> dict:
    return {"items": repo.list_admin_audit(min(max(limit, 1), 500))}


class PlatformSenderBody(BaseModel):
    phone_number_id: str = Field(min_length=1, max_length=64)
    access_token: str = Field(min_length=8, max_length=2000)
    display_number: Optional[str] = Field(default=None, max_length=32)
    template_name: Optional[str] = Field(default=None, max_length=120)
    template_language: str = Field(default="en_US", max_length=12)


class TestSendBody(BaseModel):
    to: str = Field(min_length=6, max_length=20)


@router.get("/admin/platform")
def platform_status(_actor: int = Depends(current_superadmin)) -> dict:
    return {"settings": platform.describe(), "bootstrap_phone": settings.bootstrap_phone}


@router.put("/admin/platform/whatsapp")
def set_platform_sender(body: PlatformSenderBody, actor: int = Depends(current_superadmin)) -> dict:
    try:
        result = platform.save_meta(
            body.phone_number_id, body.access_token, body.display_number,
            body.template_name, body.template_language,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:300]) from None
    repo.add_admin_audit(actor, None, "platform_sender_update", {
        "phone_number_id": body.phone_number_id, "template": body.template_name,
    })
    return result


@router.delete("/admin/platform/whatsapp")
def disable_platform_sender(actor: int = Depends(current_superadmin)) -> dict:
    platform.disable()
    repo.add_admin_audit(actor, None, "platform_sender_disabled", {})
    return platform.describe()


@router.post("/admin/platform/test")
def test_platform_sender(body: TestSendBody, actor: int = Depends(current_superadmin)) -> dict:
    result = platform.send_test(body.to)
    repo.add_admin_audit(actor, None, "platform_sender_test", {
        "to": body.to, "ok": bool(result.get("ok")),
    })
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("error"))
    return result
