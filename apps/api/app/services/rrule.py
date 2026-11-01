"""Minimal iCalendar RRULE support: FREQ=DAILY|WEEKLY|MONTHLY, INTERVAL,
BYHOUR, BYMINUTE, BYDAY, UNTIL.

Enough for "every weekday at 9am" and "weekly on Monday". Anything more exotic
(COUNT, BYSETPOS, BYMONTH) should move to `dateutil.rrule`.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def _parse(rrule: str) -> dict[str, str]:
    parts: dict[str, str] = {}
    for chunk in rrule.strip().lstrip("RRULE:").split(";"):
        if "=" in chunk:
            key, value = chunk.split("=", 1)
            parts[key.strip().upper()] = value.strip().upper()
    return parts


def _combine(day: date, hour: int, minute: int, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time(hour=hour, minute=minute), tz)


def next_occurrence(rrule: str, dtstart_local: str, after_utc: int, timezone: str) -> Optional[int]:
    """Return the next epoch second strictly after `after_utc`, or None if done."""
    tz = ZoneInfo(timezone)
    parts = _parse(rrule)
    if not parts:
        return None

    try:
        start = datetime.fromisoformat(dtstart_local)
    except ValueError:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz)

    hour = int(parts.get("BYHOUR", start.hour))
    minute = int(parts.get("BYMINUTE", start.minute))
    interval = max(1, int(parts.get("INTERVAL", "1")))
    freq = parts.get("FREQ", "DAILY")
    byday = [WEEKDAYS[d] for d in parts.get("BYDAY", "").split(",") if d in WEEKDAYS]
    until = parts.get("UNTIL")

    after_local = datetime.fromtimestamp(after_utc, tz)
    candidate = _combine(start.date(), hour, minute, tz)
    if candidate <= after_local:
        candidate = _combine(after_local.date(), hour, minute, tz)

    for _ in range(1000):
        if candidate > after_local:
            if freq == "DAILY":
                delta_days = (candidate.date() - start.date()).days
                if delta_days % interval == 0:
                    break
            elif freq == "WEEKLY":
                weeks = (candidate.date() - start.date()).days // 7
                if weeks % interval == 0 and (not byday or candidate.weekday() in byday):
                    break
            elif freq == "MONTHLY":
                months = (candidate.year - start.year) * 12 + (candidate.month - start.month)
                if months % interval == 0:
                    break
            else:
                break
        candidate += timedelta(days=1)
        candidate = _combine(candidate.date(), hour, minute, tz)
    else:
        return None

    if until:
        try:
            until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
            if until_dt.tzinfo is None:
                until_dt = until_dt.replace(tzinfo=tz)
            if candidate > until_dt:
                return None
        except ValueError:
            pass
    return int(candidate.timestamp())
