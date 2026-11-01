"""Plans, subscriptions, entitlements and metered usage.

The tenant boundary is the organization. Limits live on the plan, usage is
recorded per organization, and every enforcement point asks this module — not
the UI, not the agent prompt.
"""
from __future__ import annotations

import calendar
import json
import time
from typing import Any, Optional

from .. import repo

PLAN_SEED: list[dict[str, Any]] = [
    {
        "id": "trial",
        "name": "Trial",
        "price_inr": 0,
        "period": "14 days",
        "tagline": "Kick the tyres",
        "features": ["1 number", "500 messages / month", "Follow-ups", "Knowledge base"],
        "limits": {"numbers": 1, "seats": 1, "messages": 500},
        "lookup_key": "trial",
        "recommended": False,
        "sort_order": 1,
    },
    {
        "id": "growth",
        "name": "Growth",
        "price_inr": 1999,
        "period": "per month",
        "tagline": "For a busy sales desk",
        "features": ["3 numbers", "20,000 messages / month", "5 seats", "Label follow-ups", "Priority support"],
        "limits": {"numbers": 3, "seats": 5, "messages": 20_000},
        "lookup_key": "growth_monthly",
        "recommended": True,
        "sort_order": 2,
    },
    {
        "id": "scale",
        "name": "Scale",
        "price_inr": 4999,
        "period": "per month",
        "tagline": "Multiple teams, one brand",
        "features": ["10 numbers", "100,000 messages / month", "25 seats", "Roles and approvals", "Webhooks", "Dedicated support"],
        "limits": {"numbers": 10, "seats": 25, "messages": 100_000},
        "lookup_key": "scale_monthly",
        "recommended": False,
        "sort_order": 3,
    },
]

PERIOD_DAYS = 30


class QuotaExceeded(Exception):
    def __init__(self, metric: str, limit: int, used: int) -> None:
        super().__init__(f"{metric}_limit_reached")
        self.metric = metric
        self.limit = limit
        self.used = used


class PlanTooSmall(Exception):
    def __init__(self, reason: str, **details: Any) -> None:
        super().__init__(reason)
        self.reason = reason
        self.details = details


def ensure_plans() -> None:
    for plan in PLAN_SEED:
        repo.upsert_plan(plan)


def _plan_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "price_inr": row["price_inr"],
        "period": row["period"],
        "tagline": row["tagline"],
        "features": json.loads(row["features_json"] or "[]"),
        "limits": json.loads(row["limits_json"] or "{}"),
        "lookup_key": row["lookup_key"],
        "recommended": bool(row["recommended"]),
    }


def list_plans() -> list[dict[str, Any]]:
    return [_plan_dict(row) for row in repo.list_plan_rows()]


def get_plan(plan_id: str) -> dict[str, Any]:
    row = repo.plan_row(plan_id)
    if row is None:
        raise KeyError("plan not found")
    return _plan_dict(row)


def _trial_plan() -> dict[str, Any]:
    row = repo.plan_row("trial")
    if row is None:
        ensure_plans()
        row = repo.plan_row("trial")
    return _plan_dict(row)  # type: ignore[arg-type]


def _month_bounds(now: Optional[int] = None) -> tuple[int, int]:
    moment = time.gmtime(now or int(time.time()))
    start = calendar.timegm((moment.tm_year, moment.tm_mon, 1, 0, 0, 0, 0, 0, 0))
    if moment.tm_mon == 12:
        end = calendar.timegm((moment.tm_year + 1, 1, 1, 0, 0, 0, 0, 0, 0))
    else:
        end = calendar.timegm((moment.tm_year, moment.tm_mon + 1, 1, 0, 0, 0, 0, 0, 0))
    return int(start), int(end)


def period_bounds(org_id: int) -> tuple[int, int]:
    subscription = repo.get_subscription(org_id)
    if subscription is not None:
        return int(subscription["current_period_start"]), int(subscription["current_period_end"])
    return _month_bounds()


def entitlements(org_id: int) -> dict[str, Any]:
    subscription = repo.get_subscription(org_id)
    plan = get_plan(subscription["plan_id"]) if subscription else _trial_plan()
    start, end = period_bounds(org_id)

    usage = {
        "messages": repo.usage_since(org_id, "messages", start),
        "runs": repo.usage_since(org_id, "runs", start),
        "numbers": repo.count_org_accounts(org_id),
        "seats": repo.count_memberships(org_id),
    }
    limits = plan["limits"]
    remaining = {metric: max(0, int(limits.get(metric, 0)) - usage.get(metric, 0)) for metric in limits}
    over = [metric for metric in limits if usage.get(metric, 0) > int(limits.get(metric, 0))]
    # consumable metrics are "exhausted" at the limit; capacity metrics are not
    exhausted = [
        metric for metric in ("messages", "runs")
        if metric in limits and usage.get(metric, 0) >= int(limits[metric])
    ]

    return {
        "org_id": org_id,
        "plan": plan,
        "subscription": {
            "status": subscription["status"] if subscription else "trialing",
            "provider": subscription["provider"] if subscription else "manual",
            "current_period_start": start,
            "current_period_end": end,
            "cancel_at_period_end": bool(subscription["cancel_at_period_end"]) if subscription else False,
        },
        "limits": limits,
        "usage": usage,
        "remaining": remaining,
        "over": over,
        "exhausted": exhausted,
    }


def record(org_id: int, metric: str, quantity: int = 1, ref: str | None = None) -> None:
    repo.add_usage(org_id, metric, quantity, ref)


def check(org_id: int, metric: str, quantity: int = 1) -> None:
    """Raise QuotaExceeded when the plan has no room for one more unit."""
    state = entitlements(org_id)
    limit = int(state["limits"].get(metric, 0))
    used = int(state["usage"].get(metric, 0))
    if used + quantity > limit:
        raise QuotaExceeded(metric, limit, used)


def subscribe(org_id: int, plan_id: str, *, provider: str = "manual", provider_ref: str | None = None) -> dict[str, Any]:
    plan = get_plan(plan_id)
    numbers = repo.count_org_accounts(org_id)
    seats = repo.count_memberships(org_id)
    if numbers > plan["limits"]["numbers"]:
        raise PlanTooSmall("plan_too_small", numbers=numbers, max_numbers=plan["limits"]["numbers"])
    if seats > plan["limits"]["seats"]:
        raise PlanTooSmall("plan_too_small", members=seats, max_seats=plan["limits"]["seats"])

    now = int(time.time())
    repo.upsert_subscription(
        org_id,
        plan_id,
        "active" if plan_id != "trial" else "trialing",
        now,
        now + PERIOD_DAYS * 86_400,
        provider=provider,
        provider_ref=provider_ref,
    )
    record(org_id, "subscription_changes", 1, plan_id)
    return entitlements(org_id)


def cancel(org_id: int) -> dict[str, Any]:
    subscription = repo.get_subscription(org_id)
    if subscription is None:
        raise KeyError("no subscription")
    repo.upsert_subscription(
        org_id,
        subscription["plan_id"],
        subscription["status"],
        int(subscription["current_period_start"]),
        int(subscription["current_period_end"]),
        provider=subscription["provider"],
        provider_ref=subscription["provider_ref"],
        cancel_at_period_end=True,
    )
    return entitlements(org_id)


def apply_provider_event(org_id: int, plan_id: str, status: str, period_end: Optional[int] = None,
                         provider: str = "stripe", provider_ref: Optional[str] = None) -> dict[str, Any]:
    now = int(time.time())
    repo.upsert_subscription(
        org_id, plan_id, status, now, int(period_end or now + PERIOD_DAYS * 86_400),
        provider=provider, provider_ref=provider_ref,
    )
    return entitlements(org_id)


def usage_summary(org_id: int) -> dict[str, Any]:
    start, end = period_bounds(org_id)
    return {"period_start": start, "period_end": end, "usage": entitlements(org_id)["usage"]}


def org_for_account(account_id: int) -> Optional[int]:
    row = repo.account_by_id(account_id)
    return int(row["org_id"]) if row and row.get("org_id") else None
