"""Outbound delivery.

Two states matter and are tracked separately:
  message.status  accepted -> delivered | failed     (thread truth)
  outbox.status   queued   -> sent | failed          (transport truth)
A crash between send and commit can duplicate; real bridges need an idempotency
key (see docs/BRIDGE.md).
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from .. import repo
from ..channels import get_channel
from ..storage.cache import cache


def enqueue(account_id: int, room_id: int, text: str, *, message_id: Optional[int] = None,
            media: Optional[list[dict[str, Any]]] = None) -> int:
    return repo.enqueue_outbox(account_id, room_id, text, media=media, message_id=message_id)


def _load(outbox_id: int) -> Optional[dict[str, Any]]:
    context = repo.outbox_context(outbox_id)
    return context["outbox"] if context else None


async def deliver(outbox_id: int) -> bool:
    context = repo.outbox_context(outbox_id)
    if context is None:
        return False
    row, account, room = context["outbox"], context["account"], context["room"]
    if row["status"] != "queued":
        return False
    if account is None or room is None:
        repo.mark_outbox(outbox_id, "failed", "account or room missing", row.get("message_id"))
        return False

    channel = get_channel()
    try:
        transport_id = await channel.send(account, room, row["text"], row.get("media") or [])
        repo.mark_outbox(outbox_id, "sent", None, row.get("message_id"))
        _ = transport_id
        return True
    except Exception as exc:
        repo.mark_outbox(outbox_id, "failed", f"{type(exc).__name__}: {exc}"[:300], row.get("message_id"))
        return False


async def drain_once(limit: int = 50) -> int:
    """Process every queued row once. Used by the worker loop and by tests."""
    processed = 0
    for row in repo.queued_outbox(limit):
        if await deliver(int(row["id"])):
            processed += 1
    return processed


class Worker:
    def __init__(self, interval: float = 1.0) -> None:
        self.interval = interval
        self._task: Optional[asyncio.Task[None]] = None
        self._stopping = asyncio.Event()

    async def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                with cache.lock("worker:outbox", ttl_seconds=max(5, int(self.interval * 5))) as owned:
                    if owned:
                        await drain_once()
            except Exception as exc:  # keep the worker alive
                print(f"[worker] drain failed: {exc}")
            await asyncio.sleep(self.interval)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass


_worker = Worker()


def start_worker() -> None:
    _worker.start()


async def stop_worker() -> None:
    await _worker.stop()


def outbox_stats() -> dict[str, Any]:
    return repo.outbox_stats() | {"at": int(time.time())}
