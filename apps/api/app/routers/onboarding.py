"""First-run setup status: WhatsApp channel + Google connections."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import settings
from ..deps import current_account, current_org
from ..services import integrations

router = APIRouter(prefix="/dashboard", tags=["onboarding"])


@router.get("/onboarding")
def onboarding(account: dict = Depends(current_account), org: dict = Depends(current_org)) -> dict:
    if integrations.configured():
        integrations.sync(org["org_id"])
    google = integrations.connected_services(org["org_id"])
    whatsapp_connected = bool(account.get("wa_number"))
    return {
        "whatsapp": {
            "connected": whatsapp_connected,
            "channel": ("bridge" if whatsapp_connected else None),
            "methods": [
                {"id": "qr", "label": "Scan a QR code", "description": "Use your existing number as a linked device. Two-way, free-form, groups.", "available": True},
                {"id": "official", "label": "WhatsApp Business (official)", "description": "Requires a Meta app and WABA. Outbound works via Composio, inbound needs a Meta webhook.", "available": bool(settings.composio_auth_whatsapp and settings.meta_token)},
                {"id": "meta", "label": "Meta Cloud API", "description": "Bring your own WABA token + phone number id.", "available": bool(settings.meta_token and settings.meta_phone_number_id)},
            ],
        },
        "google": {
            "calendar": google.get("google_calendar", False),
            "gmail": google.get("gmail", False),
            "broker_configured": integrations.configured(),
        },
        "complete": whatsapp_connected,
    }
