"""Repository facade.

The application imports `repo` and never cares which store is behind it:

    WASIGNAL_DB_BACKEND=sqlite  (default when no MONGODB_URI)
    WASIGNAL_DB_BACKEND=mongo   (default when MONGODB_URI is set)

Both modules expose the same functions and the same dict shapes.
"""
from __future__ import annotations

from .config import settings

if settings.db_backend == "mongo":
    from .storage.repo_mongo import *  # noqa: F401,F403
else:
    from .storage.repo_sqlite import *  # noqa: F401,F403
