"""Naive keyword retrieval over structured knowledge entries.

Deliberately not an embedding store: entries are small, and a scorer you can
explain is easier to debug than a vector index you cannot. Swap `search` for a
hybrid (BM25 + embeddings) search once catalogues grow.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from .. import repo

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return {word for word in _WORD.findall((text or "").lower()) if len(word) > 2}


def search(account_id: int, query: str, *, source_ids: Optional[list[int]] = None, limit: int = 3) -> list[dict[str, Any]]:
    query_tokens = _tokens(query)
    results: list[tuple[float, dict[str, Any]]] = []
    for entry in repo.all_entries(account_id):
        if source_ids is not None and entry["source_id"] not in source_ids:
            continue
        haystack = " ".join([
            entry.get("title", ""),
            entry.get("content", ""),
            " ".join(entry.get("keys") or []),
            " ".join(f"{k} {v}" for k, v in (entry.get("metadata") or {}).items()),
        ])
        entry_tokens = _tokens(haystack)
        if not entry_tokens:
            continue
        overlap = len(query_tokens & entry_tokens)
        if overlap == 0:
            continue
        score = overlap / (len(query_tokens) or 1)
        # exact key or title hit wins
        if any(token in entry_tokens for token in query_tokens if token in (entry.get("keys") or [])):
            score += 0.5
        results.append((score, entry))

    results.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
    return [
        {
            "id": entry["id"],
            "title": entry.get("title", ""),
            "content": entry.get("content", ""),
            "keys": entry.get("keys") or [],
            "source": entry.get("source_name"),
            "medias": entry.get("medias") or [],
        }
        for _, entry in results[:limit]
    ]
