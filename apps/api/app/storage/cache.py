"""Redis-backed cache, locks and counters — with an in-process fallback.

Redis is what makes the scaffold safe to run as more than one replica: the
outbox worker and scheduler take a lock per tick, so two API processes cannot
double-send. Without WASIGNAL_REDIS_URL everything degrades to the old
single-process behaviour instead of failing.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from ..config import settings

try:  # optional dependency at runtime
    import redis as _redis
except Exception:  # pragma: no cover
    _redis = None  # type: ignore[assignment]


class Cache:
    def __init__(self) -> None:
        self._local: dict[str, tuple[float, str]] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self._client: Any = None

    # ------------------------------------------------------------------ client

    def client(self) -> Any:
        if self._client is not None:
            return self._client
        if settings.fakeredis:
            import fakeredis

            self._client = fakeredis.FakeRedis(decode_responses=True)
        elif settings.redis_url and _redis is not None:
            self._client = _redis.from_url(settings.redis_url, decode_responses=True)
        return self._client

    def ping(self) -> bool:
        client = self.client()
        if client is None:
            return False
        try:
            return bool(client.ping())
        except Exception:
            return False

    # ------------------------------------------------------------------- basic

    def get_json(self, key: str) -> Optional[Any]:
        client = self.client()
        if client is not None:
            raw = client.get(key)
        else:
            entry = self._local.get(key)
            if entry is None or entry[0] < time.time():
                self._local.pop(key, None)
                return None
            raw = entry[1]
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None

    def set_json(self, key: str, value: Any, ttl: int) -> None:
        raw = json.dumps(value, ensure_ascii=False)
        client = self.client()
        if client is not None:
            client.set(key, raw, ex=max(1, int(ttl)))
        else:
            self._local[key] = (time.time() + ttl, raw)

    def delete(self, key: str) -> None:
        client = self.client()
        if client is not None:
            client.delete(key)
        else:
            self._local.pop(key, None)

    def incr(self, key: str, ttl: int) -> int:
        client = self.client()
        if client is not None:
            value = int(client.incr(key))
            if value == 1:
                client.expire(key, ttl)
            return value
        current = self._local.get(key)
        if current and current[0] >= time.time():
            value = int(current[1]) + 1
        else:
            value = 1
        self._local[key] = (time.time() + ttl, str(value))
        return value

    # ------------------------------------------------------------------- locks

    @contextmanager
    def lock(self, name: str, ttl_seconds: int = 30) -> Iterator[bool]:
        """Yield True when this process owns the lock for the duration."""
        client = self.client()
        if client is None:
            # single-process fallback: never contend with ourselves
            with self._guard:
                lock = self._locks.setdefault(name, threading.Lock())
            acquired = lock.acquire(blocking=False)
            try:
                yield acquired
            finally:
                if acquired:
                    lock.release()
            return

        token = uuid.uuid4().hex
        acquired = bool(client.set(f"lock:{name}", token, nx=True, px=max(500, ttl_seconds * 1000)))
        try:
            yield acquired
        finally:
            if acquired:
                # release only if we still own it
                try:
                    client.eval(
                        "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
                        1, f"lock:{name}", token,
                    )
                except Exception:
                    pass

    def info(self) -> dict[str, Any]:
        client = self.client()
        if client is None:
            return {"backend": "memory", "keys": len(self._local)}
        try:
            return {"backend": "redis" if not settings.fakeredis else "fakeredis", "ping": self.ping()}
        except Exception as exc:  # pragma: no cover
            return {"backend": "redis", "error": str(exc)}


cache = Cache()
