"""Composio v3 broker adapter.

Three calls matter: create a link for a toolkit, list connected accounts for a
tenant, execute a tool for that tenant. Everything is scoped by `user_id`,
which we set to `org_<id>` so tenants can never reach each other's accounts.
"""
from __future__ import annotations

from typing import Any, Optional

import httpx

from ...config import settings


class BrokerError(RuntimeError):
    pass


class NotConfigured(BrokerError):
    pass


class ComposioBroker:
    name = "composio"
    toolkit_slugs = {"google_calendar": "googlecalendar", "gmail": "gmail"}

    def __init__(self) -> None:
        if not settings.composio_api_key:
            raise NotConfigured("composio_api_key_missing")
        self.base = settings.composio_base_url
        self.headers = {"x-api-key": settings.composio_api_key, "content-type": "application/json"}

    @staticmethod
    def user_id(org_id: int) -> str:
        return f"org_{org_id}"

    def auth_config_id(self, service: str) -> str:
        config = {
            "google_calendar": settings.composio_auth_calendar,
            "gmail": settings.composio_auth_gmail,
        }.get(service)
        if not config:
            raise NotConfigured(f"composio_auth_config_missing:{service}")
        return config

    # ------------------------------------------------------------------ calls

    def link(self, org_id: int, service: str, callback_url: str) -> dict[str, Any]:
        response = httpx.post(
            f"{self.base}/api/v3/connected_accounts/link",
            headers=self.headers,
            json={
                "auth_config_id": self.auth_config_id(service),
                "user_id": self.user_id(org_id),
                "callback_url": callback_url,
            },
            timeout=20,
        )
        if response.status_code >= 400:
            raise BrokerError(f"link {response.status_code}: {response.text[:200]}")
        data = response.json()
        return {
            "redirect_url": data.get("redirect_url"),
            "external_id": data.get("connected_account_id"),
            "expires_at": data.get("expires_at"),
        }

    def list_accounts(self, org_id: int) -> list[dict[str, Any]]:
        response = httpx.get(
            f"{self.base}/api/v3/connected_accounts",
            headers=self.headers,
            params={
                "user_ids": self.user_id(org_id),
                "toolkit_slugs": ",".join(self.toolkit_slugs.values()),
                "limit": 50,
            },
            timeout=20,
        )
        if response.status_code >= 400:
            raise BrokerError(f"list {response.status_code}: {response.text[:200]}")
        items = response.json().get("items") or []
        accounts = []
        for item in items:
            toolkit = (item.get("toolkit") or {}).get("slug") or ""
            service = next((name for name, slug in self.toolkit_slugs.items() if slug == toolkit), None)
            if not service:
                continue
            accounts.append({
                "service": service,
                "external_id": item.get("id"),
                "status": (item.get("status") or "").lower() or "active",
                "toolkit": toolkit,
            })
        return accounts

    def execute(self, org_id: int, tool_slug: str, arguments: dict[str, Any],
                connected_account_id: Optional[str] = None) -> dict[str, Any]:
        body: dict[str, Any] = {"user_id": self.user_id(org_id), "arguments": arguments}
        if connected_account_id:
            body["connected_account_id"] = connected_account_id
        response = httpx.post(
            f"{self.base}/api/v3/tools/execute/{tool_slug}",
            headers=self.headers,
            json=body,
            timeout=60,
        )
        if response.status_code >= 400:
            return {"ok": False, "error": f"{response.status_code}: {response.text[:300]}", "data": None}
        payload = response.json()
        return {
            "ok": bool(payload.get("successful")),
            "data": payload.get("data"),
            "error": payload.get("error"),
        }

    def disconnect(self, org_id: int, service: str) -> None:
        accounts = [a for a in self.list_accounts(org_id) if a["service"] == service]
        for account in accounts:
            if account.get("external_id"):
                httpx.delete(
                    f"{self.base}/api/v3/connected_accounts/{account['external_id']}",
                    headers=self.headers,
                    timeout=20,
                )
