"""Monotonic integer ids per collection.

The API exposes integer ids (paths, query params, the UI). Mongo's ObjectId
would change that contract, so documents are keyed by a counter — which also
makes SQLite -> Mongo migration a straight copy that preserves ids.
"""
from __future__ import annotations

from pymongo import ReturnDocument

from .mongo import get_db


def next_id(name: str) -> int:
    doc = get_db()["counters"].find_one_and_update(
        {"_id": name}, {"$inc": {"seq": 1}}, upsert=True, return_document=ReturnDocument.AFTER
    )
    return int(doc["seq"])


def set_counter(name: str, value: int) -> None:
    get_db()["counters"].update_one({"_id": name}, {"$max": {"seq": int(value)}}, upsert=True)
