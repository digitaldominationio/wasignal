"""Composio v3 broker adapter, scoped by tenant API key.

The tenant supplies their own Composio key (stored encrypted like an LLM key).
Every call is made with that key and `user_id = org_<id>`, so two tenants can
never share accounts.
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

    def __init__(self, api_key: str, base_url: Optional[str] = None) -> None:
        if not api_key:
            raise NotConfigured("composio_key_missing")
        self.api_key = api_key
        self.base = (base_url or settings.composio_base_url).rstrip("/")
        self.headers = {"x-api-key": api_key, "content-type": "application/json"}

    @staticmethod
    def user_id(org_id: int) -> str:
        return f"org_{org_id}"

    # ------------------------------------------------------------- validation

    def validate(self) -> int:
        """Cheap key check: list one toolkit. Raises BrokerError on 401/403."""
        response = httpx.get(
            f"{self.base}/api/v3/toolkits",
            headers=self.headers,
            params={"limit": 1},
            timeout=15,
        )
        if response.status_code in (401, 403):
            raise BrokerError("invalid_composio_key")
        if response.status_code >= 400:
            raise BrokerError(f"composio {response.status_code}: {response.text[:200]}")
        payload = response.json()
        items = payload.get("items") or payload.get("data") or []
        return len(items)

    def create_auth_config(self, toolkit_slug: str) -> str:
        """Create a Composio-managed OAuth config and return its id."""
        response = httpx.post(
            f"{self.base}/api/v3/auth_configs",
            headers=self.headers,
            json={
                "toolkit": {"slug": toolkit_slug},
                "auth_config": {"type": "use_composio_managed_auth", "credentials": {}},
            },
            timeout=20,
        )
        if response.status_code >= 400:
            raise BrokerError(f"auth_config {response.status_code}: {response.text[:200]}")
        data = response.json()
        config_id = (data.get("auth_config") or {}).get("id") or data.get("id")
        if not config_id:
            raise BrokerError("auth_config_missing_id")
        return str(config_id)

    # ------------------------------------------------------------------ calls

    def link(self, org_id: int, auth_config_id: str, callback_url: str) -> dict[str, Any]:
        response = httpx.post(
            f"{self.base}/api/v3/connected_accounts/link",
            headers=self.headers,
            json={
                "auth_config_id": auth_config_id,
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
        accounts = []
        for item in response.json().get("items") or []:
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
        for account in self.list_accounts(org_id):
            if account["service"] == service and account.get("external_id"):
                httpx.delete(
                    f"{self.base}/api/v3/connected_accounts/{account['external_id']}",
                    headers=self.headers,
                    timeout=20,
                )
