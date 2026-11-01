"""MongoDB storage client and indexes."""
from __future__ import annotations

from typing import Any

from ..config import settings

_client: Any = None

INDEXES: dict[str, list[tuple[list[tuple[str, int]], dict[str, Any]]]] = {
    "partners": [([("phone", 1)], {"unique": True})],
    "sessions": [([("expires_at", 1)], {})],
    "accounts": [([("org_id", 1)], {}), ([("partner_pid", 1)], {}), ([("wa_number", 1)], {})],
    "rooms": [([("account_id", 1), ("external_id", 1)], {"unique": True}),
              ([("account_id", 1), ("last_activity_at", -1)], {})],
    "messages": [([("room_id", 1), ("ts", -1)], {}),
                 ([("account_id", 1), ("ts", -1)], {}),
                 ([("account_id", 1), ("source", 1), ("ts", -1)], {})],
    "agents": [([("account_id", 1)], {})],
    "lanes": [([("agent_id", 1), ("room_id", 1), ("lane_key", 1)], {"unique": True})],
    "memory": [([("agent_id", 1), ("key", 1)], {"unique": True})],
    "runs": [([("agent_id", 1), ("_id", -1)], {}), ([("account_id", 1), ("started_at", -1)], {})],
    "webhooks": [([("account_id", 1)], {})],
    "deliveries": [([("webhook_id", 1), ("_id", -1)], {})],
    "knowledge_sources": [([("account_id", 1)], {})],
    "knowledge_entries": [([("source_id", 1)], {})],
    "jobs": [([("account_id", 1)], {}), ([("enabled", 1), ("next_run_at", 1)], {})],
    "tasks": [([("account_id", 1)], {}), ([("status", 1), ("execute_after_at", 1)], {})],
    "followup_rules": [([("scope", 1), ("ref_id", 1)], {"unique": True})],
    "followup_runs": [([("rule_id", 1), ("room_id", 1), ("rule_key", 1)], {}), ([("due_at", 1)], {})],
    "outbox": [([("status", 1), ("_id", 1)], {})],
    "organizations": [([("slug", 1)], {"unique": True})],
    "memberships": [([("org_id", 1), ("pid", 1)], {"unique": True}), ([("pid", 1)], {})],
    "invitations": [([("token", 1)], {"unique": True}), ([("org_id", 1), ("accepted_at", 1)], {}),
                    ([("phone", 1), ("accepted_at", 1)], {})],
    "plans": [],
    "subscriptions": [],
    "usage_events": [([("org_id", 1), ("metric", 1), ("ts", -1)], {})],
}


def get_client() -> Any:
    global _client
    if _client is None:
        if settings.mongomock:
            import mongomock

            _client = mongomock.MongoClient()
        else:
            from pymongo import MongoClient

            _client = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=4000, tz_aware=False)
    return _client


def get_db() -> Any:
    return get_client()[settings.mongodb_db]


def ensure_indexes() -> None:
    database = get_db()
    for name, specs in INDEXES.items():
        collection = database[name]
        for keys, options in specs:
            collection.create_index(keys, **options)


def reset_client() -> None:
    global _client
    if _client is not None:
        try:
            _client.close()
        except Exception:
            pass
    _client = None
