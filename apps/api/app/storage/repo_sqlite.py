"""Data access. All JSON columns are (de)serialised here so services stay clean."""
from __future__ import annotations

import json
import time
from typing import Any, Iterable, Optional

from ..db import db


def _loads(value: Any, fallback: Any) -> Any:
    if value is None or value == "":
        return fallback
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


# --------------------------------------------------------------------------- accounts


def list_accounts(pid: int) -> list[dict[str, Any]]:
    return db.query("SELECT * FROM accounts WHERE partner_pid=? ORDER BY id", (pid,))


def get_account(pid: int, account_id: int) -> dict[str, Any]:
    row = db.one("SELECT * FROM accounts WHERE id=? AND partner_pid=?", (account_id, pid))
    if row is None:
        raise KeyError("account not found")
    return row


def default_account(pid: int) -> dict[str, Any]:
    row = db.one("SELECT * FROM accounts WHERE partner_pid=? ORDER BY id LIMIT 1", (pid,))
    if row is None:
        raise KeyError("no account for partner")
    return row


# ------------------------------------------------------------------------------ rooms


def list_rooms(account_id: int) -> list[dict[str, Any]]:
    return db.query("SELECT * FROM rooms WHERE account_id=? ORDER BY last_activity_at DESC, id", (account_id,))


def get_room(account_id: int, room_id: int) -> dict[str, Any]:
    row = db.one("SELECT * FROM rooms WHERE id=? AND account_id=?", (room_id, account_id))
    if row is None:
        raise KeyError("room not found")
    return row


def ensure_room(account_id: int, external_id: str, kind: str = "dm", display_name: str = "") -> dict[str, Any]:
    row = db.one("SELECT * FROM rooms WHERE account_id=? AND external_id=?", (account_id, external_id))
    if row is not None:
        return row
    db.execute(
        "INSERT INTO rooms(account_id, external_id, kind, display_name, last_activity_at) VALUES(?,?,?,?,?)",
        (account_id, external_id, kind, display_name, int(time.time())),
    )
    return db.one("SELECT * FROM rooms WHERE account_id=? AND external_id=?", (account_id, external_id))  # type: ignore[return-value]


def ensure_system_room(account_id: int) -> dict[str, Any]:
    """The partner's own thread with the assistant: OTPs, link events, alerts."""
    return ensure_room(account_id, "system", "system", "Assistant")


def system_room(account_id: int) -> dict[str, Any] | None:
    return db.one("SELECT * FROM rooms WHERE account_id=? AND kind='system' LIMIT 1", (account_id,))


def set_exclusion(account_id: int, room_id: int, excluded: bool) -> None:
    db.execute("UPDATE rooms SET is_excluded=? WHERE id=? AND account_id=?", (1 if excluded else 0, room_id, account_id))


# --------------------------------------------------------------------------- messages


def add_message(
    account_id: int,
    room_id: int,
    direction: str,
    text: str,
    *,
    sender: str = "",
    sender_name: str = "",
    ts: Optional[int] = None,
    media: Optional[list[dict[str, Any]]] = None,
    status: str = "delivered",
    source: str = "whatsapp",
    agent_id: Optional[int] = None,
    run_id: Optional[int] = None,
) -> dict[str, Any]:
    now = int(ts if ts is not None else time.time())
    mid = db.execute(
        "INSERT INTO messages(account_id, room_id, direction, sender, sender_name, text, media_json, ts, status, source, agent_id, run_id) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (account_id, room_id, direction, sender, sender_name, text, _dumps(media or []), now, status, source, agent_id, run_id),
    )
    db.execute("UPDATE rooms SET last_activity_at=? WHERE id=?", (now, room_id))
    return db.one("SELECT * FROM messages WHERE id=?", (mid,))  # type: ignore[return-value]


def list_messages(room_id: int, *, limit: int = 50, before_ts: Optional[int] = None) -> list[dict[str, Any]]:
    if before_ts is None:
        rows = db.query("SELECT * FROM messages WHERE room_id=? ORDER BY ts DESC, id DESC LIMIT ?", (room_id, limit))
    else:
        rows = db.query(
            "SELECT * FROM messages WHERE room_id=? AND ts<=? ORDER BY ts DESC, id DESC LIMIT ?",
            (room_id, before_ts, limit),
        )
    for row in rows:
        row["media"] = _loads(row.pop("media_json", "[]"), [])
    return rows


def history(room_id: int, limit: int) -> list[dict[str, Any]]:
    rows = list_messages(room_id, limit=limit)
    return list(reversed(rows))


def last_message_at(room_id: int, direction: str) -> int:
    return int(db.scalar(
        "SELECT MAX(ts) FROM messages WHERE room_id=? AND direction=?", (room_id, direction), default=0
    ) or 0)


def last_message(room_id: int, direction: str) -> Optional[dict[str, Any]]:
    return db.one(
        "SELECT * FROM messages WHERE room_id=? AND direction=? ORDER BY ts DESC, id DESC LIMIT 1",
        (room_id, direction),
    )


# ----------------------------------------------------------------------------- agents


def _agent(row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    row["excluded_room_ids"] = _loads(row.pop("excluded_rooms_json", "[]"), [])
    row["capabilities"] = _loads(row.pop("capabilities_json", '["read","send"]'), ["read", "send"])
    row["tool_suites"] = _loads(row.pop("tool_suites_json", "[]"), [])
    row["webhook_ids"] = _loads(row.pop("webhook_ids_json", "[]"), [])
    return row


def list_agents(account_id: int, include_paused: bool = True) -> list[dict[str, Any]]:
    if include_paused:
        rows = db.query("SELECT * FROM agents WHERE account_id=? ORDER BY id", (account_id,))
    else:
        rows = db.query("SELECT * FROM agents WHERE account_id=? AND status='active' ORDER BY id", (account_id,))
    return [_agent(r) for r in rows]


def get_agent(account_id: int, agent_id: int) -> dict[str, Any]:
    row = db.one("SELECT * FROM agents WHERE id=? AND account_id=?", (agent_id, account_id))
    if row is None:
        raise KeyError("agent not found")
    return _agent(row)


def create_agent(account_id: int, body: dict[str, Any]) -> dict[str, Any]:
    agent_id = db.execute(
        "INSERT INTO agents(account_id, name, system_prompt, trigger_type, trigger_scope, trigger_condition, room_id, "
        "chat_type, excluded_rooms_json, capabilities_json, tool_suites_json, webhook_ids_json, llm_provider, llm_model, "
        "recurrence_cron, timezone, max_iterations, timeout_seconds, max_memory_chars, created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            account_id,
            body["name"],
            body["system_prompt"],
            body.get("trigger_type", "event"),
            body.get("trigger_scope", "room"),
            body.get("trigger_condition"),
            body.get("room_id"),
            body.get("chat_type", "all"),
            _dumps(body.get("excluded_room_ids", [])),
            _dumps(body.get("capabilities", ["read", "send"])),
            _dumps(body.get("tool_suites", [])),
            _dumps(body.get("webhook_ids", [])),
            body.get("llm_provider"),
            body.get("llm_model"),
            body.get("recurrence_cron"),
            body.get("timezone", "Asia/Kolkata"),
            body.get("max_iterations", 6),
            body.get("timeout_seconds", 60),
            body.get("max_memory_chars", 4000),
            int(time.time()),
        ),
    )
    return get_agent(account_id, agent_id)


_AGENT_JSON_COLUMNS = {
    "excluded_room_ids": "excluded_rooms_json",
    "capabilities": "capabilities_json",
    "tool_suites": "tool_suites_json",
    "webhook_ids": "webhook_ids_json",
}


def update_agent(account_id: int, agent_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    current = get_agent(account_id, agent_id)
    fields: list[str] = []
    params: list[Any] = []
    for key, value in patch.items():
        if value is None:
            continue
        column = _AGENT_JSON_COLUMNS.get(key, key)
        if key in _AGENT_JSON_COLUMNS:
            value = _dumps(value)
        if key not in current and column not in current:
            continue
        fields.append(f"{column}=?")
        params.append(value)
    if fields:
        params.extend([agent_id, account_id])
        db.execute(f"UPDATE agents SET {', '.join(fields)} WHERE id=? AND account_id=?", params)
    return get_agent(account_id, agent_id)


def toggle_agent(account_id: int, agent_id: int) -> dict[str, Any]:
    agent = get_agent(account_id, agent_id)
    status = "paused" if agent["status"] == "active" else "active"
    db.execute("UPDATE agents SET status=? WHERE id=? AND account_id=?", (status, agent_id, account_id))
    return get_agent(account_id, agent_id)


# ------------------------------------------------------------------------------ lanes


def get_lane(agent_id: int, room_id: int, lane_key: str = "main") -> dict[str, Any]:
    row = db.one("SELECT * FROM lanes WHERE agent_id=? AND room_id=? AND lane_key=?", (agent_id, room_id, lane_key))
    if row is None:
        db.execute(
            "INSERT INTO lanes(agent_id, room_id, lane_key) VALUES(?,?,?)", (agent_id, room_id, lane_key)
        )
        row = db.one("SELECT * FROM lanes WHERE agent_id=? AND room_id=? AND lane_key=?", (agent_id, room_id, lane_key))
    assert row is not None
    row["pending_steps"] = _loads(row.get("pending_steps"), [])
    return row


def list_lanes(agent_id: int) -> list[dict[str, Any]]:
    return db.query(
        "SELECT l.*, r.display_name AS room_name FROM lanes l JOIN rooms r ON r.id=l.room_id "
        "WHERE l.agent_id=? ORDER BY l.last_run_at DESC",
        (agent_id,),
    )


def reset_lane(agent_id: int, room_id: int, lane_key: str) -> None:
    db.execute(
        "UPDATE lanes SET session_memory='', pending_steps='[]' WHERE agent_id=? AND room_id=? AND lane_key=?",
        (agent_id, room_id, lane_key),
    )


def set_handover(agent_id: int, room_id: int, handed_over: bool, lane_key: str = "main") -> None:
    get_lane(agent_id, room_id, lane_key)
    db.execute(
        "UPDATE lanes SET handed_over=? WHERE agent_id=? AND room_id=? AND lane_key=?",
        (1 if handed_over else 0, agent_id, room_id, lane_key),
    )


def touch_lane(agent_id: int, room_id: int, lane_key: str = "main") -> None:
    db.execute(
        "UPDATE lanes SET last_run_at=? WHERE agent_id=? AND room_id=? AND lane_key=?",
        (int(time.time()), agent_id, room_id, lane_key),
    )


# ----------------------------------------------------------------------------- memory


def list_memory(agent_id: int) -> list[dict[str, Any]]:
    return db.query("SELECT key, value FROM memory WHERE agent_id=? ORDER BY key", (agent_id,))


def memory_block(agent_id: int, limit_chars: int) -> str:
    rows = list_memory(agent_id)
    lines = [f"{r['key']}: {r['value']}" for r in rows]
    text = "\n".join(lines)
    return text[-limit_chars:] if len(text) > limit_chars else text


def set_memory(agent_id: int, key: str, value: str) -> None:
    db.execute(
        "INSERT INTO memory(agent_id, key, value) VALUES(?,?,?) "
        "ON CONFLICT(agent_id, key) DO UPDATE SET value=excluded.value",
        (agent_id, key, value),
    )


def delete_memory(agent_id: int, key: str) -> bool:
    row = db.one("SELECT id FROM memory WHERE agent_id=? AND key=?", (agent_id, key))
    if row is None:
        return False
    db.execute("DELETE FROM memory WHERE id=?", (row["id"],))
    return True


# ------------------------------------------------------------------------------- runs


def create_run(agent_id: int, account_id: int, room_id: Optional[int], trigger: str, lane: str = "main") -> int:
    return db.execute(
        "INSERT INTO runs(agent_id, account_id, room_id, trigger, lane, started_at) VALUES(?,?,?,?,?,?)",
        (agent_id, account_id, room_id, trigger, lane, int(time.time())),
    )


def finish_run(run_id: int, *, status: str, stage: str, iterations: int, tokens: int, reply: str,
               reason: Optional[str] = None, provider: Optional[str] = None, model: Optional[str] = None,
               tool_calls: Optional[list[dict[str, Any]]] = None) -> None:
    db.execute(
        "UPDATE runs SET status=?, stage=?, iterations=?, tokens=?, reply=?, reason=?, "
        "llm_provider=?, llm_model=?, tool_calls_json=?, finished_at=? WHERE id=?",
        (status, stage, iterations, tokens, reply, reason, provider, model,
         _dumps(tool_calls or []), int(time.time()), run_id),
    )


def list_runs(account_id: int, agent_id: Optional[int] = None, limit: int = 50) -> list[dict[str, Any]]:
    if agent_id is None:
        rows = db.query("SELECT * FROM runs WHERE account_id=? ORDER BY id DESC LIMIT ?", (account_id, limit))
    else:
        rows = db.query(
            "SELECT * FROM runs WHERE account_id=? AND agent_id=? ORDER BY id DESC LIMIT ?",
            (account_id, agent_id, limit),
        )
    for row in rows:
        row["tool_calls"] = _loads(row.pop("tool_calls_json", "[]"), [])
    return rows


# --------------------------------------------------------------------------- webhooks


def _webhook(row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    row["headers"] = _loads(row.pop("headers_json", "[]"), [])
    row["body_fields"] = _loads(row.pop("body_fields_json", "[]"), [])
    # secrets never leave the server
    for header in row["headers"]:
        if header.get("secret"):
            header["value"] = None
    for field in row["body_fields"]:
        if field.get("secret"):
            field["value"] = None
    return row


def list_webhooks(account_id: int) -> list[dict[str, Any]]:
    return [_webhook(r) for r in db.query("SELECT * FROM webhooks WHERE account_id=? ORDER BY id", (account_id,))]


def get_webhook(account_id: int, webhook_id: int) -> dict[str, Any]:
    row = db.one("SELECT * FROM webhooks WHERE id=? AND account_id=?", (webhook_id, account_id))
    if row is None:
        raise KeyError("webhook not found")
    return _webhook(row)


def raw_webhook(account_id: int, webhook_id: int) -> dict[str, Any]:
    """Internal read that keeps secret values (never serialise this to a client)."""
    row = db.one("SELECT * FROM webhooks WHERE id=? AND account_id=?", (webhook_id, account_id))
    if row is None:
        raise KeyError("webhook not found")
    raw = dict(row)
    raw["headers"] = _loads(raw.pop("headers_json", "[]"), [])
    raw["body_fields"] = _loads(raw.pop("body_fields_json", "[]"), [])
    return raw


def create_webhook(account_id: int, body: dict[str, Any]) -> dict[str, Any]:
    webhook_id = db.execute(
        "INSERT INTO webhooks(account_id, name, description, url, method, headers_json, body_fields_json, created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (
            account_id,
            body["name"],
            body.get("description", ""),
            body["url"],
            body.get("method", "POST"),
            _dumps(body.get("headers", [])),
            _dumps(body.get("body_fields", [])),
            int(time.time()),
        ),
    )
    return get_webhook(account_id, webhook_id)


def update_webhook(account_id: int, webhook_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    raw = raw_webhook(account_id, webhook_id)
    mapping = {"headers": "headers_json", "body_fields": "body_fields_json"}
    fields: list[str] = []
    params: list[Any] = []
    for key, value in patch.items():
        if value is None:
            continue
        column = mapping.get(key, key)
        if key in mapping:
            merged = _merge_write_only(raw[key], value)
            value = _dumps(merged)
        if column not in raw:
            continue
        fields.append(f"{column}=?")
        params.append(int(value) if key == "active" else value)
    if fields:
        params.extend([webhook_id, account_id])
        db.execute(f"UPDATE webhooks SET {', '.join(fields)} WHERE id=? AND account_id=?", params)
    return get_webhook(account_id, webhook_id)


def _merge_write_only(current: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A secret sent as null keeps the stored value (observed Loop2 behaviour)."""
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
    in_use = db.scalar(
        "SELECT COUNT(*) FROM agents WHERE account_id=? AND webhook_ids_json LIKE ?",
        (account_id, f"%{webhook_id}%"),
        default=0,
    )
    if in_use:
        raise ValueError("webhook_in_use")
    db.execute("DELETE FROM webhooks WHERE id=? AND account_id=?", (webhook_id, account_id))


def add_delivery(webhook_id: int, account_id: int, trigger: str, status_code: Optional[int], duration_ms: int, error: Optional[str]) -> int:
    return db.execute(
        "INSERT INTO deliveries(webhook_id, account_id, trigger, status_code, duration_ms, error, created_at) VALUES(?,?,?,?,?,?,?)",
        (webhook_id, account_id, trigger, status_code, duration_ms, error, int(time.time())),
    )


def list_deliveries(account_id: int, webhook_id: int, limit: int = 50) -> list[dict[str, Any]]:
    return db.query(
        "SELECT * FROM deliveries WHERE account_id=? AND webhook_id=? ORDER BY id DESC LIMIT ?",
        (account_id, webhook_id, limit),
    )


# -------------------------------------------------------------------------- knowledge


def list_sources(account_id: int) -> list[dict[str, Any]]:
    return db.query("SELECT * FROM knowledge_sources WHERE account_id=? ORDER BY id", (account_id,))


def create_source(account_id: int, body: dict[str, Any]) -> dict[str, Any]:
    source_id = db.execute(
        "INSERT INTO knowledge_sources(account_id, name, source_room_id, source_type, extraction_instruction, created_at) "
        "VALUES(?,?,?,?,?,?)",
        (
            account_id,
            body["name"],
            body["source_room_id"],
            body.get("source_type", "whatsapp_room"),
            body.get("extraction_instruction", ""),
            int(time.time()),
        ),
    )
    return db.one("SELECT * FROM knowledge_sources WHERE id=?", (source_id,))  # type: ignore[return-value]


def list_entries(source_id: int) -> list[dict[str, Any]]:
    rows = db.query("SELECT * FROM knowledge_entries WHERE source_id=? ORDER BY id", (source_id,))
    for row in rows:
        row["keys"] = _loads(row.pop("keys_json", "[]"), [])
        row["medias"] = _loads(row.pop("medias_json", "[]"), [])
        row["metadata"] = _loads(row.pop("metadata_json", "{}"), {})
    return rows


def create_entry(source_id: int, body: dict[str, Any]) -> dict[str, Any]:
    entry_id = db.execute(
        "INSERT INTO knowledge_entries(source_id, keys_json, title, content, medias_json, metadata_json) VALUES(?,?,?,?,?,?)",
        (
            source_id,
            _dumps(body.get("keys", [])),
            body.get("title", ""),
            body.get("content", ""),
            _dumps(body.get("medias", [])),
            _dumps(body.get("metadata", {})),
        ),
    )
    rows = [r for r in list_entries(source_id) if r["id"] == entry_id]
    return rows[0]


def all_entries(account_id: int) -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT e.*, s.name AS source_name FROM knowledge_entries e "
        "JOIN knowledge_sources s ON s.id=e.source_id WHERE s.account_id=? ORDER BY e.id",
        (account_id,),
    )
    for row in rows:
        row["keys"] = _loads(row.pop("keys_json", "[]"), [])
        row["medias"] = _loads(row.pop("medias_json", "[]"), [])
        row["metadata"] = _loads(row.pop("metadata_json", "{}"), {})
    return rows


def set_agent_knowledge(agent_id: int, source_ids: list[int]) -> None:
    db.execute("DELETE FROM agent_knowledge WHERE agent_id=?", (agent_id,))
    db.executemany(
        "INSERT OR IGNORE INTO agent_knowledge(agent_id, source_id) VALUES(?,?)",
        [(agent_id, source_id) for source_id in source_ids],
    )


def agent_knowledge_sources(agent_id: int) -> list[dict[str, Any]]:
    return db.query(
        "SELECT s.* FROM knowledge_sources s JOIN agent_knowledge ak ON ak.source_id=s.id "
        "WHERE ak.agent_id=? ORDER BY s.id",
        (agent_id,),
    )


def agent_knowledge_ids(agent_id: int) -> list[int]:
    return [int(r["source_id"]) for r in db.query(
        "SELECT source_id FROM agent_knowledge WHERE agent_id=?", (agent_id,)
    )]


# ------------------------------------------------------------------- scheduling / jobs


def create_job(account_id: int, context: dict[str, Any], rrule: str, dtstart_local: str, until_local: Optional[str], next_run_at: int) -> dict[str, Any]:
    job_id = db.execute(
        "INSERT INTO jobs(account_id, context_json, rrule, dtstart_local, until_local, next_run_at) VALUES(?,?,?,?,?,?)",
        (account_id, _dumps(context), rrule, dtstart_local, until_local, next_run_at),
    )
    return db.one("SELECT * FROM jobs WHERE id=?", (job_id,))  # type: ignore[return-value]


def list_jobs(account_id: int) -> list[dict[str, Any]]:
    rows = db.query("SELECT * FROM jobs WHERE account_id=? ORDER BY id", (account_id,))
    for row in rows:
        row["context"] = _loads(row.pop("context_json", "{}"), {})
    return rows


def due_jobs(now: int) -> list[dict[str, Any]]:
    rows = db.query("SELECT * FROM jobs WHERE enabled=1 AND next_run_at IS NOT NULL AND next_run_at<=?", (now,))
    for row in rows:
        row["context"] = _loads(row.pop("context_json", "{}"), {})
    return rows


def update_job(job_id: int, **fields: Any) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    db.execute(f"UPDATE jobs SET {sets} WHERE id=?", (*fields.values(), job_id))


def create_task(account_id: int, context: dict[str, Any], execute_after_at: int) -> dict[str, Any]:
    task_id = db.execute(
        "INSERT INTO tasks(account_id, context_json, execute_after_at) VALUES(?,?,?)",
        (account_id, _dumps(context), execute_after_at),
    )
    return db.one("SELECT * FROM tasks WHERE id=?", (task_id,))  # type: ignore[return-value]


def list_tasks(account_id: int) -> list[dict[str, Any]]:
    rows = db.query("SELECT * FROM tasks WHERE account_id=? ORDER BY id", (account_id,))
    for row in rows:
        row["context"] = _loads(row.pop("context_json", "{}"), {})
    return rows


def due_tasks(now: int) -> list[dict[str, Any]]:
    rows = db.query("SELECT * FROM tasks WHERE status='pending' AND execute_after_at<=?", (now,))
    for row in rows:
        row["context"] = _loads(row.pop("context_json", "{}"), {})
    return rows


# -------------------------------------------------------------------------- followups


def get_followup_rules(agent_id: int) -> dict[str, Any]:
    row = db.one("SELECT * FROM followup_rules WHERE scope='agent' AND ref_id=?", (agent_id,))
    if row is None:
        return {"enabled": False, "rules": [], "send_window": None}
    return {
        "enabled": bool(row["enabled"]),
        "rules": _loads(row["rules_json"], []),
        "send_window": _loads(row["window_json"], None),
    }


def put_followup_rules(account_id: int, agent_id: int, body: dict[str, Any]) -> dict[str, Any]:
    row = db.one("SELECT id FROM followup_rules WHERE scope='agent' AND ref_id=?", (agent_id,))
    rules = body.get("rules", [])
    for index, rule in enumerate(rules):
        rule.setdefault("id", f"r{index + 1}")
    payload = (
        account_id,
        1 if body.get("enabled", True) else 0,
        _dumps(rules),
        _dumps(body.get("send_window") or {}),
    )
    if row is None:
        db.execute(
            "INSERT INTO followup_rules(account_id, scope, ref_id, enabled, rules_json, window_json) VALUES(?,?,?,?,?,?)",
            (account_id, "agent", agent_id, payload[1], payload[2], payload[3]),
        )
    else:
        db.execute(
            "UPDATE followup_rules SET enabled=?, rules_json=?, window_json=? WHERE id=?",
            (payload[1], payload[2], payload[3], row["id"]),
        )
    return get_followup_rules(agent_id)


def enabled_followup_rules() -> list[dict[str, Any]]:
    rows = db.query("SELECT * FROM followup_rules WHERE enabled=1 AND scope='agent'")
    for row in rows:
        row["rules"] = _loads(row["rules_json"], [])
        row["window"] = _loads(row["window_json"], {})
    return rows


def followup_already_sent(rule_id: int, room_id: int, rule_key: str) -> bool:
    return bool(db.scalar(
        "SELECT COUNT(*) FROM followup_runs WHERE rule_id=? AND room_id=? AND rule_key=? AND status='sent'",
        (rule_id, room_id, rule_key),
        default=0,
    ))


def record_followup(rule_id: int, room_id: int, rule_key: str, due_at: int, status: str) -> int:
    return db.execute(
        "INSERT INTO followup_runs(rule_id, room_id, rule_key, due_at, sent_at, status) VALUES(?,?,?,?,?,?)",
        (rule_id, room_id, rule_key, due_at, int(time.time()) if status == "sent" else None, status),
    )


def list_followup_runs(agent_id: int, limit: int = 50) -> list[dict[str, Any]]:
    return db.query(
        "SELECT fr.* FROM followup_runs fr JOIN followup_rules r ON r.id=fr.rule_id "
        "WHERE r.scope='agent' AND r.ref_id=? ORDER BY fr.id DESC LIMIT ?",
        (agent_id, limit),
    )


# --------------------------------------------------------------------------- settings


def human_pause_enabled(account_id: int) -> bool:
    row = db.one("SELECT human_active_pause FROM settings WHERE account_id=?", (account_id,))
    return True if row is None else bool(row["human_active_pause"])


def set_human_pause(account_id: int, enabled: bool) -> None:
    db.execute(
        "INSERT INTO settings(account_id, human_active_pause) VALUES(?,?) "
        "ON CONFLICT(account_id) DO UPDATE SET human_active_pause=excluded.human_active_pause",
        (account_id, 1 if enabled else 0),
    )


def owner_spoke_recently(account_id: int, room_id: int, within_seconds: int) -> bool:
    cutoff = int(time.time()) - within_seconds
    return bool(db.scalar(
        "SELECT COUNT(*) FROM messages WHERE account_id=? AND room_id=? AND source='owner' AND ts>=?",
        (account_id, room_id, cutoff),
        default=0,
    ))


# ----------------------------------------------------------------------------- outbox


def enqueue_outbox(account_id: int, room_id: int, text: str, media: Optional[list[dict[str, Any]]] = None,
                   message_id: Optional[int] = None) -> int:
    return db.execute(
        "INSERT INTO outbox(account_id, room_id, message_id, text, media_json, created_at) VALUES(?,?,?,?,?,?)",
        (account_id, room_id, message_id, text, _dumps(media or []), int(time.time())),
    )


def queued_outbox(limit: int = 20) -> list[dict[str, Any]]:
    rows = db.query("SELECT * FROM outbox WHERE status='queued' ORDER BY id LIMIT ?", (limit,))
    for row in rows:
        row["media"] = _loads(row.pop("media_json", "[]"), [])
    return rows


def mark_outbox(outbox_id: int, status: str, error: Optional[str] = None, message_id: Optional[int] = None) -> None:
    db.execute(
        "UPDATE outbox SET status=?, error=?, sent_at=? WHERE id=?",
        (status, error, int(time.time()) if status == "sent" else None, outbox_id),
    )
    if message_id is not None:
        db.execute(
            "UPDATE messages SET status=? WHERE id=?",
            ("delivered" if status == "sent" else "failed", message_id),
        )


# ------------------------------------------------------------------- organizations


def create_org(owner_pid: int, name: str, slug: str) -> dict[str, Any]:
    org_id = db.execute(
        "INSERT INTO organizations(name, slug, owner_pid, created_at) VALUES(?,?,?,?)",
        (name, slug, owner_pid, int(time.time())),
    )
    add_membership(org_id, owner_pid, "owner")
    return get_org(org_id)


def get_org(org_id: int) -> dict[str, Any]:
    row = db.one("SELECT * FROM organizations WHERE id=?", (org_id,))
    if row is None:
        raise KeyError("org not found")
    return row


def orgs_for_partner(pid: int) -> list[dict[str, Any]]:
    return db.query(
        "SELECT o.*, m.role FROM organizations o JOIN memberships m ON m.org_id=o.id "
        "WHERE m.pid=? ORDER BY o.id",
        (pid,),
    )


def first_org_for_partner(pid: int) -> dict[str, Any] | None:
    row = db.one(
        "SELECT o.*, m.role FROM organizations o JOIN memberships m ON m.org_id=o.id "
        "WHERE m.pid=? ORDER BY o.id LIMIT 1",
        (pid,),
    )
    return row


def add_membership(org_id: int, pid: int, role: str = "member") -> None:
    db.execute(
        "INSERT INTO memberships(org_id, pid, role, created_at) VALUES(?,?,?,?) "
        "ON CONFLICT(org_id, pid) DO UPDATE SET role=excluded.role",
        (org_id, pid, role, int(time.time())),
    )


def membership(org_id: int, pid: int) -> dict[str, Any] | None:
    return db.one("SELECT * FROM memberships WHERE org_id=? AND pid=?", (org_id, pid))


def list_memberships(org_id: int) -> list[dict[str, Any]]:
    return db.query(
        "SELECT m.org_id, m.pid, m.role, m.created_at, p.name, p.phone "
        "FROM memberships m JOIN partners p ON p.pid=m.pid WHERE m.org_id=? ORDER BY m.id",
        (org_id,),
    )


def count_memberships(org_id: int) -> int:
    return int(db.scalar("SELECT COUNT(*) FROM memberships WHERE org_id=?", (org_id,), default=0))


def set_membership_role(org_id: int, pid: int, role: str) -> None:
    db.execute("UPDATE memberships SET role=? WHERE org_id=? AND pid=?", (role, org_id, pid))


def remove_membership(org_id: int, pid: int) -> None:
    db.execute("DELETE FROM memberships WHERE org_id=? AND pid=?", (org_id, pid))


def create_invitation(org_id: int, phone: str, role: str, token: str, invited_by: int, expires_at: int) -> dict[str, Any]:
    invite_id = db.execute(
        "INSERT INTO invitations(org_id, phone, role, token, invited_by, created_at, expires_at) VALUES(?,?,?,?,?,?,?)",
        (org_id, phone, role, token, invited_by, int(time.time()), expires_at),
    )
    return db.one("SELECT * FROM invitations WHERE id=?", (invite_id,))  # type: ignore[return-value]


def list_invitations(org_id: int, pending_only: bool = True) -> list[dict[str, Any]]:
    sql = "SELECT * FROM invitations WHERE org_id=?"
    if pending_only:
        sql += " AND accepted_at IS NULL AND declined_at IS NULL AND expires_at>=?"
        return db.query(sql + " ORDER BY id DESC", (org_id, int(time.time())))
    return db.query(sql + " ORDER BY id DESC", (org_id,))


def invitation_by_token(token: str) -> dict[str, Any] | None:
    return db.one("SELECT * FROM invitations WHERE token=?", (token,))


def accept_invitation(invite_id: int) -> None:
    db.execute("UPDATE invitations SET accepted_at=? WHERE id=?", (int(time.time()), invite_id))


def decline_invitation(invite_id: int) -> None:
    db.execute("UPDATE invitations SET declined_at=? WHERE id=?", (int(time.time()), invite_id))


def invitations_for_phone(phone: str) -> list[dict[str, Any]]:
    return db.query(
        "SELECT * FROM invitations WHERE phone=? AND accepted_at IS NULL AND declined_at IS NULL AND expires_at>=?",
        (phone, int(time.time())),
    )


# ------------------------------------------------------------------- org accounts


def create_account(org_id: int, partner_pid: int, name: str, timezone: str) -> dict[str, Any]:
    account_id = db.execute(
        "INSERT INTO accounts(partner_pid, org_id, name, timezone, created_at) VALUES(?,?,?,?,?)",
        (partner_pid, org_id, name, timezone, int(time.time())),
    )
    return db.one("SELECT * FROM accounts WHERE id=?", (account_id,))  # type: ignore[return-value]


def list_org_accounts(org_id: int) -> list[dict[str, Any]]:
    return db.query("SELECT * FROM accounts WHERE org_id=? ORDER BY id", (org_id,))


def count_org_accounts(org_id: int) -> int:
    return int(db.scalar("SELECT COUNT(*) FROM accounts WHERE org_id=?", (org_id,), default=0))


# ----------------------------------------------------------------- subscriptions


def get_subscription(org_id: int) -> dict[str, Any] | None:
    return db.one("SELECT * FROM subscriptions WHERE org_id=?", (org_id,))


def upsert_subscription(
    org_id: int,
    plan_id: str,
    status: str,
    period_start: int,
    period_end: int,
    *,
    provider: str = "manual",
    provider_ref: str | None = None,
    cancel_at_period_end: bool = False,
) -> dict[str, Any]:
    now = int(time.time())
    db.execute(
        "INSERT INTO subscriptions(org_id, plan_id, status, current_period_start, current_period_end, "
        "cancel_at_period_end, provider, provider_ref, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(org_id) DO UPDATE SET plan_id=excluded.plan_id, status=excluded.status, "
        "current_period_start=excluded.current_period_start, current_period_end=excluded.current_period_end, "
        "cancel_at_period_end=excluded.cancel_at_period_end, provider=excluded.provider, "
        "provider_ref=excluded.provider_ref, updated_at=excluded.updated_at",
        (org_id, plan_id, status, period_start, period_end, 1 if cancel_at_period_end else 0,
         provider, provider_ref, now, now),
    )
    return get_subscription(org_id)  # type: ignore[return-value]


# ------------------------------------------------------------------------ usage


def add_usage(org_id: int, metric: str, quantity: int = 1, ref: str | None = None) -> None:
    db.execute(
        "INSERT INTO usage_events(org_id, metric, quantity, ts, ref) VALUES(?,?,?,?,?)",
        (org_id, metric, quantity, int(time.time()), ref),
    )


def usage_since(org_id: int, metric: str, since: int) -> int:
    return int(db.scalar(
        "SELECT COALESCE(SUM(quantity),0) FROM usage_events WHERE org_id=? AND metric=? AND ts>=?",
        (org_id, metric, since),
        default=0,
    ))


def plan_row(plan_id: str) -> dict[str, Any] | None:
    return db.one("SELECT * FROM plans WHERE id=?", (plan_id,))


def list_plan_rows() -> list[dict[str, Any]]:
    return db.query("SELECT * FROM plans ORDER BY sort_order, price_inr")


def upsert_plan(plan: dict[str, Any]) -> None:
    db.execute(
        "INSERT INTO plans(id, name, price_inr, period, tagline, features_json, limits_json, lookup_key, "
        "recommended, sort_order) VALUES(?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, price_inr=excluded.price_inr, period=excluded.period, "
        "tagline=excluded.tagline, features_json=excluded.features_json, limits_json=excluded.limits_json, "
        "lookup_key=excluded.lookup_key, recommended=excluded.recommended, sort_order=excluded.sort_order",
        (
            plan["id"], plan["name"], plan["price_inr"], plan["period"], plan["tagline"],
            _dumps(plan["features"]), _dumps(plan["limits"]), plan["lookup_key"],
            1 if plan.get("recommended") else 0, plan.get("sort_order", 0),
        ),
    )


# ------------------------------------------------------------ auth / identity


def partner_by_phone(phone: str) -> dict[str, Any] | None:
    return db.one("SELECT * FROM partners WHERE phone=?", (phone,))


def partner(pid: int) -> dict[str, Any] | None:
    return db.one("SELECT * FROM partners WHERE pid=?", (pid,))


def create_partner(phone: str, name: str) -> int:
    return db.execute(
        "INSERT INTO partners(phone, name, created_at) VALUES(?,?,?)", (phone, name, int(time.time()))
    )


def set_wa_linked(pid: int, linked: bool) -> None:
    db.execute("UPDATE partners SET wa_linked=? WHERE pid=?", (1 if linked else 0, pid))


def count_partners() -> int:
    return int(db.scalar("SELECT COUNT(*) FROM partners", default=0))


def otp_upsert(phone: str, code: str, expires_at: int) -> None:
    db.execute(
        "INSERT INTO otps(phone, code, expires_at, attempts) VALUES(?,?,?,0) "
        "ON CONFLICT(phone) DO UPDATE SET code=excluded.code, expires_at=excluded.expires_at, attempts=0",
        (phone, code, expires_at),
    )


def otp_get(phone: str) -> dict[str, Any] | None:
    return db.one("SELECT * FROM otps WHERE phone=?", (phone,))


def otp_increment_attempts(phone: str) -> None:
    db.execute("UPDATE otps SET attempts=attempts+1 WHERE phone=?", (phone,))


def otp_delete(phone: str) -> None:
    db.execute("DELETE FROM otps WHERE phone=?", (phone,))


def session_create(token: str, pid: int, expires_at: int) -> None:
    db.execute("INSERT INTO sessions(token, partner_pid, expires_at) VALUES(?,?,?)", (token, pid, expires_at))


def session_get(token: str) -> dict[str, Any] | None:
    return db.one("SELECT * FROM sessions WHERE token=?", (token,))


def session_delete(token: str) -> None:
    db.execute("DELETE FROM sessions WHERE token=?", (token,))


# ------------------------------------------------------------- full accounts


def create_account_full(org_id: int, partner_pid: int, name: str, wa_number: str,
                        timezone: str, subscription_status: str = "trialing") -> int:
    return db.execute(
        "INSERT INTO accounts(partner_pid, org_id, name, wa_number, timezone, subscription_status, created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (partner_pid, org_id, name, wa_number, timezone, subscription_status, int(time.time())),
    )


def account_by_id(account_id: int) -> dict[str, Any] | None:
    return db.one("SELECT * FROM accounts WHERE id=?", (account_id,))


def account_by_number(wa_number: str) -> dict[str, Any] | None:
    return db.one("SELECT * FROM accounts WHERE wa_number=?", (wa_number,))


def set_account_number(account_id: int, number: str) -> None:
    db.execute("UPDATE accounts SET wa_number=? WHERE id=?", (number, account_id))


# -------------------------------------------------------------------- stats


def messages_since(account_id: int, since: int) -> int:
    return int(db.scalar(
        "SELECT COUNT(*) FROM messages WHERE account_id=? AND ts>=?", (account_id, since), default=0
    ))


def runs_since(account_id: int, since: int) -> int:
    return int(db.scalar(
        "SELECT COUNT(*) FROM runs WHERE account_id=? AND started_at>=?", (account_id, since), default=0
    ))


def followup_sent_count(account_id: int) -> int:
    return int(db.scalar(
        "SELECT COUNT(*) FROM followup_runs fr JOIN followup_rules r ON r.id=fr.rule_id "
        "WHERE r.account_id=? AND fr.status='sent'", (account_id,), default=0
    ))


def outbox_queued_count(account_id: int) -> int:
    return int(db.scalar(
        "SELECT COUNT(*) FROM outbox WHERE account_id=? AND status='queued'", (account_id,), default=0
    ))


def activity_rows(account_id: int, since: int) -> list[dict[str, Any]]:
    return db.query(
        "SELECT date(ts, 'unixepoch') AS day, direction, COUNT(*) AS n FROM messages "
        "WHERE account_id=? AND ts>=? GROUP BY day, direction ORDER BY day DESC",
        (account_id, since),
    )


def runs_by_status(account_id: int) -> list[dict[str, Any]]:
    return db.query("SELECT status, COUNT(*) AS n FROM runs WHERE account_id=? GROUP BY status", (account_id,))


def stop_task(task_id: int) -> None:
    db.execute("UPDATE tasks SET status='paused' WHERE id=?", (task_id,))


def outbox_context(outbox_id: int) -> dict[str, Any] | None:
    outbox = db.one("SELECT * FROM outbox WHERE id=?", (outbox_id,))
    if outbox is None:
        return None
    outbox["media"] = _loads(outbox.pop("media_json", "[]"), [])
    account = db.one("SELECT * FROM accounts WHERE id=?", (outbox["account_id"],))
    room = db.one("SELECT * FROM rooms WHERE id=?", (outbox["room_id"],))
    return {"outbox": outbox, "account": account, "room": room}


def recent_system_message(account_id: int, text: str, since: int) -> dict[str, Any] | None:
    return db.one(
        "SELECT * FROM messages WHERE account_id=? AND source='otp' AND text=? AND ts>=? "
        "ORDER BY id DESC LIMIT 1",
        (account_id, text, since),
    )


def webhook_in_use(account_id: int, webhook_id: int) -> bool:
    return bool(db.scalar(
        "SELECT COUNT(*) FROM agents WHERE account_id=? AND webhook_ids_json LIKE ?",
        (account_id, f"%{webhook_id}%"),
        default=0,
    ))


def delete_invitation(org_id: int, invitation_id: int) -> None:
    db.execute("DELETE FROM invitations WHERE id=? AND org_id=?", (invitation_id, org_id))


def rename_org(org_id: int, name: str) -> None:
    db.execute("UPDATE organizations SET name=? WHERE id=?", (name, org_id))


def set_task_status(task_id: int, status: str) -> None:
    db.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))


def healthy() -> bool:
    try:
        return bool(db.scalar("SELECT 1", default=0))
    except Exception:
        return False


def outbox_stats() -> dict[str, int]:
    rows = db.query("SELECT status, COUNT(*) AS n FROM outbox GROUP BY status")
    return {row["status"]: int(row["n"]) for row in rows}


def clear_pending_work() -> None:
    """Ops helper: stop all scheduled work (used by tests and maintenance)."""
    db.execute("UPDATE followup_rules SET enabled=0")
    db.execute("UPDATE jobs SET enabled=0")
    db.execute("UPDATE tasks SET status='done'")


# ------------------------------------------------------ provider credentials


def upsert_credential(org_id: int, provider: str, encrypted_key: str, nonce: str,
                      key_hint: str, base_url: Optional[str], created_by: Optional[int]) -> dict[str, Any]:
    now = int(time.time())
    db.execute(
        "INSERT INTO provider_credentials(org_id, provider, encrypted_key, nonce, key_hint, base_url, "
        "status, created_by, created_at, updated_at, last_validated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(org_id, provider) DO UPDATE SET encrypted_key=excluded.encrypted_key, nonce=excluded.nonce, "
        "key_hint=excluded.key_hint, base_url=excluded.base_url, status='active', updated_at=excluded.updated_at, "
        "last_validated_at=excluded.last_validated_at",
        (org_id, provider, encrypted_key, nonce, key_hint, base_url, "active", created_by, now, now, now),
    )
    return db.one(
        "SELECT * FROM provider_credentials WHERE org_id=? AND provider=?", (org_id, provider)
    )  # type: ignore[return-value]


def get_credential(org_id: int, provider: str) -> Optional[dict[str, Any]]:
    return db.one("SELECT * FROM provider_credentials WHERE org_id=? AND provider=?", (org_id, provider))


def list_credentials(org_id: int) -> list[dict[str, Any]]:
    rows = db.query("SELECT * FROM provider_credentials WHERE org_id=? ORDER BY provider", (org_id,))
    for row in rows:
        row.pop("encrypted_key", None)
        row.pop("nonce", None)
    return rows


def delete_credential(org_id: int, provider: str) -> None:
    db.execute("DELETE FROM provider_credentials WHERE org_id=? AND provider=?", (org_id, provider))


def update_credential(org_id: int, provider: str, **fields: Any) -> None:
    allowed = {"status", "last_validated_at", "last_used_at", "base_url", "key_hint"}
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return
    sets = ", ".join(f"{key}=?" for key in updates)
    db.execute(
        f"UPDATE provider_credentials SET {sets} WHERE org_id=? AND provider=?",
        (*updates.values(), org_id, provider),
    )


def set_org_defaults(org_id: int, provider: Optional[str], model: Optional[str]) -> None:
    db.execute(
        "UPDATE organizations SET default_provider=?, default_model=? WHERE id=?",
        (provider, model, org_id),
    )
