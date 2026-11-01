"""Accounts (numbers) inside the active organization, plus quota/usage."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import repo
from ..deps import current_account, current_org, current_partner, manager_up
from ..schemas import PauseBody
from ..services import billing

router = APIRouter(prefix="/dashboard", tags=["accounts"])


class AccountBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    timezone: str = "Asia/Kolkata"


@router.get("/accounts")
def list_accounts(org: dict = Depends(current_org)) -> dict:
    accounts = repo.list_org_accounts(org["org_id"])
    return {"items": accounts, "org_id": org["org_id"], "role": org["role"]}


@router.post("/accounts", status_code=201)
def create_account(body: AccountBody, org: dict = Depends(manager_up)) -> dict:
    try:
        billing.check(org["org_id"], "numbers")
    except billing.QuotaExceeded as exc:
        raise HTTPException(status_code=402, detail={
            "code": "number_limit_reached", "limit": exc.limit, "used": exc.used,
        }) from None
    account = repo.create_account(org["org_id"], org["org"]["owner_pid"], body.name, body.timezone)
    return account


@router.get("/organizations")
def list_organizations(partner_pid: int = Depends(current_partner)) -> dict:
    items = []
    for item in repo.orgs_for_partner(partner_pid):
        state = billing.entitlements(int(item["id"]))
        items.append({
            "id": item["id"],
            "name": item["name"],
            "slug": item["slug"],
            "role": item["role"],
            "plan": state["plan"]["id"],
            "status": state["subscription"]["status"],
            "numbers": state["usage"]["numbers"],
            "seats": state["usage"]["seats"],
        })
    return {"items": items}


@router.get("/quota")
def quota(account: dict = Depends(current_account), org: dict = Depends(current_org)) -> dict:
    state = billing.entitlements(org["org_id"])
    return {
        "account_id": account["id"],
        "org_id": org["org_id"],
        "plan": state["plan"]["id"],
        "numbers": {"used": state["usage"]["numbers"], "limit": state["limits"]["numbers"]},
        "seats": {"used": state["usage"]["seats"], "limit": state["limits"]["seats"]},
        "messages": {"used": state["usage"]["messages"], "limit": state["limits"]["messages"]},
        "period_end": state["subscription"]["current_period_end"],
        "subscription_status": state["subscription"]["status"],
        "over": state["over"],
    }


@router.get("/settings/human-active-pause")
def get_pause(account: dict = Depends(current_account)) -> dict:
    return {"enabled": repo.human_pause_enabled(int(account["id"]))}


@router.put("/settings/human-active-pause")
def set_pause(body: PauseBody, account: dict = Depends(current_account)) -> dict:
    repo.set_human_pause(int(account["id"]), body.enabled)
    return {"enabled": body.enabled}


@router.get("/insights/activity")
def activity(account: dict = Depends(current_account), days: int = 7) -> dict:
    import time as _time

    since = int(_time.time()) - days * 86_400
    rows = repo.activity_rows(int(account["id"]), since)
    runs = repo.runs_by_status(int(account["id"]))
    return {"by_day": rows, "runs_by_status": {row["status"]: row["n"] for row in runs}}
