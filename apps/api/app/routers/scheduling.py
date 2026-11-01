"""Recurring jobs and one-shot tasks."""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException

from .. import repo
from ..deps import current_account
from ..schemas import ScheduleBody
from ..services import rrule

router = APIRouter(prefix="/dashboard", tags=["scheduling"])


def _parse_local(value: str, timezone: str) -> int:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_local_datetime") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone))
    return int(parsed.timestamp())


@router.get("/jobs")
def list_jobs(account: dict = Depends(current_account)) -> dict:
    return {"items": repo.list_jobs(int(account["id"]))}


@router.post("/jobs", status_code=201)
def create_job(body: ScheduleBody, account: dict = Depends(current_account)) -> dict:
    timezone = account.get("timezone") or "Asia/Kolkata"
    dtstart_local = body.dtstart_local or body.execute_after_local
    if not dtstart_local:
        raise HTTPException(status_code=422, detail="dtstart_local_required")
    if body.rrule:
        next_at = rrule.next_occurrence(body.rrule, dtstart_local, int(time.time()), timezone)
    else:
        next_at = _parse_local(dtstart_local, timezone)
    job = repo.create_job(
        int(account["id"]), body.context, body.rrule or "", dtstart_local, body.until_local, next_at or 0
    )
    return job


@router.patch("/jobs/{job_id}")
def patch_job(job_id: int, body: dict, account: dict = Depends(current_account)) -> dict:
    jobs = [job for job in repo.list_jobs(int(account["id"])) if int(job["id"]) == job_id]
    if not jobs:
        raise HTTPException(status_code=404, detail="job_not_found")
    job = jobs[0]
    context = dict(job.get("context") or {})
    if "message" in body:
        context["message"] = body["message"]
    if "room_id" in body:
        context["room_id"] = body["room_id"]
    updates = {}
    if context != job.get("context"):
        updates["context_json"] = json.dumps(context, ensure_ascii=False)
    for key in ("enabled", "rrule", "until_local"):
        if key in body and body[key] is not None:
            updates[key] = body[key]
    if "enabled" in body:
        updates["enabled"] = 1 if body["enabled"] else 0
    if "rrule" in body and body["rrule"]:
        timezone = account.get("timezone") or "Asia/Kolkata"
        updates["next_run_at"] = rrule.next_occurrence(body["rrule"], job["dtstart_local"], int(time.time()), timezone)
    repo.update_job(job_id, **updates)
    return next(item for item in repo.list_jobs(int(account["id"])) if int(item["id"]) == job_id)


@router.post("/jobs/{job_id}/toggle-status")
def toggle_job(job_id: int, account: dict = Depends(current_account)) -> dict:
    jobs = [job for job in repo.list_jobs(int(account["id"])) if int(job["id"]) == job_id]
    if not jobs:
        raise HTTPException(status_code=404, detail="job_not_found")
    enabled = 0 if jobs[0]["enabled"] else 1
    repo.update_job(job_id, enabled=enabled)
    return {"enabled": bool(enabled)}


@router.get("/tasks")
def list_tasks(account: dict = Depends(current_account)) -> dict:
    return {"items": repo.list_tasks(int(account["id"]))}


@router.post("/tasks", status_code=201)
def create_task(body: ScheduleBody, account: dict = Depends(current_account)) -> dict:
    timezone = account.get("timezone") or "Asia/Kolkata"
    when = body.execute_after_local or body.dtstart_local
    if not when:
        raise HTTPException(status_code=422, detail="execute_after_local_required")
    return repo.create_task(int(account["id"]), body.context, _parse_local(when, timezone))


@router.post("/tasks/{task_id}/pause")
def pause_task(task_id: int, account: dict = Depends(current_account)) -> dict:
    tasks = [task for task in repo.list_tasks(int(account["id"])) if int(task["id"]) == task_id]
    if not tasks:
        raise HTTPException(status_code=404, detail="task_not_found")
    repo.stop_task(task_id)
    return {"status": "paused"}
