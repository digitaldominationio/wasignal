"""Time-driven work: follow-up rules, jobs, tasks, send windows, RRULE."""
from __future__ import annotations

import asyncio
import time

import pytest

from app import repo
from app.services import rrule, scheduler


@pytest.fixture(autouse=True)
def _quiet_schedule():
    """Other tests' rules must not fire during this test's tick."""
    repo.clear_pending_work()
    yield


def test_followup_fires_once_and_respects_scope(fresh_account):
    account = fresh_account
    room = repo.ensure_room(int(account["id"]), "911111130001@s.whatsapp.net", "dm", "Quiet lead")
    agent = repo.create_agent(int(account["id"]), {
        "name": "Follow-up agent",
        "system_prompt": "Nudge quiet leads.",
        "trigger_type": "scheduled",
        "room_id": room["id"],
        "capabilities": ["read", "send"],
    })
    repo.put_followup_rules(int(account["id"]), agent["id"], {
        "enabled": True,
        "rules": [{"id": "r1", "message": "Just checking in about your question.",
                   "message_mode": "verbatim", "delay_seconds": 60}],
        "send_window": {"timezone": "Asia/Kolkata", "days": [0, 1, 2, 3, 4, 5, 6],
                        "start": "00:00", "end": "23:59"},
    })

    now = int(time.time())
    repo.add_message(int(account["id"]), int(room["id"]), "out", "Hi, any questions?", ts=now)

    assert asyncio.run(scheduler.tick(now + 61))["followups"] == 1
    assert any(row["text"] == "Just checking in about your question." for row in repo.queued_outbox())

    rule_row = repo.enabled_followup_rules()[0]
    assert repo.followup_already_sent(int(rule_row["id"]), int(room["id"]), "r1")

    assert asyncio.run(scheduler.tick(now + 120))["followups"] == 0


def test_followup_skips_when_lead_replied(fresh_account):
    account = fresh_account
    room = repo.ensure_room(int(account["id"]), "911111130002@s.whatsapp.net", "dm", "Replied lead")
    agent = repo.create_agent(int(account["id"]), {
        "name": "Follow-up agent",
        "system_prompt": "x",
        "trigger_type": "scheduled",
        "room_id": room["id"],
    })
    repo.put_followup_rules(int(account["id"]), agent["id"], {
        "enabled": True,
        "rules": [{"id": "r1", "message": "nudge", "message_mode": "verbatim", "delay_seconds": 60}],
    })
    now = int(time.time())
    repo.add_message(int(account["id"]), int(room["id"]), "out", "Any questions?", ts=now - 300)
    repo.add_message(int(account["id"]), int(room["id"]), "in", "Yes, one thing", ts=now - 100)

    assert asyncio.run(scheduler.tick(now))["followups"] == 0


def test_followup_respects_send_window(fresh_account):
    account = fresh_account
    room = repo.ensure_room(int(account["id"]), "911111130003@s.whatsapp.net", "dm", "Window lead")
    agent = repo.create_agent(int(account["id"]), {
        "name": "Window agent", "system_prompt": "x", "trigger_type": "scheduled", "room_id": room["id"],
    })
    repo.put_followup_rules(int(account["id"]), agent["id"], {
        "enabled": True,
        "rules": [{"id": "r1", "message": "nudge", "message_mode": "verbatim", "delay_seconds": 1}],
        # a one-minute window that is almost certainly not "now"
        "send_window": {"timezone": "Asia/Kolkata", "days": [0], "start": "03:00", "end": "03:01"},
    })
    now = int(time.time())
    _ = now
    # 1970-01-05 was a Monday; 345600 = 05:30 IST, outside the 03:00–03:01 window
    monday_4am = 345600
    repo.add_message(int(account["id"]), int(room["id"]), "out", "Hello", ts=monday_4am - 100)
    assert asyncio.run(scheduler.tick(monday_4am))["followups"] == 0


def test_job_fires_and_is_disabled_after_one_shot(fresh_account):
    account = fresh_account
    repo.ensure_room(int(account["id"]), "911111130004@s.whatsapp.net", "dm", "Ops")
    now = int(time.time())
    job = repo.create_job(
        int(account["id"]),
        {"type": "scheduled_whatsapp_message", "room_id": None, "message": "Standup in 10 minutes"},
        "", "2026-01-01T09:00:00", None, now - 5,
    )
    assert asyncio.run(scheduler.tick(now))["jobs"] == 1

    after = [item for item in repo.list_jobs(int(account["id"])) if item["id"] == job["id"]][0]
    assert bool(after["enabled"]) is False
    assert any(row["text"] == "Standup in 10 minutes" for row in repo.queued_outbox())


def test_task_runs_once(fresh_account):
    account = fresh_account
    repo.ensure_room(int(account["id"]), "911111130005@s.whatsapp.net", "dm", "Ops")
    now = int(time.time())
    repo.create_task(int(account["id"]), {"message": "Reminder: send the brochure"}, now - 1)
    assert asyncio.run(scheduler.tick(now))["tasks"] == 1
    assert asyncio.run(scheduler.tick(now + 10))["tasks"] == 0
    assert any(row["text"] == "Reminder: send the brochure" for row in repo.queued_outbox())


def test_rrule_next_occurrence_daily():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Kolkata")
    start = "2026-01-01T09:00:00"
    after = int(datetime(2026, 1, 1, 10, 0, tzinfo=tz).timestamp())
    nxt = rrule.next_occurrence("FREQ=DAILY;BYHOUR=9;BYMINUTE=0", start, after, "Asia/Kolkata")
    assert nxt is not None
    assert nxt > after


def test_rrule_until_stops():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Kolkata")
    start = "2026-01-01T09:00:00"
    after = int(datetime(2026, 1, 3, 10, 0, tzinfo=tz).timestamp())
    assert rrule.next_occurrence("FREQ=DAILY;UNTIL=2026-01-02T23:59:59", start, after, "Asia/Kolkata") is None
