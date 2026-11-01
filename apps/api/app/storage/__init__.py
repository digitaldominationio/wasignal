"""Storage selection: Mongo when configured, SQLite otherwise."""
from __future__ import annotations

from ..config import settings
from .cache import cache

if settings.db_backend == "mongo":
    from . import repo_mongo as repo  # noqa: F401
    from .mongo import ensure_indexes
else:
    from . import repo_sqlite as repo  # noqa: F401

    def ensure_indexes() -> None:  # type: ignore[misc]
        return None


def init_storage() -> dict:
    ensure_indexes()
    return {
        "backend": settings.db_backend,
        "cache": cache.info(),
        "cache_ok": cache.ping(),
    }
