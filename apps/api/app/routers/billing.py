"""Plans, subscriptions, usage and provider webhooks."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import repo
from ..deps import admin_only, current_org
from ..services import billing

router = APIRouter(prefix="/dashboard/billing", tags=["billing"])


class CheckoutBody(BaseModel):
    plan_id: Optional[str] = None
    lookup_key: Optional[str] = None


@router.get("/plans")
def plans() -> dict:
    return {"items": billing.list_plans()}


@router.get("/status")
def status(org: dict = Depends(current_org)) -> dict:
    state = billing.entitlements(org["org_id"])
    return {
        "org_id": org["org_id"],
        "organization": org["org"]["name"],
        "role": org["role"],
        "plan": state["plan"],
        "subscription": state["subscription"],
        "limits": state["limits"],
        "usage": state["usage"],
        "remaining": state["remaining"],
        "over": state["over"],
        "exhausted": state["exhausted"],
    }


@router.post("/checkout")
def checkout(body: CheckoutBody, org: dict = Depends(admin_only)) -> dict:
    """Mock checkout: activates the plan immediately.

    In production this creates a Stripe/Dodo session and returns its URL; the
    subscription only changes when the provider webhook arrives.
    """
    plan_id = body.plan_id
    if plan_id is None and body.lookup_key:
        plan_id = next(
            (plan["id"] for plan in billing.list_plans() if plan["lookup_key"] == body.lookup_key),
            None,
        )
    if not plan_id:
        raise HTTPException(status_code=422, detail="plan_id_required")

    try:
        state = billing.subscribe(org["org_id"], plan_id, provider="manual")
    except KeyError:
        raise HTTPException(status_code=404, detail="plan_not_found") from None
    except billing.PlanTooSmall as exc:
        raise HTTPException(status_code=409, detail={"code": exc.reason, **exc.details}) from None
    return {"status": "active", "mock_provider": True, **state}


@router.post("/cancel")
def cancel(org: dict = Depends(admin_only)) -> dict:
    try:
        return billing.cancel(org["org_id"])
    except KeyError:
        raise HTTPException(status_code=409, detail="no_subscription") from None


@router.post("/portal")
def portal(org: dict = Depends(admin_only)) -> dict:
    raise HTTPException(status_code=501, detail="billing_portal_not_configured")


# ------------------------------------------------------------------- webhooks

webhooks = APIRouter(prefix="/webhook", tags=["billing"])


def _handle_event(provider: str, event: dict[str, Any]) -> dict[str, Any]:
    """Minimal provider webhook handling.

    Expects `{type, data: {object: {metadata: {org_id}, plan_id, status,
    current_period_end}}}`. Real providers differ; adapt per SDK.
    """
    obj = (event.get("data") or {}).get("object") or {}
    metadata = obj.get("metadata") or {}
    org_id = metadata.get("org_id") or obj.get("org_id")
    if org_id is None:
        return {"ignored": True, "reason": "missing_org_id"}

    event_type = str(event.get("type") or "")
    if "canceled" in event_type or "cancelled" in event_type:
        try:
            return billing.cancel(int(org_id))
        except KeyError:
            return {"ignored": True, "reason": "unknown_org"}

    plan_id = metadata.get("plan_id") or obj.get("plan_id")
    if not plan_id:
        return {"ignored": True, "reason": "missing_plan_id"}

    status = str(obj.get("status") or "active")
    period_end = obj.get("current_period_end")
    return billing.apply_provider_event(
        int(org_id), str(plan_id), status,
        int(period_end) if period_end else None,
        provider=provider,
        provider_ref=str(obj.get("id") or "") or None,
    )


@webhooks.post("/stripe")
async def stripe_webhook(request: Request) -> dict:
    event = await request.json()
    return _handle_event("stripe", event)


@webhooks.post("/dodo-payments")
async def dodo_webhook(request: Request) -> dict:
    event = await request.json()
    return _handle_event("dodo", event)
