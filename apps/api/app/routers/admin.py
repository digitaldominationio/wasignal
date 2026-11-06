"""Platform admin: tenant inventory, impersonation, audit."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import repo, security
from ..deps import current_partner, current_superadmin
from ..services import admin


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
