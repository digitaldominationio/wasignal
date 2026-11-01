"""Auth: WhatsApp OTP + session cookie."""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request, Response

from .. import repo, security
from ..config import settings
from ..schemas import RequestOtpBody, SignupBody, VerifyOtpBody
from ..services import billing, notifications

router = APIRouter(prefix="/dashboard/auth", tags=["auth"])


@router.post("/request-otp")
def request_otp(body: RequestOtpBody) -> dict:
    phone = security.normalise_phone(body.phone)
    partner = repo.partner_by_phone(phone)
    if partner is None:
        raise HTTPException(status_code=404, detail="phone_not_registered")
    code = security.issue_otp(phone)
    _inbox_otp(int(partner["pid"]), code)
    payload = {"status": "sent"}
    if settings.env == "dev":
        payload["dev_code"] = code  # never do this outside dev
    return payload


@router.post("/signup")
def signup(body: SignupBody) -> dict:
    phone = security.normalise_phone(body.phone)
    if repo.partner_by_phone(phone):
        raise HTTPException(status_code=409, detail="phone_already_registered")
    pid = repo.create_partner(phone, body.name)
    from ..migrations import _slug

    org = repo.create_org(pid, body.name, _slug(body.name, pid))
    billing.ensure_plans()
    billing.subscribe(int(org["id"]), "trial")
    repo.create_account_full(int(org["id"]), pid, body.name, "", "Asia/Kolkata", "trialing")
    security.issue_otp(phone)
    _inbox_otp(pid, settings.dev_otp)
    payload = {"status": "sent", "pid": pid}
    if settings.env == "dev":
        payload["dev_code"] = settings.dev_otp
    return payload


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
