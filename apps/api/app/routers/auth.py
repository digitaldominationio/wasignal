"""Auth: WhatsApp OTP + session cookie."""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request, Response

from .. import repo, security
from ..config import settings
from ..schemas import RequestOtpBody, SignupBody, VerifyOtpBody
from ..services import billing, notifications, platform

router = APIRouter(prefix="/dashboard/auth", tags=["auth"])


@router.post("/request-otp")
def request_otp(body: RequestOtpBody) -> dict:
    phone = security.normalise_phone(body.phone)
    partner = repo.partner_by_phone(phone)
    if partner is None:
        raise HTTPException(status_code=404, detail="phone_not_registered")
    payload, code = _deliver_login(phone)
    _inbox_otp(int(partner["pid"]), code)
    return payload


@router.post("/signup")
def signup(body: SignupBody) -> dict:
    phone = security.normalise_phone(body.phone)
    if repo.partner_by_phone(phone):
        raise HTTPException(status_code=409, detail="phone_already_registered")
    if not (platform.is_active() or settings.env == "dev"):
        raise HTTPException(status_code=503, detail="otp_delivery_unavailable")
    pid = repo.create_partner(phone, body.name)
    from ..migrations import _slug

    org = repo.create_org(pid, body.name, _slug(body.name, pid))
    billing.ensure_plans()
    billing.subscribe(int(org["id"]), "trial")
    repo.create_account_full(int(org["id"]), pid, body.name, "", "Asia/Kolkata", "trialing")
    payload, code = _deliver_login(phone)
    _inbox_otp(pid, code)
    payload["pid"] = pid
    return payload


def _deliver_login(phone: str) -> tuple[dict, str]:
    """Issue a code and deliver it from the platform sender when configured.

    Order: platform WhatsApp sender → dev mode (code in response) → bootstrap
    phone with the installer OTP → 503 (no delivery path).
    """
    if platform.is_active():
        code = security.issue_otp(phone)
        result = platform.deliver_otp(phone, code)
        if not result.get("ok"):
            raise HTTPException(status_code=502, detail={
                "code": "otp_delivery_failed",
                "detail": result.get("error"),
            })
        return {"status": "sent"}, code

    if settings.env == "dev":
        code = security.issue_otp(phone, settings.dev_otp or None)
        return {"status": "sent", "dev_code": code}, code

    bootstrap = "".join(ch for ch in settings.bootstrap_phone if ch.isdigit())
    if settings.dev_otp and phone == bootstrap:
        security.issue_otp(phone, settings.dev_otp)
        return {"status": "sent"}, settings.dev_otp

    raise HTTPException(status_code=503, detail="otp_delivery_unavailable")


def _inbox_otp(pid: int, code: str) -> None:
    """Mirror the OTP into the assistant inbox (the real product does this too)."""
    try:
        account = repo.default_account(pid)
    except KeyError:
        return
    notifications.otp_message(account, code)


@router.post("/verify-otp")
def verify_otp(body: VerifyOtpBody, response: Response) -> dict:
    phone = security.normalise_phone(body.phone)
    if not security.verify_otp(phone, body.otp):
        raise HTTPException(status_code=401, detail="invalid_otp")
    partner = repo.partner_by_phone(phone)
    if partner is None:
        raise HTTPException(status_code=404, detail="phone_not_registered")

    token, expires_at = security.create_session(int(partner["pid"]))
    response.set_cookie(
        key=settings.session_cookie,
        value=token,
        max_age=settings.session_ttl_seconds,
        **security.cookie_options(),
    )
    return {
        "authenticated": True,
        "pid": partner["pid"],
        "username": partner["name"],
        "expires_in": expires_at - int(time.time()),
        # Same token as the cookie, for clients that cannot use cookies
        # (cross-site previews, scripts). Treat it exactly like a password.
        "access_token": token,
    }


@router.get("/session")
def session(request: Request) -> dict:
    pid = security.session_partner(request)
    if pid is None:
        raise HTTPException(status_code=401, detail="Could not validate credentials")
    partner = repo.partner(pid)
    return {"authenticated": True, "pid": pid, "username": partner["name"] if partner else None}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    security.destroy_session(request)
    response.delete_cookie(settings.session_cookie, path="/", domain=settings.cookie_domain or None)
    return {"ok": True}
