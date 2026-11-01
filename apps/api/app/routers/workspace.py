"""Workspace surfaces: overview and connections."""
from __future__ import annotations

from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException

from .. import repo
from ..deps import current_account, current_org
from ..services import notifications

router = APIRouter(prefix="/dashboard", tags=["workspace"])

INTEGRATIONS: list[dict[str, Any]] = [
    {
        "group": "Google",
        "hint": "Sign in with Google once to enable any of these.",
        "items": [
            {"id": "gmail", "label": "Gmail", "description": "Read and reply to customer email"},
            {"id": "google_calendar", "label": "Google Calendar", "description": "Book and reschedule calls"},
            {"id": "google_sheets", "label": "Google Sheets", "description": "Log leads and orders to a sheet"},
            {"id": "google_drive", "label": "Google Drive", "description": "Send catalogues and price lists"},
        ],
    },
    {
        "group": "Other",
        "hint": "Third-party integrations.",
        "items": [
            {"id": "notion", "label": "Notion", "description": "Keep the knowledge base in Notion"},
            {"id": "slack", "label": "Slack", "description": "Notify the team when a lead goes hot"},
            {"id": "hubspot", "label": "HubSpot", "description": "Sync contacts and deals"},
        ],
    },
]


@router.get("/overview")
def overview(account: dict = Depends(current_account), org: dict = Depends(current_org)) -> dict:
    account_id = int(account["id"])
    timezone = account.get("timezone") or "Asia/Kolkata"
    try:
        tz = ZoneInfo(timezone)
    except Exception:
        tz = ZoneInfo("UTC")
    start_today = int(datetime.combine(datetime.now(tz).date(), time.min, tz).timestamp())

    agents = repo.list_agents(account_id)
    rooms = repo.list_rooms(account_id)
    messages_today = repo.messages_since(account_id, start_today)
    runs_today = repo.runs_since(account_id, start_today)
    followups_sent = repo.followup_sent_count(account_id)
    queued = repo.outbox_queued_count(account_id)

    attention: list[dict[str, Any]] = []
    if not account.get("wa_number"):
        attention.append({
            "id": "whatsapp",
            "title": "WhatsApp isn't connected",
            "detail": "Your automations and scheduled messages won't run until you link your account.",
            "href": "/dashboard/connections",
            "cta": "Connect now",
        })
    if not any(agent["status"] == "active" for agent in agents):
        attention.append({
            "id": "agents",
            "title": "No active automation",
            "detail": "Create one to answer enquiries and follow up on quiet leads.",
            "href": "/dashboard/automations",
            "cta": "Create automation",
        })
    if not repo.list_sources(account_id):
        attention.append({
            "id": "knowledge",
            "title": "No knowledge yet",
            "detail": "Add your price list or catalogue so the agent can answer without guessing.",
            "href": "/dashboard/knowledge",
            "cta": "Add knowledge",
        })

    return {
        "org": {"id": org["org_id"], "name": org["org"]["name"], "role": org["role"]},
        "stats": {
            "active_agents": sum(1 for agent in agents if agent["status"] == "active"),
            "agents": len(agents),
            "rooms": len(rooms),
            "messages_today": messages_today,
            "runs_today": runs_today,
            "followups_sent": followups_sent,
            "queued": queued,
        },
        "attention": attention,
        "recent_runs": repo.list_runs(account_id, limit=6),
        "rooms": rooms[:5],
    }


def _whatsapp_state(account: dict) -> dict[str, Any]:
    partner = repo.partner(int(account["partner_pid"]))
    connected = bool(account.get("wa_number")) and bool(partner and partner.get("wa_linked"))
    return {
        "id": "whatsapp",
        "label": "WhatsApp",
        "description": "Required — automations and scheduled messages won't work without this.",
        "connected": connected,
        "detail": account.get("wa_number") if connected else "Not connected yet",
        "required": True,
    }


@router.get("/connections")
async def connections(account: dict = Depends(current_account)) -> dict:
    groups = []
    for group in INTEGRATIONS:
        groups.append({
            "group": group["group"],
            "hint": group["hint"],
            "items": [
                {
                    "id": item["id"],
                    "label": item["label"],
                    "description": item["description"],
                    "connected": False,
                    "detail": "Not connected yet",
                }
                for item in group["items"]
            ],
        })
    return {"whatsapp": _whatsapp_state(account), "groups": groups}


@router.post("/connections/{service}/connect")
async def connect(service: str, account: dict = Depends(current_account)) -> dict:
    if service == "whatsapp":
        from ..channels import get_channel

        result = await get_channel().start_link(account, "qr")
        notifications.whatsapp_qr_message(account)
        return {"service": service, **result}
    raise HTTPException(status_code=501, detail="oauth_not_configured")


@router.delete("/connections/{service}")
async def disconnect(service: str, account: dict = Depends(current_account)) -> dict:
    if service == "whatsapp":
        from ..channels import get_channel

        await get_channel().disconnect(account)
        repo.set_account_number(int(account["id"]), "")
        repo.set_wa_linked(int(account["partner_pid"]), False)
        notifications.whatsapp_disconnected_message(account)
        return {"service": service, "connected": False}
    raise HTTPException(status_code=501, detail="oauth_not_configured")
