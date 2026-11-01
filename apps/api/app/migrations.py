"""Forward-only schema migrations for existing databases.

`schema.sql` covers fresh installs (CREATE TABLE IF NOT EXISTS). This handles
databases created before organizations existed: add `accounts.org_id`, then give
every partner an organization, an owner membership, and attach their accounts.

Production should use Alembic; this keeps the scaffold upgradeable in place.
"""
from __future__ import annotations

import re
import time
from typing import Any

from .db import Database


def _columns(db: Database, table: str) -> set[str]:
    return {row["name"] for row in db.query(f"PRAGMA table_info({table})")}


def _slug(name: str, pid: int) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or f"org-{pid}"
    return f"{base[:40]}-{pid}"


def run(db: Database) -> None:
    if "org_id" not in _columns(db, "accounts"):
        db.execute("ALTER TABLE accounts ADD COLUMN org_id INTEGER REFERENCES organizations(id)")

    run_columns = _columns(db, "runs")
    if "llm_provider" not in run_columns:
        db.execute("ALTER TABLE runs ADD COLUMN llm_provider TEXT")
    if "llm_model" not in run_columns:
        db.execute("ALTER TABLE runs ADD COLUMN llm_model TEXT")
    if "tool_calls_json" not in run_columns:
        db.execute("ALTER TABLE runs ADD COLUMN tool_calls_json TEXT NOT NULL DEFAULT '[]'")

    now = int(time.time())
    for partner in db.query("SELECT pid, name FROM partners"):
        pid = int(partner["pid"])
        existing = db.one("SELECT org_id FROM memberships WHERE pid=? ORDER BY id LIMIT 1", (pid,))
        if existing is not None:
            org_id = int(existing["org_id"])
        else:
            org_id = db.execute(
                "INSERT INTO organizations(name, slug, owner_pid, created_at) VALUES(?,?,?,?)",
                (partner["name"] or f"Workspace {pid}", _slug(partner["name"] or "", pid), pid, now),
            )
            db.execute(
                "INSERT INTO memberships(org_id, pid, role, created_at) VALUES(?,?,?,?)",
                (org_id, pid, "owner", now),
            )
        db.execute(
            "UPDATE accounts SET org_id=? WHERE partner_pid=? AND (org_id IS NULL OR org_id=0)",
            (org_id, pid),
        )
