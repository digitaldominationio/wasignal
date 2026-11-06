"""MongoDB implementation of the repository contract.

Same function names and dict shapes as `repo_sqlite.py`; `app/repo.py` picks one
at import time. Ids are integer counters (see ids.py), so the public API is
unchanged and a SQLite database can be copied over one-to-one.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from pymongo.errors import DuplicateKeyError

from .ids import next_id
from .mongo import get_db


def _c(name: str) -> Any:
    return get_db()[name]


def _out(doc: Any) -> Any:
    if doc is None:
        return None
    out = dict(doc)
    ident = out.pop("_id", None)
    out["id"] = ident
    return out


def _insert(collection: str, **fields: Any) -> int:
    ident = next_id(collection)
    _c(collection).insert_one({"_id": ident, **fields})
    return ident


def _dumps(value: Any) -> str:  # parity helper for callers that used it
    import json

    return json.dumps(value, ensure_ascii=False)


# ------------------------------------------------------------------ accounts


def list_accounts(pid: int) -> list[dict[str, Any]]:
    return [_out(d) for d in _c("accounts").find({"partner_pid": pid}).sort("_id", 1)]


def get_account(pid: int, account_id: int) -> dict[str, Any]:
    doc = _c("accounts").find_one({"_id": account_id, "partner_pid": pid})
    if doc is None:
        raise KeyError("account not found")
    return _out(doc)


def default_account(pid: int) -> dict[str, Any]:
    doc = _c("accounts").find_one({"partner_pid": pid}, sort=[("_id", 1)])
    if doc is None:
        raise KeyError("no account for partner")
    return _out(doc)


def create_account(org_id: int, partner_pid: int, name: str, timezone: str) -> dict[str, Any]:
    ident = create_account_full(org_id, partner_pid, name, "", timezone)
    return account_by_id(ident)  # type: ignore[return-value]


def list_org_accounts(org_id: int) -> list[dict[str, Any]]:
    return [_out(d) for d in _c("accounts").find({"org_id": org_id}).sort("_id", 1)]


def count_org_accounts(org_id: int) -> int:
    return int(_c("accounts").count_documents({"org_id": org_id}))


# --------------------------------------------------------------------- rooms


def list_rooms(account_id: int) -> list[dict[str, Any]]:
    return [_out(d) for d in _c("rooms").find({"account_id": account_id}).sort(
        [("last_activity_at", -1), ("_id", 1)]
    )]


def get_room(account_id: int, room_id: int) -> dict[str, Any]:
    doc = _c("rooms").find_one({"_id": room_id, "account_id": account_id})
    if doc is None:
        raise KeyError("room not found")
    return _out(doc)


def ensure_room(account_id: int, external_id: str, kind: str = "dm", display_name: str = "") -> dict[str, Any]:
    doc = _c("rooms").find_one({"account_id": account_id, "external_id": external_id})
    if doc is not None:
        return _out(doc)
    try:
        ident = _insert(
            "rooms", account_id=account_id, external_id=external_id, kind=kind,
            display_name=display_name, is_excluded=0, last_activity_at=int(time.time()),
        )
    except DuplicateKeyError:
        doc = _c("rooms").find_one({"account_id": account_id, "external_id": external_id})
        return _out(doc)
    return _out(_c("rooms").find_one({"_id": ident}))


def ensure_system_room(account_id: int) -> dict[str, Any]:
    return ensure_room(account_id, "system", "system", "Assistant")


def system_room(account_id: int) -> Optional[dict[str, Any]]:
    doc = _c("rooms").find_one({"account_id": account_id, "kind": "system"})
    return _out(doc)


def set_exclusion(account_id: int, room_id: int, excluded: bool) -> None:
    _c("rooms").update_one(
        {"_id": room_id, "account_id": account_id}, {"$set": {"is_excluded": 1 if excluded else 0}}
    )


# ------------------------------------------------------------------ messages


def add_message(account_id: int, room_id: int, direction: str, text: str, *,
                sender: str = "", sender_name: str = "", media: Optional[list[dict[str, Any]]] = None,
                ts: Optional[int] = None, status: str = "delivered", source: str = "whatsapp",
                agent_id: Optional[int] = None, run_id: Optional[int] = None) -> dict[str, Any]:
    now = int(ts if ts is not None else time.time())
    ident = _insert(
        "messages", account_id=account_id, room_id=room_id, direction=direction, sender=sender,
        sender_name=sender_name, text=text, media=media or [], ts=now, status=status,
        source=source, agent_id=agent_id, run_id=run_id,
    )
    _c("rooms").update_one({"_id": room_id}, {"$set": {"last_activity_at": now}})
    return _out(_c("messages").find_one({"_id": ident}))


def list_messages(room_id: int, *, limit: int = 50, before_ts: Optional[int] = None) -> list[dict[str, Any]]:
    query: dict[str, Any] = {"room_id": room_id}
    if before_ts is not None:
        query["ts"] = {"$lte": before_ts}
    cursor = _c("messages").find(query).sort([("ts", -1), ("_id", -1)]).limit(limit)
    return [_out(doc) for doc in cursor]


def history(room_id: int, limit: int) -> list[dict[str, Any]]:
    return list(reversed(list_messages(room_id, limit=limit)))


def last_message_at(room_id: int, direction: str) -> int:
    doc = _c("messages").find_one({"room_id": room_id, "direction": direction}, sort=[("ts", -1)])
    return int(doc["ts"]) if doc else 0


def last_message(room_id: int, direction: str) -> Optional[dict[str, Any]]:
    return _out(_c("messages").find_one({"room_id": room_id, "direction": direction}, sort=[("ts", -1)]))


# -------------------------------------------------------------------- agents


def _agent(doc: dict[str, Any]) -> dict[str, Any]:
    row = _out(doc)
    row.setdefault("excluded_room_ids", [])
    row.setdefault("capabilities", ["read", "send"])
    row.setdefault("tool_suites", [])
    row.setdefault("webhook_ids", [])
    return row


def list_agents(account_id: int, include_paused: bool = True) -> list[dict[str, Any]]:
    query: dict[str, Any] = {"account_id": account_id}
    if not include_paused:
        query["status"] = "active"
    return [_agent(doc) for doc in _c("agents").find(query).sort("_id", 1)]


def get_agent(account_id: int, agent_id: int) -> dict[str, Any]:
    doc = _c("agents").find_one({"_id": agent_id, "account_id": account_id})
    if doc is None:
        raise KeyError("agent not found")
    return _agent(doc)


def create_agent(account_id: int, body: dict[str, Any]) -> dict[str, Any]:
    ident = _insert(
        "agents",
        account_id=account_id,
        name=body["name"],
        system_prompt=body["system_prompt"],
        trigger_type=body.get("trigger_type", "event"),
        trigger_scope=body.get("trigger_scope", "room"),
        trigger_condition=body.get("trigger_condition"),
        room_id=body.get("room_id"),
        chat_type=body.get("chat_type", "all"),
        excluded_room_ids=body.get("excluded_room_ids", []),
        capabilities=body.get("capabilities", ["read", "send"]),
        tool_suites=body.get("tool_suites", []),
        webhook_ids=body.get("webhook_ids", []),
        llm_provider=body.get("llm_provider"),
        llm_model=body.get("llm_model"),
        recurrence_cron=body.get("recurrence_cron"),
        timezone=body.get("timezone", "Asia/Kolkata"),
        max_iterations=body.get("max_iterations", 6),
        timeout_seconds=body.get("timeout_seconds", 60),
        max_memory_chars=body.get("max_memory_chars", 4000),
        status="active",
        created_at=int(time.time()),
    )
    return get_agent(account_id, ident)


def update_agent(account_id: int, agent_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    fields = {key: value for key, value in patch.items() if value is not None}
    if fields:
        _c("agents").update_one({"_id": agent_id, "account_id": account_id}, {"$set": fields})
    return get_agent(account_id, agent_id)


def toggle_agent(account_id: int, agent_id: int) -> dict[str, Any]:
    agent = get_agent(account_id, agent_id)
    status = "paused" if agent["status"] == "active" else "active"
    _c("agents").update_one({"_id": agent_id}, {"$set": {"status": status}})
    return get_agent(account_id, agent_id)


# --------------------------------------------------------------------- lanes


def get_lane(agent_id: int, room_id: int, lane_key: str = "main") -> dict[str, Any]:
    doc = _c("lanes").find_one({"agent_id": agent_id, "room_id": room_id, "lane_key": lane_key})
    if doc is None:
        try:
            _insert("lanes", agent_id=agent_id, room_id=room_id, lane_key=lane_key,
                    session_memory="", pending_steps=[], handed_over=0, last_run_at=0)
        except DuplicateKeyError:
            pass
        doc = _c("lanes").find_one({"agent_id": agent_id, "room_id": room_id, "lane_key": lane_key})
    row = _out(doc)
    row["pending_steps"] = row.get("pending_steps") or []
    return row


def list_lanes(agent_id: int) -> list[dict[str, Any]]:
    rows = [_out(d) for d in _c("lanes").find({"agent_id": agent_id}).sort("last_run_at", -1)]
    names = {room["id"]: room["display_name"] for room in list_rooms_for_names(rows)}
    for row in rows:
        row["room_name"] = names.get(int(row["room_id"]), "")
        row["pending_steps"] = row.get("pending_steps") or []
    return rows


def list_rooms_for_names(lanes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ids = [lane["room_id"] for lane in lanes]
    if not ids:
        return []
    return [_out(d) for d in _c("rooms").find({"_id": {"$in": ids}})]


def reset_lane(agent_id: int, room_id: int, lane_key: str) -> None:
    _c("lanes").update_one(
        {"agent_id": agent_id, "room_id": room_id, "lane_key": lane_key},
        {"$set": {"session_memory": "", "pending_steps": []}},
    )


def set_handover(agent_id: int, room_id: int, handed_over: bool, lane_key: str = "main") -> None:
    get_lane(agent_id, room_id, lane_key)
    _c("lanes").update_one(
        {"agent_id": agent_id, "room_id": room_id, "lane_key": lane_key},
        {"$set": {"handed_over": 1 if handed_over else 0}},
    )


def touch_lane(agent_id: int, room_id: int, lane_key: str = "main") -> None:
    _c("lanes").update_one(
        {"agent_id": agent_id, "room_id": room_id, "lane_key": lane_key},
        {"$set": {"last_run_at": int(time.time())}},
    )


# -------------------------------------------------------------------- memory


def list_memory(agent_id: int) -> list[dict[str, Any]]:
    return [{"key": d["key"], "value": d["value"]} for d in _c("memory").find({"agent_id": agent_id}).sort("key", 1)]


def memory_block(agent_id: int, limit_chars: int) -> str:
    lines = [f"{row['key']}: {row['value']}" for row in list_memory(agent_id)]
    text = "\n".join(lines)
    return text[-limit_chars:] if len(text) > limit_chars else text


def set_memory(agent_id: int, key: str, value: str) -> None:
    _c("memory").update_one(
        {"agent_id": agent_id, "key": key}, {"$set": {"value": value}}, upsert=True
    )


def delete_memory(agent_id: int, key: str) -> bool:
    result = _c("memory").delete_one({"agent_id": agent_id, "key": key})
    return bool(result.deleted_count)


# ---------------------------------------------------------------------- runs


def create_run(agent_id: int, account_id: int, room_id: Optional[int], trigger: str, lane: str = "main") -> int:
    return _insert(
        "runs", agent_id=agent_id, account_id=account_id, room_id=room_id, lane=lane, trigger=trigger,
        status="running", stage="assembling", reason=None, iterations=0, tokens=0, reply="",
        llm_provider=None, llm_model=None, tool_calls=[], started_at=int(time.time()), finished_at=None,
    )


def finish_run(run_id: int, *, status: str, stage: str, iterations: int, tokens: int, reply: str,
               reason: Optional[str] = None, provider: Optional[str] = None, model: Optional[str] = None,
               tool_calls: Optional[list[dict[str, Any]]] = None) -> None:
    _c("runs").update_one({"_id": run_id}, {"$set": {
        "status": status, "stage": stage, "iterations": iterations, "tokens": tokens, "reply": reply,
        "reason": reason, "llm_provider": provider, "llm_model": model,
        "tool_calls": tool_calls or [], "finished_at": int(time.time()),
    }})


def list_runs(account_id: int, agent_id: Optional[int] = None, limit: int = 50) -> list[dict[str, Any]]:
    query: dict[str, Any] = {"account_id": account_id}
    if agent_id is not None:
        query["agent_id"] = agent_id
    rows = [_out(d) for d in _c("runs").find(query).sort("_id", -1).limit(limit)]
    for row in rows:
        row["tool_calls"] = row.get("tool_calls") or []
    return rows


# ------------------------------------------------------------------ webhooks


def _webhook(doc: dict[str, Any]) -> dict[str, Any]:
    row = _out(doc)
    row["headers"] = [
        {**header, "value": None} if header.get("secret") else header for header in row.get("headers", [])
    ]
    row["body_fields"] = [
        {**field, "value": None} if field.get("secret") else field for field in row.get("body_fields", [])
    ]
    return row


def list_webhooks(account_id: int) -> list[dict[str, Any]]:
    return [_webhook(d) for d in _c("webhooks").find({"account_id": account_id}).sort("_id", 1)]


def get_webhook(account_id: int, webhook_id: int) -> dict[str, Any]:
    doc = _c("webhooks").find_one({"_id": webhook_id, "account_id": account_id})
    if doc is None:
        raise KeyError("webhook not found")
    return _webhook(doc)


def raw_webhook(account_id: int, webhook_id: int) -> dict[str, Any]:
    doc = _c("webhooks").find_one({"_id": webhook_id, "account_id": account_id})
    if doc is None:
        raise KeyError("webhook not found")
    row = _out(doc)
    row.setdefault("headers", [])
    row.setdefault("body_fields", [])
    return row


def create_webhook(account_id: int, body: dict[str, Any]) -> dict[str, Any]:
    ident = _insert(
        "webhooks", account_id=account_id, name=body["name"], description=body.get("description", ""),
        url=body["url"], method=body.get("method", "POST"), headers=body.get("headers", []),
        body_fields=body.get("body_fields", []), active=1, created_at=int(time.time()),
    )
    return get_webhook(account_id, ident)


def update_webhook(account_id: int, webhook_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    raw = raw_webhook(account_id, webhook_id)
    fields: dict[str, Any] = {}
    for key, value in patch.items():
        if value is None:
            continue
        if key in {"headers", "body_fields"}:
            fields[key] = _merge_write_only(raw.get(key, []), value)
        elif key == "active":
            fields[key] = 1 if value else 0
        else:
            fields[key] = value
    if fields:
        _c("webhooks").update_one({"_id": webhook_id}, {"$set": fields})
    return get_webhook(account_id, webhook_id)


def _merge_write_only(current: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {item.get("name") or item.get("key"): item for item in current}
    merged: list[dict[str, Any]] = []
    for item in incoming:
        key = item.get("name") or item.get("key")
        previous = by_key.get(key, {})
        if item.get("secret") and item.get("value") in (None, ""):
            item = {**item, "value": previous.get("value")}
        merged.append(item)
    return merged


def delete_webhook(account_id: int, webhook_id: int) -> None:
    if _c("agents").count_documents({"account_id": account_id, "webhook_ids": webhook_id}):
        raise ValueError("webhook_in_use")
    _c("webhooks").delete_one({"_id": webhook_id, "account_id": account_id})


def add_delivery(webhook_id: int, account_id: int, trigger: str, status_code: Optional[int],
                 duration_ms: int, error: Optional[str]) -> int:
    return _insert(
        "deliveries", webhook_id=webhook_id, account_id=account_id, trigger=trigger,
        status_code=status_code, duration_ms=duration_ms, error=error, created_at=int(time.time()),
    )


def list_deliveries(account_id: int, webhook_id: int, limit: int = 50) -> list[dict[str, Any]]:
    return [_out(d) for d in _c("deliveries").find(
        {"account_id": account_id, "webhook_id": webhook_id}
    ).sort("_id", -1).limit(limit)]


# ----------------------------------------------------------------- knowledge


def list_sources(account_id: int) -> list[dict[str, Any]]:
    return [_out(d) for d in _c("knowledge_sources").find({"account_id": account_id}).sort("_id", 1)]


def create_source(account_id: int, body: dict[str, Any]) -> dict[str, Any]:
    ident = _insert(
        "knowledge_sources", account_id=account_id, name=body["name"],
        source_room_id=body["source_room_id"], source_type=body.get("source_type", "whatsapp_room"),
        extraction_instruction=body.get("extraction_instruction", ""), status="ready",
        created_at=int(time.time()),
    )
    return _out(_c("knowledge_sources").find_one({"_id": ident}))


def list_entries(source_id: int) -> list[dict[str, Any]]:
    return [_out(d) for d in _c("knowledge_entries").find({"source_id": source_id}).sort("_id", 1)]


def create_entry(source_id: int, body: dict[str, Any]) -> dict[str, Any]:
    ident = _insert(
        "knowledge_entries", source_id=source_id, keys=body.get("keys", []), title=body.get("title", ""),
        content=body.get("content", ""), medias=body.get("medias", []), metadata=body.get("metadata", {}),
    )
    return _out(_c("knowledge_entries").find_one({"_id": ident}))


def all_entries(account_id: int) -> list[dict[str, Any]]:
    sources = list_sources(account_id)
    names = {source["id"]: source["name"] for source in sources}
    if not names:
        return []
    rows = [_out(d) for d in _c("knowledge_entries").find({"source_id": {"$in": list(names)}})]
    for row in rows:
        row["source_name"] = names.get(int(row["source_id"]))
    return rows


def set_agent_knowledge(agent_id: int, source_ids: list[int]) -> None:
    _c("agent_knowledge").delete_many({"agent_id": agent_id})
    if source_ids:
        _c("agent_knowledge").insert_many([
            {"agent_id": agent_id, "source_id": int(source_id)} for source_id in source_ids
        ])


def agent_knowledge_ids(agent_id: int) -> list[int]:
    return [int(d["source_id"]) for d in _c("agent_knowledge").find({"agent_id": agent_id})]


def agent_knowledge_sources(agent_id: int) -> list[dict[str, Any]]:
    ids = agent_knowledge_ids(agent_id)
    if not ids:
        return []
    return [_out(d) for d in _c("knowledge_sources").find({"_id": {"$in": ids}}).sort("_id", 1)]


# ---------------------------------------------------------------- scheduling


def create_job(account_id: int, context: dict[str, Any], rrule: str, dtstart_local: str,
               until_local: Optional[str], next_run_at: int) -> dict[str, Any]:
    ident = _insert(
        "jobs", account_id=account_id, context=context, rrule=rrule, dtstart_local=dtstart_local,
        until_local=until_local, next_run_at=next_run_at, enabled=1, last_fired_at=None,
    )
    return _out(_c("jobs").find_one({"_id": ident}))


def list_jobs(account_id: int) -> list[dict[str, Any]]:
    return [_out(d) for d in _c("jobs").find({"account_id": account_id}).sort("_id", 1)]


def due_jobs(now: int) -> list[dict[str, Any]]:
    return [_out(d) for d in _c("jobs").find(
        {"enabled": 1, "next_run_at": {"$lte": now, "$ne": None}}
    ).sort("_id", 1)]


def update_job(job_id: int, **fields: Any) -> None:
    if fields:
        _c("jobs").update_one({"_id": job_id}, {"$set": fields})


def create_task(account_id: int, context: dict[str, Any], execute_after_at: int) -> dict[str, Any]:
    ident = _insert(
        "tasks", account_id=account_id, context=context, execute_after_at=execute_after_at, status="pending"
    )
    return _out(_c("tasks").find_one({"_id": ident}))


def list_tasks(account_id: int) -> list[dict[str, Any]]:
    return [_out(d) for d in _c("tasks").find({"account_id": account_id}).sort("_id", 1)]


def due_tasks(now: int) -> list[dict[str, Any]]:
    return [_out(d) for d in _c("tasks").find(
        {"status": "pending", "execute_after_at": {"$lte": now}}
    ).sort("_id", 1)]


# ----------------------------------------------------------------- followups


def get_followup_rules(agent_id: int) -> dict[str, Any]:
    doc = _c("followup_rules").find_one({"scope": "agent", "ref_id": agent_id})
    if doc is None:
        return {"enabled": False, "rules": [], "send_window": None}
    return {
        "enabled": bool(doc.get("enabled")),
        "rules": doc.get("rules", []),
        "send_window": doc.get("send_window"),
    }


def put_followup_rules(account_id: int, agent_id: int, body: dict[str, Any]) -> dict[str, Any]:
    rules = body.get("rules", [])
    for index, rule in enumerate(rules):
        rule.setdefault("id", f"r{index + 1}")
    existing = _c("followup_rules").find_one({"scope": "agent", "ref_id": agent_id})
    fields = {
        "enabled": 1 if body.get("enabled", True) else 0,
        "rules": rules,
        "send_window": body.get("send_window") or {},
    }
    if existing is None:
        _insert("followup_rules", account_id=account_id, scope="agent", ref_id=agent_id, **fields)
    else:
        _c("followup_rules").update_one({"_id": existing["_id"]}, {"$set": fields})
    return get_followup_rules(agent_id)


def enabled_followup_rules() -> list[dict[str, Any]]:
    rows = [_out(d) for d in _c("followup_rules").find({"enabled": 1, "scope": "agent"})]
    for row in rows:
        row["window"] = row.get("send_window") or {}
        row["rules"] = row.get("rules") or []
    return rows


def followup_already_sent(rule_id: int, room_id: int, rule_key: str) -> bool:
    return bool(_c("followup_runs").count_documents(
        {"rule_id": rule_id, "room_id": room_id, "rule_key": rule_key, "status": "sent"}
    ))


def record_followup(rule_id: int, room_id: int, rule_key: str, due_at: int, status: str) -> int:
    return _insert(
        "followup_runs", rule_id=rule_id, room_id=room_id, rule_key=rule_key, due_at=due_at,
        sent_at=int(time.time()) if status == "sent" else None, status=status,
    )


def list_followup_runs(agent_id: int, limit: int = 50) -> list[dict[str, Any]]:
    rule_ids = [int(d["_id"]) for d in _c("followup_rules").find({"scope": "agent", "ref_id": agent_id})]
    if not rule_ids:
        return []
    return [_out(d) for d in _c("followup_runs").find(
        {"rule_id": {"$in": rule_ids}}
    ).sort("_id", -1).limit(limit)]


# ------------------------------------------------------------------ settings


def human_pause_enabled(account_id: int) -> bool:
    doc = _c("settings").find_one({"_id": account_id})
    return True if doc is None else bool(doc.get("human_active_pause", 1))


def set_human_pause(account_id: int, enabled: bool) -> None:
    _c("settings").update_one(
        {"_id": account_id}, {"$set": {"human_active_pause": 1 if enabled else 0}}, upsert=True
    )


def owner_spoke_recently(account_id: int, room_id: int, within_seconds: int) -> bool:
    cutoff = int(time.time()) - within_seconds
    return bool(_c("messages").count_documents(
        {"account_id": account_id, "room_id": room_id, "source": "owner", "ts": {"$gte": cutoff}}
    ))


# -------------------------------------------------------------------- outbox


def enqueue_outbox(account_id: int, room_id: int, text: str,
                   media: Optional[list[dict[str, Any]]] = None,
                   message_id: Optional[int] = None) -> int:
    return _insert(
        "outbox", account_id=account_id, room_id=room_id, message_id=message_id, text=text,
        media=media or [], status="queued", error=None, created_at=int(time.time()), sent_at=None,
    )


def queued_outbox(limit: int = 20) -> list[dict[str, Any]]:
    return [_out(d) for d in _c("outbox").find({"status": "queued"}).sort("_id", 1).limit(limit)]


def mark_outbox(outbox_id: int, status: str, error: Optional[str] = None,
                message_id: Optional[int] = None) -> None:
    _c("outbox").update_one({"_id": outbox_id}, {"$set": {
        "status": status, "error": error, "sent_at": int(time.time()) if status == "sent" else None,
    }})
    if message_id is not None:
        _c("messages").update_one({"_id": message_id}, {
            "$set": {"status": "delivered" if status == "sent" else "failed"}
        })


def outbox_context(outbox_id: int) -> Optional[dict[str, Any]]:
    doc = _c("outbox").find_one({"_id": outbox_id})
    if doc is None:
        return None
    outbox = _out(doc)
    account = account_by_id(int(outbox["account_id"]))
    room = _out(_c("rooms").find_one({"_id": outbox["room_id"]}))
    return {"outbox": outbox, "account": account, "room": room}


def outbox_stats() -> dict[str, int]:
    stats: dict[str, int] = {}
    for row in _c("outbox").aggregate([{"$group": {"_id": "$status", "n": {"$sum": 1}}}]):
        stats[str(row["_id"])] = int(row["n"])
    return stats


# ------------------------------------------------------------- organizations


def create_org(owner_pid: int, name: str, slug: str) -> dict[str, Any]:
    ident = _insert("organizations", name=name, slug=slug, owner_pid=owner_pid, created_at=int(time.time()))
    add_membership(ident, owner_pid, "owner")
    return get_org(ident)


def get_org(org_id: int) -> dict[str, Any]:
    doc = _c("organizations").find_one({"_id": org_id})
    if doc is None:
        raise KeyError("org not found")
    return _out(doc)


def orgs_for_partner(pid: int) -> list[dict[str, Any]]:
    memberships = [_out(d) for d in _c("memberships").find({"pid": pid}).sort("_id", 1)]
    if not memberships:
        return []
    orgs = {int(d["_id"]): _out(d) for d in _c("organizations").find(
        {"_id": {"$in": [m["org_id"] for m in memberships]}}
    )}
    result = []
    for membership in memberships:
        org = orgs.get(int(membership["org_id"]))
        if org is not None:
            result.append({**org, "role": membership["role"]})
    return result


def first_org_for_partner(pid: int) -> Optional[dict[str, Any]]:
    membership = _out(_c("memberships").find_one({"pid": pid}, sort=[("_id", 1)]))
    if membership is None:
        return None
    org = _out(_c("organizations").find_one({"_id": membership["org_id"]}))
    return {**org, "role": membership["role"]} if org else None


def add_membership(org_id: int, pid: int, role: str = "member") -> None:
    _c("memberships").update_one(
        {"org_id": org_id, "pid": pid},
        {"$set": {"role": role}, "$setOnInsert": {"created_at": int(time.time())}},
        upsert=True,
    )


def membership(org_id: int, pid: int) -> Optional[dict[str, Any]]:
    return _out(_c("memberships").find_one({"org_id": org_id, "pid": pid}))


def list_memberships(org_id: int) -> list[dict[str, Any]]:
    rows = [_out(d) for d in _c("memberships").find({"org_id": org_id}).sort("_id", 1)]
    partners = {int(d["_id"]): _out(d) for d in _c("partners").find({"_id": {"$in": [r["pid"] for r in rows]}})}
    for row in rows:
        partner = partners.get(int(row["pid"]), {})
        row["name"] = partner.get("name", "")
        row["phone"] = partner.get("phone", "")
    return rows


def count_memberships(org_id: int) -> int:
    return int(_c("memberships").count_documents({"org_id": org_id}))


def set_membership_role(org_id: int, pid: int, role: str) -> None:
    _c("memberships").update_one({"org_id": org_id, "pid": pid}, {"$set": {"role": role}})


def remove_membership(org_id: int, pid: int) -> None:
    _c("memberships").delete_one({"org_id": org_id, "pid": pid})


def create_invitation(org_id: int, phone: str, role: str, token: str, invited_by: int,
                      expires_at: int) -> dict[str, Any]:
    ident = _insert(
        "invitations", org_id=org_id, phone=phone, role=role, token=token, invited_by=invited_by,
        created_at=int(time.time()), expires_at=expires_at, accepted_at=None, declined_at=None,
    )
    return _out(_c("invitations").find_one({"_id": ident}))


def list_invitations(org_id: int, pending_only: bool = True) -> list[dict[str, Any]]:
    query: dict[str, Any] = {"org_id": org_id}
    if pending_only:
        query.update({"accepted_at": None, "declined_at": None, "expires_at": {"$gte": int(time.time())}})
    return [_out(d) for d in _c("invitations").find(query).sort("_id", -1)]


def invitation_by_token(token: str) -> Optional[dict[str, Any]]:
    return _out(_c("invitations").find_one({"token": token}))


def accept_invitation(invite_id: int) -> None:
    _c("invitations").update_one({"_id": invite_id}, {"$set": {"accepted_at": int(time.time())}})


def decline_invitation(invite_id: int) -> None:
    _c("invitations").update_one({"_id": invite_id}, {"$set": {"declined_at": int(time.time())}})


def invitations_for_phone(phone: str) -> list[dict[str, Any]]:
    return [_out(d) for d in _c("invitations").find({
        "phone": phone, "accepted_at": None, "declined_at": None,
        "expires_at": {"$gte": int(time.time())},
    })]


# -------------------------------------------------------------- subscriptions


def get_subscription(org_id: int) -> Optional[dict[str, Any]]:
    return _out(_c("subscriptions").find_one({"_id": org_id}))


def upsert_subscription(org_id: int, plan_id: str, status: str, period_start: int, period_end: int,
                        *, provider: str = "manual", provider_ref: Optional[str] = None,
                        cancel_at_period_end: bool = False) -> dict[str, Any]:
    now = int(time.time())
    _c("subscriptions").update_one({"_id": org_id}, {"$set": {
        "plan_id": plan_id, "status": status, "current_period_start": period_start,
        "current_period_end": period_end, "cancel_at_period_end": 1 if cancel_at_period_end else 0,
        "provider": provider, "provider_ref": provider_ref, "updated_at": now,
    }, "$setOnInsert": {"created_at": now}}, upsert=True)
    return get_subscription(org_id)  # type: ignore[return-value]


# --------------------------------------------------------------------- usage


def add_usage(org_id: int, metric: str, quantity: int = 1, ref: Optional[str] = None) -> None:
    _insert("usage_events", org_id=org_id, metric=metric, quantity=quantity, ts=int(time.time()), ref=ref)


def usage_since(org_id: int, metric: str, since: int) -> int:
    pipeline = [
        {"$match": {"org_id": org_id, "metric": metric, "ts": {"$gte": since}}},
        {"$group": {"_id": None, "total": {"$sum": "$quantity"}}},
    ]
    rows = list(_c("usage_events").aggregate(pipeline))
    return int(rows[0]["total"]) if rows else 0


# --------------------------------------------------------------------- plans


def plan_row(plan_id: str) -> Optional[dict[str, Any]]:
    doc = _c("plans").find_one({"_id": plan_id})
    if doc is None:
        return None
    row = dict(doc)
    row["id"] = row.pop("_id")
    return row


def list_plan_rows() -> list[dict[str, Any]]:
    rows = []
    for doc in _c("plans").find().sort([("sort_order", 1), ("price_inr", 1)]):
        row = dict(doc)
        row["id"] = row.pop("_id")
        rows.append(row)
    return rows


def upsert_plan(plan: dict[str, Any]) -> None:
    _c("plans").replace_one({"_id": plan["id"]}, {
        "_id": plan["id"],
        "name": plan["name"],
        "price_inr": plan["price_inr"],
        "period": plan["period"],
        "tagline": plan["tagline"],
        "features_json": _dumps(plan["features"]),
        "limits_json": _dumps(plan["limits"]),
        "lookup_key": plan["lookup_key"],
        "recommended": 1 if plan.get("recommended") else 0,
        "sort_order": plan.get("sort_order", 0),
    }, upsert=True)


# ------------------------------------------------------------ auth / identity


def _partner_out(doc: Any) -> Optional[dict[str, Any]]:
    """SQLite calls the partner key `pid`; keep that contract on Mongo."""
    row = _out(doc)
    if row is not None:
        row["pid"] = row["id"]
    return row


def partner_by_phone(phone: str) -> Optional[dict[str, Any]]:
    return _partner_out(_c("partners").find_one({"phone": phone}))


def partner(pid: int) -> Optional[dict[str, Any]]:
    return _partner_out(_c("partners").find_one({"_id": pid}))


def create_partner(phone: str, name: str) -> int:
    return _insert("partners", phone=phone, name=name, wa_linked=0, created_at=int(time.time()))


def set_wa_linked(pid: int, linked: bool) -> None:
    _c("partners").update_one({"_id": pid}, {"$set": {"wa_linked": 1 if linked else 0}})


def count_partners() -> int:
    return int(_c("partners").count_documents({}))


def otp_upsert(phone: str, code: str, expires_at: int) -> None:
    _c("otps").update_one(
        {"_id": phone}, {"$set": {"code": code, "expires_at": expires_at, "attempts": 0}}, upsert=True
    )


def otp_get(phone: str) -> Optional[dict[str, Any]]:
    return _out(_c("otps").find_one({"_id": phone}))


def otp_increment_attempts(phone: str) -> None:
    _c("otps").update_one({"_id": phone}, {"$inc": {"attempts": 1}})


def otp_delete(phone: str) -> None:
    _c("otps").delete_one({"_id": phone})


def session_create(token: str, pid: int, expires_at: int) -> None:
    _c("sessions").replace_one(
        {"_id": token}, {"_id": token, "partner_pid": pid, "expires_at": expires_at}, upsert=True
    )


def session_get(token: str) -> Optional[dict[str, Any]]:
    return _out(_c("sessions").find_one({"_id": token}))


def session_delete(token: str) -> None:
    _c("sessions").delete_one({"_id": token})


# -------------------------------------------------------------- full accounts


def create_account_full(org_id: int, partner_pid: int, name: str, wa_number: str,
                        timezone: str, subscription_status: str = "trialing") -> int:
    return _insert(
        "accounts", partner_pid=partner_pid, org_id=org_id, name=name, wa_number=wa_number,
        timezone=timezone, subscription_status=subscription_status, created_at=int(time.time()),
    )


def account_by_id(account_id: int) -> Optional[dict[str, Any]]:
    return _out(_c("accounts").find_one({"_id": account_id}))


def account_by_number(wa_number: str) -> Optional[dict[str, Any]]:
    if not wa_number:
        return None
    return _out(_c("accounts").find_one({"wa_number": wa_number}))


def set_account_number(account_id: int, number: str) -> None:
    _c("accounts").update_one({"_id": account_id}, {"$set": {"wa_number": number}})


# --------------------------------------------------------------------- stats


def messages_since(account_id: int, since: int) -> int:
    return int(_c("messages").count_documents({"account_id": account_id, "ts": {"$gte": since}}))


def runs_since(account_id: int, since: int) -> int:
    return int(_c("runs").count_documents({"account_id": account_id, "started_at": {"$gte": since}}))


def followup_sent_count(account_id: int) -> int:
    rule_ids = [int(d["_id"]) for d in _c("followup_rules").find({"account_id": account_id})]
    if not rule_ids:
        return 0
    return int(_c("followup_runs").count_documents({"rule_id": {"$in": rule_ids}, "status": "sent"}))


def outbox_queued_count(account_id: int) -> int:
    return int(_c("outbox").count_documents({"account_id": account_id, "status": "queued"}))


def activity_rows(account_id: int, since: int) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], int] = {}
    for doc in _c("messages").find({"account_id": account_id, "ts": {"$gte": since}},
                                    {"ts": 1, "direction": 1}):
        day = datetime.fromtimestamp(int(doc["ts"]), tz=timezone.utc).strftime("%Y-%m-%d")
        key = (day, str(doc.get("direction", "")))
        buckets[key] = buckets.get(key, 0) + 1
    return [
        {"day": day, "direction": direction, "n": count}
        for (day, direction), count in sorted(buckets.items(), reverse=True)
    ]


def runs_by_status(account_id: int) -> list[dict[str, Any]]:
    stats: dict[str, int] = {}
    for doc in _c("runs").find({"account_id": account_id}, {"status": 1}):
        status = str(doc.get("status", ""))
        stats[status] = stats.get(status, 0) + 1
    return [{"status": status, "n": count} for status, count in stats.items()]


def stop_task(task_id: int) -> None:
    set_task_status(task_id, "paused")


def set_task_status(task_id: int, status: str) -> None:
    _c("tasks").update_one({"_id": task_id}, {"$set": {"status": status}})


def recent_system_message(account_id: int, text: str, since: int) -> Optional[dict[str, Any]]:
    return _out(_c("messages").find_one(
        {"account_id": account_id, "source": "otp", "text": text, "ts": {"$gte": since}},
        sort=[("_id", -1)],
    ))


def webhook_in_use(account_id: int, webhook_id: int) -> bool:
    return bool(_c("agents").count_documents({"account_id": account_id, "webhook_ids": webhook_id}))


def delete_invitation(org_id: int, invitation_id: int) -> None:
    _c("invitations").delete_one({"_id": invitation_id, "org_id": org_id})


def rename_org(org_id: int, name: str) -> None:
    _c("organizations").update_one({"_id": org_id}, {"$set": {"name": name}})


def healthy() -> bool:
    try:
        get_db().client.admin.command("ping")
        return True
    except Exception:
        return False


def clear_pending_work() -> None:
    """Ops helper: stop all scheduled work (used by tests and maintenance)."""
    _c("followup_rules").update_many({}, {"$set": {"enabled": 0}})
    _c("jobs").update_many({}, {"$set": {"enabled": 0}})
    _c("tasks").update_many({}, {"$set": {"status": "done"}})


# ------------------------------------------------------ provider credentials


def upsert_credential(org_id: int, provider: str, encrypted_key: str, nonce: str,
                      key_hint: str, base_url: Optional[str], created_by: Optional[int]) -> dict[str, Any]:
    now = int(time.time())
    existing = _c("provider_credentials").find_one({"org_id": org_id, "provider": provider})
    fields = {
        "encrypted_key": encrypted_key, "nonce": nonce, "key_hint": key_hint,
        "base_url": base_url, "status": "active", "updated_at": now, "last_validated_at": now,
    }
    if existing is None:
        _insert("provider_credentials", org_id=org_id, provider=provider, created_by=created_by,
                created_at=now, last_used_at=None, **fields)
    else:
        _c("provider_credentials").update_one({"_id": existing["_id"]}, {"$set": fields})
    return get_credential(org_id, provider)  # type: ignore[return-value]


def get_credential(org_id: int, provider: str) -> Optional[dict[str, Any]]:
    return _out(_c("provider_credentials").find_one({"org_id": org_id, "provider": provider}))


def list_credentials(org_id: int) -> list[dict[str, Any]]:
    rows = [_out(d) for d in _c("provider_credentials").find({"org_id": org_id}).sort("provider", 1)]
    for row in rows:
        row.pop("encrypted_key", None)
        row.pop("nonce", None)
    return rows


def delete_credential(org_id: int, provider: str) -> None:
    _c("provider_credentials").delete_one({"org_id": org_id, "provider": provider})


def update_credential(org_id: int, provider: str, **fields: Any) -> None:
    allowed = {"status", "last_validated_at", "last_used_at", "base_url", "key_hint"}
    updates = {key: value for key, value in fields.items() if key in allowed}
    if updates:
        _c("provider_credentials").update_one({"org_id": org_id, "provider": provider}, {"$set": updates})


def set_org_defaults(org_id: int, provider: Optional[str], model: Optional[str]) -> None:
    _c("organizations").update_one(
        {"_id": org_id}, {"$set": {"default_provider": provider, "default_model": model}}
    )


# ------------------------------------------------------ integrations / actions


def upsert_connected_account(org_id: int, service: str, toolkit: str, external_id: Optional[str],
                             status: str, provider: str = "composio",
                             metadata: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    now = int(time.time())
    fields = {"toolkit": toolkit, "provider": provider, "external_id": external_id,
              "status": status, "metadata": metadata or {}, "updated_at": now}
    existing = _c("connected_accounts").find_one({"org_id": org_id, "service": service})
    if existing is None:
        _insert("connected_accounts", org_id=org_id, service=service, created_at=now, **fields)
    else:
        _c("connected_accounts").update_one({"_id": existing["_id"]}, {"$set": fields})
    return get_connected_account(org_id, service)  # type: ignore[return-value]


def get_connected_account(org_id: int, service: str) -> Optional[dict[str, Any]]:
    return _out(_c("connected_accounts").find_one({"org_id": org_id, "service": service}))


def list_connected_accounts(org_id: int) -> list[dict[str, Any]]:
    return [_out(d) for d in _c("connected_accounts").find({"org_id": org_id}).sort("service", 1)]


def delete_connected_account(org_id: int, service: str) -> None:
    _c("connected_accounts").delete_one({"org_id": org_id, "service": service})


def add_integration_action(org_id: int, service: str, action: str, args: dict[str, Any],
                           status: str, result: Optional[dict[str, Any]] = None,
                           error: Optional[str] = None, account_id: Optional[int] = None,
                           agent_id: Optional[int] = None, room_id: Optional[int] = None) -> int:
    return _insert(
        "integration_actions", org_id=org_id, account_id=account_id, agent_id=agent_id, room_id=room_id,
        service=service, action=action, args=args, status=status, result=result or {}, error=error,
        created_at=int(time.time()),
    )


def list_integration_actions(org_id: int, limit: int = 100) -> list[dict[str, Any]]:
    return [_out(d) for d in _c("integration_actions").find({"org_id": org_id}).sort("_id", -1).limit(limit)]


def create_pending_action(org_id: int, agent_id: int, room_id: int, lane_key: str, service: str,
                          action: str, args: dict[str, Any], token: str, expires_at: int) -> dict[str, Any]:
    ident = _insert(
        "pending_actions", org_id=org_id, agent_id=agent_id, room_id=room_id, lane_key=lane_key,
        service=service, action=action, args=args, token=token, status="pending",
        created_at=int(time.time()), expires_at=expires_at,
    )
    return _out(_c("pending_actions").find_one({"_id": ident}))


def pending_action_for_lane(agent_id: int, room_id: int, lane_key: str,
                            now: Optional[int] = None) -> Optional[dict[str, Any]]:
    moment = int(now if now is not None else time.time())
    doc = _c("pending_actions").find_one(
        {"agent_id": agent_id, "room_id": room_id, "lane_key": lane_key, "status": "pending"},
        sort=[("_id", -1)],
    )
    if doc is None:
        return None
    if int(doc["expires_at"]) < moment:
        _c("pending_actions").update_one({"_id": doc["_id"]}, {"$set": {"status": "expired"}})
        return None
    return _out(doc)


def resolve_pending_action(action_id: int, status: str) -> None:
    _c("pending_actions").update_one({"_id": action_id}, {"$set": {"status": status}})


# ------------------------------------------------------- broker credentials


def upsert_broker_credential(org_id: int, encrypted_key: str, nonce: str, key_hint: str,
                             base_url: Optional[str], auth_configs: dict[str, str],
                             provider: str = "composio") -> dict[str, Any]:
    now = int(time.time())
    fields = {
        "provider": provider, "encrypted_key": encrypted_key, "nonce": nonce, "key_hint": key_hint,
        "base_url": base_url, "auth_configs": auth_configs, "status": "active", "updated_at": now,
    }
    existing = _c("broker_credentials").find_one({"org_id": org_id})
    if existing is None:
        _insert("broker_credentials", org_id=org_id, created_at=now, **fields)
    else:
        _c("broker_credentials").update_one({"_id": existing["_id"]}, {"$set": fields})
    return get_broker_credential(org_id)  # type: ignore[return-value]


def get_broker_credential(org_id: int) -> Optional[dict[str, Any]]:
    return _out(_c("broker_credentials").find_one({"org_id": org_id}))


def update_broker_auth_configs(org_id: int, auth_configs: dict[str, str]) -> None:
    _c("broker_credentials").update_one(
        {"org_id": org_id}, {"$set": {"auth_configs": auth_configs, "updated_at": int(time.time())}}
    )


def delete_broker_credential(org_id: int) -> None:
    _c("broker_credentials").delete_one({"org_id": org_id})


# ------------------------------------------------------------ platform admin


def add_superadmin(pid: int) -> None:
    _c("platform_admins").update_one(
        {"_id": pid}, {"$setOnInsert": {"created_at": int(time.time())}}, upsert=True
    )


def is_superadmin(pid: int) -> bool:
    return bool(_c("platform_admins").find_one({"_id": pid}))


def list_orgs() -> list[dict[str, Any]]:
    return [_out(d) for d in _c("organizations").find().sort("_id", 1)]


def add_admin_audit(actor_pid: int, org_id: Optional[int], action: str, detail: Optional[dict[str, Any]] = None) -> int:
    return _insert(
        "admin_audit", actor_pid=actor_pid, org_id=org_id, action=action,
        detail=detail or {}, created_at=int(time.time()),
    )


def list_admin_audit(limit: int = 100) -> list[dict[str, Any]]:
    return [_out(d) for d in _c("admin_audit").find().sort("_id", -1).limit(limit)]


def count_agents_for_org(org_id: int) -> int:
    accounts = [int(row["id"]) for row in list_org_accounts(org_id)]
    if not accounts:
        return 0
    return int(_c("agents").count_documents({"account_id": {"$in": accounts}}))


def last_message_at_for_org(org_id: int) -> int:
    accounts = [int(row["id"]) for row in list_org_accounts(org_id)]
    if not accounts:
        return 0
    doc = _c("messages").find_one({"account_id": {"$in": accounts}}, sort=[("ts", -1)])
    return int(doc["ts"]) if doc else 0


def session_create_full(token: str, pid: int, expires_at: int, emulated_org_id: Optional[int] = None) -> None:
    _c("sessions").replace_one(
        {"_id": token},
        {"_id": token, "partner_pid": pid, "emulated_org_id": emulated_org_id, "expires_at": expires_at},
        upsert=True,
    )
