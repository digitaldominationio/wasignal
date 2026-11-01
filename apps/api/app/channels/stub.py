"""Local channel: no network, no WhatsApp. Writes every send to stdout and
returns a synthetic id, so the whole pipeline is exercisable offline."""
from __future__ import annotations

import time
from typing import Any

from .. import repo

# account_id -> epoch seconds when the fake QR was issued
_LINKS: dict[int, float] = {}

# 1x1 transparent PNG, stands in for a real QR payload
_FAKE_QR = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class StubChannel:
    name = "stub"

    async def send(self, account: dict[str, Any], room: dict[str, Any], text: str,
                   media: list[dict[str, Any]] | None = None) -> str:
        print(f"[stub-channel] -> account={account['id']} room={room['display_name'] or room['id']}: {text}")
        return f"stub-{int(time.time() * 1000)}"

    async def start_link(self, account: dict[str, Any], method: str = "qr") -> dict[str, Any]:
        _LINKS[int(account["id"])] = time.time()
        repo.set_account_number(int(account["id"]), account.get("wa_number") or "+910000000000")
        return {"state": "pending", "method": method, "qr_image_base64": _FAKE_QR}

    async def link_status(self, account: dict[str, Any]) -> dict[str, Any]:
        issued = _LINKS.get(int(account["id"]))
        if issued is None:
            return {"state": "idle"}
        elapsed = time.time() - issued
        if elapsed < 2:
            return {"state": "pending", "qr_image_base64": _FAKE_QR}
        if elapsed < 4:
            return {"state": "connecting"}
        return {"state": "connected"}

    async def disconnect(self, account: dict[str, Any]) -> dict[str, Any]:
        _LINKS.pop(int(account["id"]), None)
        return {"state": "idle", "disconnected": True}
