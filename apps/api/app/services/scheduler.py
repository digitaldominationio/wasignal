"""Time-driven work: follow-ups, recurring jobs, one-shot tasks.

A tick is a pure function of (database, clock), so tests call `tick(now=...)`
instead of sleeping. Keep it that way: wall-clock coupling is what makes
scheduling bugs unreproducible.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from .. import repo
from ..agent.capabilities import can
from ..agent.runtime import run_agent
from ..storage.cache import cache
from . import billing, outbound, rrule


def _deliver(account_id: int, room_id: int, text: str, source: str,
             media: Optional[list[dict[str, Any]]] = None) -> Optional[int]:
    account = repo.account_by_id(account_id)
    org_id = int(account["org_id"]) if account and account.get("org_id") else None
    if org_id:
        try:
            billing.check(org_id, "messages")
        except billing.QuotaExceeded:
            print(f"[scheduler] quota exhausted for org {org_id}; skipping {source} send")
            return None

    message = repo.add_message(
        account_id, room_id, "out", text,
        media=media or [], source=source, status="accepted",
    )
    outbound.enqueue(account_id, room_id, text, message_id=message["id"], media=media or [])
    if org_id:
        billing.record(org_id, "messages", 1, f"{source}:{room_id}")
    return message["id"]


def _in_window(window: dict[str, Any] | None, now_ts: int) -> bool:
    if not window:
        return True
    timezone = window.get("timezone") or "Asia/Kolkata"
    try:
        local = datetime.fromtimestamp(now_ts, ZoneInfo(timezone))
    except Exception:
        return True
    days = window.get("days")
    if days and local.weekday() not in days:
        return False
    start, end = window.get("start"), window.get("end")
    if start and end:
        hhmm = local.strftime("%H:%M")
        return start <= hhmm <= end
    return True


async def _run_followups(now_ts: int) -> int:
    sent = 0
    for row in repo.enabled_followup_rules():
        try:
            agent = repo.get_agent(int(row["account_id"]), int(row["ref_id"]))
        except KeyError:
            continue
        if agent["status"] != "active" or not can(agent, "send"):
            continue
        account = None
        for room in repo.list_rooms(int(row["account_id"])):
            if room["is_excluded"]:
                continue
            if agent.get("room_id") and int(agent["room_id"]) != int(room["id"]):
                continue
            if int(room["id"]) in [int(x) for x in agent.get("excluded_room_ids") or []]:
                continue
            chat_type = agent.get("chat_type") or "all"
            if chat_type != "all" and chat_type != room["kind"]:
                continue
            lane = repo.get_lane(agent["id"], room["id"])
            if lane["handed_over"]:
                continue
            last_out = repo.last_message_at(room["id"], "out")
            last_in = repo.last_message_at(room["id"], "in")
            if not last_out or last_in >= last_out:
                continue  # nothing sent yet, or the lead replied
            for index, rule in enumerate(row["rules"]):
                key = str(rule.get("id") or f"r{index + 1}")
                if repo.followup_already_sent(int(row["id"]), int(room["id"]), key):
                    continue
                due_at = last_out + int(rule["delay_seconds"])
                if now_ts < due_at:
                    continue
                if not _in_window(row.get("window"), now_ts):
                    continue
                if account is None:
                    account = repo.account_by_id(int(row["account_id"]))
                if account is None:
                    break

                if rule.get("message_mode") == "verbatim":
                    text = str(rule.get("message") or "")
                else:
                    history = repo.history(room["id"], 20)
                    outcome = await run_agent(
                        agent, account, room,
                        text=f"[follow-up after silence] {rule.get('message', 'Nudge the lead about their earlier question.')}",
                        history=history, sender_name="system", trigger="schedule",
                    )
                    text = outcome.reply.strip()

                if not text:
                    continue
                if _deliver(int(account["id"]), int(room["id"]), text, "followup") is None:
                    continue
                repo.record_followup(int(row["id"]), int(room["id"]), key, due_at, "sent")
                sent += 1
    return sent


def _context_room(account_id: int, context: dict[str, Any]) -> Optional[dict[str, Any]]:
    if context.get("room_id"):
        try:
            return repo.get_room(account_id, int(context["room_id"]))
        except KeyError:
            return None
    rooms = repo.list_rooms(account_id)
    for room in rooms:
        if room["kind"] == "dm":
            return room
    return rooms[0] if rooms else None


async def _run_jobs(now_ts: int) -> int:
    fired = 0
    for job in repo.due_jobs(now_ts):
        account_id = int(job["account_id"])
        context = job.get("context") or {}
        room = _context_room(account_id, context)
        if room is not None and context.get("message"):
            if _deliver(account_id, room["id"], str(context["message"]), "job", context.get("media") or []) is not None:
                fired += 1
        next_at = None
        if job.get("rrule"):
            next_at = rrule.next_occurrence(job["rrule"], job["dtstart_local"], now_ts, "Asia/Kolkata")
        repo.update_job(int(job["id"]), last_fired_at=now_ts, next_run_at=next_at,
                        enabled=1 if next_at else 0)
    return fired


async def _run_tasks(now_ts: int) -> int:
    done = 0
    for task in repo.due_tasks(now_ts):
        account_id = int(task["account_id"])
        context = task.get("context") or {}
        room = _context_room(account_id, context)
        if room is not None and context.get("message"):
            if _deliver(account_id, room["id"], str(context["message"]), "task", context.get("media") or []) is not None:
                done += 1
        repo.set_task_status(int(task["id"]), "done")
    return done


async def tick(now_ts: Optional[int] = None) -> dict[str, int]:
    moment = int(now_ts if now_ts is not None else time.time())
    return {
        "followups": await _run_followups(moment),
        "jobs": await _run_jobs(moment),
        "tasks": await _run_tasks(moment),
    }


class Ticker:
    def __init__(self, interval: float = 15.0) -> None:
        self.interval = interval
        self._task: Optional[asyncio.Task[None]] = None
        self._stopping = asyncio.Event()

    async def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                with cache.lock("scheduler:tick", ttl_seconds=max(10, int(self.interval * 2))) as owned:
                    result = await tick() if owned else {}
                if any(result.values()):
                    print(f"[scheduler] {result}")
            except Exception as exc:
                print(f"[scheduler] tick failed: {exc}")
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


_ticker: Optional[Ticker] = None


def start_ticker(interval: float) -> None:
    global _ticker
    if _ticker is None:
        _ticker = Ticker(interval)
        _ticker.start()


async def stop_ticker() -> None:
    global _ticker
    if _ticker is not None:
        await _ticker.stop()
        _ticker = None
