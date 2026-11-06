"""Platform administration: tenant inventory and superadmin bootstrap."""
from __future__ import annotations

from typing import Any

from .. import repo
from ..config import settings
from . import billing


def bootstrap_superadmins() -> None:
    for phone in settings.superadmin_phones:
        digits = "".join(ch for ch in phone if ch.isdigit())
        partner = repo.partner_by_phone(digits)
        if partner is not None:
            repo.add_superadmin(int(partner["pid"]))


def tenant_summaries() -> list[dict[str, Any]]:
    items = []
    for org in repo.list_orgs():
        org_id = int(org["id"])
        owner = repo.partner(int(org["owner_pid"])) or {}
        state = billing.entitlements(org_id)
        items.append({
            "id": org_id,
            "name": org["name"],
            "slug": org.get("slug"),
            "owner": {"pid": org["owner_pid"], "name": owner.get("name"), "phone": owner.get("phone")},
            "plan": state["plan"]["id"],
            "status": state["subscription"]["status"],
            "numbers": state["usage"]["numbers"],
            "agents": repo.count_agents_for_org(org_id),
            "members": repo.count_memberships(org_id),
            "messages_tokens": state["usage"]["tokens"],
            "last_activity": repo.last_message_at_for_org(org_id),
            "created_at": org.get("created_at"),
        })
    return sorted(items, key=lambda item: item["id"])


def tenant_detail(org_id: int) -> dict[str, Any]:
    org = repo.get_org(org_id)
    accounts = repo.list_org_accounts(org_id)
    state = billing.entitlements(org_id)
    agents: list[dict[str, Any]] = []
    recent_runs: list[dict[str, Any]] = []
    for account in accounts:
        agents.extend(repo.list_agents(int(account["id"])))
        recent_runs.extend(repo.list_runs(int(account["id"]), limit=5))
    recent_runs.sort(key=lambda run: int(run.get("started_at") or 0), reverse=True)
    return {
        "organization": {"id": org_id, "name": org["name"], "slug": org.get("slug")},
        "billing": {
            "plan": state["plan"],
            "status": state["subscription"]["status"],
            "usage": state["usage"],
            "limits": state["limits"],
        },
        "accounts": accounts,
        "members": repo.list_memberships(org_id),
        "agents": agents,
        "integrations": repo.list_connected_accounts(org_id),
        "recent_runs": recent_runs[:10],
        "audit": [row for row in repo.list_admin_audit(200) if row.get("org_id") == org_id][:20],
    }
