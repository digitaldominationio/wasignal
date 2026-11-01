"""SQLite access.

One connection guarded by a re-entrant lock. Fine for a scaffold and for a
single-node deployment; swap `Database` for a Mongo/Postgres repository layer
when you outgrow it (see docs/ARCHITECTURE.md).
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from .config import settings


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def _migrate(self) -> None:
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        with self._lock:
            self._conn.executescript(schema)
            self._conn.commit()
        from . import migrations

        migrations.run(self)

    @contextmanager
    def cursor(self) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        with self.cursor() as cur:
            cur.execute(sql, tuple(params))
            return int(cur.lastrowid or 0)

    def executemany(self, sql: str, rows: Iterable[Iterable[Any]]) -> None:
        with self.cursor() as cur:
            cur.executemany(sql, [tuple(r) for r in rows])

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            try:
                return [dict(row) for row in cur.fetchall()]
            finally:
                cur.close()

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql: str, params: Iterable[Any] = (), default: Any = None) -> Any:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            try:
                row = cur.fetchone()
                return default if row is None else row[0]
            finally:
                cur.close()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# SQLite is the offline default. With the Mongo backend this module is still
# importable, but no connection (and no data/ directory) is created.
db: Database | None = Database(settings.db_path) if settings.db_backend == "sqlite" else None
