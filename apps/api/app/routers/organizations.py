"""Organization, members, roles and invitations."""
from __future__ import annotations

import secrets
import time
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import repo
from ..deps import admin_only, current_org, current_partner
from ..schemas import RequestOtpBody
from ..security import normalise_phone
from ..services import billing

router = APIRouter(prefix="/dashboard", tags=["organization"])

Role = Literal["admin", "manager", "member", "viewer"]
INVITE_TTL = 7 * 86_400


class InviteBody(BaseModel):
    phone: str = Field(min_length=6, max_length=20)
    role: Role = "member"


class RoleBody(BaseModel):
    role: Role


class OrgBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)


def _org_payload(org: dict) -> dict:
    state = billing.entitlements(org["org_id"])
    members = repo.list_memberships(org["org_id"])
    invitations = repo.list_invitations(org["org_id"])
    return {
        "organization": {"id": org["org_id"], "name": org["org"]["name"], "slug": org["org"]["slug"]},
        "role": org["role"],
        "plan": state["plan"]["id"],
        "status": state["subscription"]["status"],
        "members": [
            {
                "pid": member["pid"],
                "name": member["name"] or "Member",
                "phone": member["phone"],
                "role": member["role"],
                "is_owner": member["role"] == "owner",
            }
            for member in members
        ],
        "invitations": [
            {
                "id": invite["id"],
                "phone": invite["phone"],
                "role": invite["role"],
                "token": invite["token"],
                "created_at": invite["created_at"],
                "expires_at": invite["expires_at"],
            }
            for invite in invitations
        ],
        "seats": {
            "used": state["usage"]["seats"],
            "pending": len(invitations),
            "limit": state["limits"]["seats"],
        },
    }


@router.get("/team")
def team(org: dict = Depends(current_org)) -> dict:
    return _org_payload(org)


@router.get("/organization")
def get_organization(org: dict = Depends(current_org)) -> dict:
    return _org_payload(org)


@router.patch("/organization")
def rename_organization(body: OrgBody, org: dict = Depends(admin_only)) -> dict:
    repo.rename_org(org["org_id"], body.name)
    return _org_payload(org)


@router.post("/organization/invitations", status_code=201)
def invite(body: InviteBody, org: dict = Depends(admin_only), partner_pid: int = Depends(current_partner)) -> dict:
    phone = normalise_phone(body.phone)
    state = billing.entitlements(org["org_id"])
    pending = repo.list_invitations(org["org_id"])
    if state["usage"]["seats"] + len(pending) >= state["limits"]["seats"]:
        raise HTTPException(status_code=402, detail={
            "code": "seat_limit_reached",
            "limit": state["limits"]["seats"],
            "used": state["usage"]["seats"],
            "pending": len(pending),
        })

    if any(normalise_phone(member["phone"]) == phone for member in repo.list_memberships(org["org_id"])):
        raise HTTPException(status_code=409, detail="already_a_member")
    if any(normalise_phone(invite_item["phone"]) == phone for invite_item in pending):
        raise HTTPException(status_code=409, detail="invitation_exists")

    invitation = repo.create_invitation(
        org["org_id"], phone, body.role, secrets.token_urlsafe(24), partner_pid,
        int(time.time()) + INVITE_TTL,
    )
    return {**invitation, "accept_path": f"/dashboard/team?invite={invitation['token']}"}


@router.get("/organization/invitations")
def list_invitations(org: dict = Depends(admin_only)) -> dict:
    return {"items": repo.list_invitations(org["org_id"])}


@router.delete("/organization/invitations/{invitation_id}")
def revoke_invitation(invitation_id: int, org: dict = Depends(admin_only)) -> dict:
    repo.delete_invitation(org["org_id"], invitation_id)
    return {"revoked": invitation_id}


@router.get("/invitations")
def my_invitations(partner_pid: int = Depends(current_partner)) -> dict:
    partner = repo.partner(partner_pid)
    phone = normalise_phone(partner["phone"]) if partner else ""
    items = repo.invitations_for_phone(phone) if phone else []
    orgs = {invite["org_id"]: repo.get_org(invite["org_id"]) for invite in items}
    return {
        "items": [
            {
                "token": invite["token"],
                "org_id": invite["org_id"],
                "org_name": orgs[invite["org_id"]]["name"],
                "role": invite["role"],
                "expires_at": invite["expires_at"],
            }
            for invite in items
        ]
    }


@router.post("/invitations/{token}/accept")
def accept_invitation(token: str, partner_pid: int = Depends(current_partner)) -> dict:
    invite = repo.invitation_by_token(token)
    if invite is None or invite["accepted_at"] or invite["declined_at"]:
        raise HTTPException(status_code=404, detail="invitation_not_found")
    if int(invite["expires_at"]) < int(time.time()):
        raise HTTPException(status_code=410, detail="invitation_expired")

    partner = repo.partner(partner_pid)
    if partner is None or normalise_phone(partner["phone"]) != normalise_phone(invite["phone"]):
        raise HTTPException(status_code=403, detail="invitation_wrong_account")

    state = billing.entitlements(int(invite["org_id"]))
    if state["usage"]["seats"] >= state["limits"]["seats"]:
        raise HTTPException(status_code=402, detail={"code": "seat_limit_reached", "limit": state["limits"]["seats"]})

    if repo.membership(int(invite["org_id"]), partner_pid) is not None:
        repo.accept_invitation(int(invite["id"]))
        return {"org_id": invite["org_id"], "already_member": True, "role": invite["role"]}

    repo.add_membership(int(invite["org_id"]), partner_pid, invite["role"])
    repo.accept_invitation(int(invite["id"]))
    return {"org_id": invite["org_id"], "role": invite["role"], "accepted": True}


@router.post("/invitations/{token}/decline")
def decline_invitation(token: str, partner_pid: int = Depends(current_partner)) -> dict:
    invite = repo.invitation_by_token(token)
    if invite is None or invite["accepted_at"] or invite["declined_at"]:
        raise HTTPException(status_code=404, detail="invitation_not_found")
    partner = repo.partner(partner_pid)
    if partner is None or normalise_phone(partner["phone"]) != normalise_phone(invite["phone"]):
        raise HTTPException(status_code=403, detail="invitation_wrong_account")
    repo.decline_invitation(int(invite["id"]))
    return {"declined": True}


@router.patch("/organization/members/{pid}")
def change_role(pid: int, body: RoleBody, org: dict = Depends(admin_only)) -> dict:
    member = repo.membership(org["org_id"], pid)
    if member is None:
        raise HTTPException(status_code=404, detail="member_not_found")
    if member["role"] == "owner":
        raise HTTPException(status_code=409, detail="cannot_change_owner")
    repo.set_membership_role(org["org_id"], pid, body.role)
    return {"pid": pid, "role": body.role}


@router.delete("/organization/members/{pid}")
def remove_member(pid: int, org: dict = Depends(admin_only), partner_pid: int = Depends(current_partner)) -> dict:
    member = repo.membership(org["org_id"], pid)
    if member is None:
        raise HTTPException(status_code=404, detail="member_not_found")
    if member["role"] == "owner":
        raise HTTPException(status_code=409, detail="cannot_remove_owner")
    repo.remove_membership(org["org_id"], pid)
    return {"removed": pid, "self": pid == partner_pid}


@router.post("/organization/leave")
def leave(org: dict = Depends(current_org), partner_pid: int = Depends(current_partner)) -> dict:
    member = repo.membership(org["org_id"], partner_pid)
    if member is None:
        raise HTTPException(status_code=404, detail="member_not_found")
    if member["role"] == "owner":
        raise HTTPException(status_code=409, detail="owner_must_transfer")
    repo.remove_membership(org["org_id"], partner_pid)
    return {"left": org["org_id"]}


@router.post("/organization", status_code=201)
def create_organization(body: OrgBody, partner_pid: int = Depends(current_partner)) -> dict:
    from ..migrations import _slug

    org = repo.create_org(partner_pid, body.name, _slug(body.name, partner_pid))
    billing.subscribe(int(org["id"]), "trial")
    return {"id": org["id"], "name": org["name"], "slug": org["slug"], "role": "owner"}
