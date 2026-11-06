"""Platform sender: the WhatsApp number Wasignal uses for login OTPs.

This is deliberately separate from tenant agent numbers. The superadmin connects
it once; every tenant's login codes go out from here.

Today the real transport is Meta Cloud API (WABA). The QR/bridge transport is a
future channel, so `sender_channel` is stored to allow it without a migration.
"""
from __future__ import annotations

from typing import Any, Optional

import httpx

from .. import repo
from ..config import settings
from . import secrets

GRAPH = "https://graph.facebook.com/v21.0"


def get_settings() -> Optional[dict[str, Any]]:
    return repo.get_platform_settings()


def _token(row: dict[str, Any]) -> Optional[str]:
    if not row or not row.get("token_encrypted"):
        return None
    try:
        return secrets.decrypt(row["token_encrypted"], row["token_nonce"])
    except secrets.SecretError:
        return None


def is_active() -> bool:
    row = get_settings()
    return bool(
        row
        and row.get("status") == "active"
        and row.get("sender_channel") == "meta"
        and row.get("phone_number_id")
        and _token(row)
    )


def describe() -> dict[str, Any]:
    row = get_settings()
    if row is None:
        return {"channel": "none", "status": "disabled", "is_active": False}
    return {
        "channel": row.get("sender_channel", "none"),
        "status": row.get("status", "disabled"),
        "is_active": is_active(),
        "phone_number_id": row.get("phone_number_id"),
        "display_number": row.get("display_number"),
        "template_name": row.get("template_name"),
        "template_language": row.get("template_language"),
        "has_token": bool(row.get("token_encrypted")),
    }


def save_meta(phone_number_id: str, access_token: str, display_number: Optional[str] = None,
              template_name: Optional[str] = None, template_language: str = "en_US") -> dict[str, Any]:
    """Validate the token against the phone number, then store it encrypted."""
    response = httpx.get(
        f"{GRAPH}/{phone_number_id}",
        params={"fields": "display_phone_number,verified_name"},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=settings.provider_validation_timeout,
    )
    if response.status_code >= 400:
        raise ValueError(f"meta {response.status_code}: {response.text[:200]}")
    profile = response.json() or {}
    number = display_number or profile.get("display_phone_number")

    ciphertext, nonce = secrets.encrypt(access_token)
    repo.save_platform_sender(
        "meta", phone_number_id, number, ciphertext, nonce,
        template_name or None, template_language or "en_US", "active",
    )
    return describe()


def disable() -> None:
    repo.disable_platform_sender()


def _payload(to: str, text: str, row: dict[str, Any], code: Optional[str]) -> dict[str, Any]:
    template = row.get("template_name")
    if template and code:
        return {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template,
                "language": {"code": row.get("template_language") or "en_US"},
                "components": [{
                    "type": "body",
                    "parameters": [{"type": "text", "text": code}],
                }],
            },
        }
    return {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }


def _send(to: str, text: str, code: Optional[str] = None) -> dict[str, Any]:
    row = get_settings()
    token = _token(row) if row else None
    if not row or row.get("status") != "active" or not token:
        return {"ok": False, "error": "platform_sender_not_configured"}
    phone_number_id = row.get("phone_number_id")
    if not phone_number_id:
        return {"ok": False, "error": "platform_phone_number_id_missing"}

    try:
        response = httpx.post(
            f"{GRAPH}/{phone_number_id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json=_payload(to, text, row, code),
            timeout=20,
        )
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"transport: {exc}"}

    if response.status_code >= 400:
        return {"ok": False, "error": f"meta {response.status_code}: {response.text[:300]}"}
    return {"ok": True}


def deliver_otp(phone: str, code: str) -> dict[str, Any]:
    to = "".join(ch for ch in phone if ch.isdigit())
    return _send(to, f"Your Wasignal code is {code}. It expires in 10 minutes.", code=code)


def send_test(to: str) -> dict[str, Any]:
    digits = "".join(ch for ch in to if ch.isdigit())
    return _send(digits, "This is a test message from Wasignal. Your platform sender works.")
