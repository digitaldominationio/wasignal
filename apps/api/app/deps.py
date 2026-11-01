"""Shared dependencies: session -> partner -> organization -> account.

Tenancy is enforced here, once. Routers ask for `current_org` / `current_account`
and never trust a client-supplied id without a membership check.
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException, Query, Request

from . import repo, security

ROLE_RANK = {"viewer": 1, "member": 2, "manager": 3, "admin": 4, "owner": 5}


def current_partner(request: Request) -> int:
    pid = security.session_partner(request)
    if pid is None:
        raise HTTPException(status_code=401, detail="Could not validate credentials")
    return pid


def current_org(
    partner_pid: int = Depends(current_partner),
    org_id: Optional[int] = Query(default=None, alias="org_id"),
    x_org_id: Optional[str] = Header(default=None, alias="x-org-id"),
) -> dict:
    """Resolve the active organization and the caller's role in it."""
    target: Optional[int] = org_id
    if target is None and x_org_id:
        try:
            target = int(x_org_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid_org_id") from None

    if target is None:
        org = repo.first_org_for_partner(partner_pid)
        if org is None:
            raise HTTPException(status_code=404, detail="no_organization")
    else:
        org = repo.get_org(target) if _org_exists(target) else None
        if org is None:
            raise HTTPException(status_code=404, detail="org_not_found") from None
        membership = repo.membership(target, partner_pid)
        if membership is None:
            raise HTTPException(status_code=404, detail="org_not_found") from None
        org = {**org, "role": membership["role"]}

    return {"org": org, "role": org["role"], "org_id": int(org["id"])}


def _org_exists(org_id: int) -> bool:
    try:
        repo.get_org(org_id)
        return True
    except KeyError:
        return False


def require_roles(*roles: str):
    """Dependency factory: caller's role must be one of `roles` (owner included)."""
    allowed = set(roles)

    def dependency(org: dict = Depends(current_org)) -> dict:
        if org["role"] not in allowed:
            raise HTTPException(status_code=403, detail="role_forbidden")
        return org

    return dependency


admin_only = require_roles("owner", "admin")
manager_up = require_roles("owner", "admin", "manager")


def require_writer(request: Request, org: dict = Depends(current_org)) -> dict:
    """Any member may read; mutating requests need at least `member`."""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return org
    if ROLE_RANK.get(org["role"], 0) < ROLE_RANK["member"]:
        raise HTTPException(status_code=403, detail="read_only_role")
    return org


def current_account(
    account_pid: Optional[int] = Query(default=None, alias="account_pid"),
    partner_pid: int = Depends(current_partner),
    org: dict = Depends(current_org),
) -> dict:
    try:
        if account_pid is not None:
            account = repo.get_account(partner_pid, int(account_pid))
        else:
            accounts = repo.list_org_accounts(org["org_id"])
            account = accounts[0] if accounts else repo.default_account(partner_pid)
    except KeyError:
        raise HTTPException(status_code=404, detail="account_not_found") from None

    if account.get("org_id") and int(account["org_id"]) != org["org_id"]:
        raise HTTPException(status_code=404, detail="account_not_found")
    return account


def account_id(account: dict = Depends(current_account)) -> int:
    return int(account["id"])


def room_or_404(account: dict, room_id: int) -> dict:
    try:
        return repo.get_room(int(account["id"]), room_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="room_not_found") from None


def agent_or_404(account: dict, agent_id: int) -> dict:
    try:
        return repo.get_agent(int(account["id"]), agent_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="agent_not_found") from None


def webhook_or_404(account: dict, webhook_id: int) -> dict:
    try:
        return repo.get_webhook(int(account["id"]), webhook_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="webhook_not_found") from None
