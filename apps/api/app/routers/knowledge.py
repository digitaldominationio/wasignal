"""Knowledge sources and entries. A source is a chat; entries are extracted facts."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import repo
from ..deps import current_account
from ..schemas import KnowledgeEntryBody, KnowledgeSourceBody

router = APIRouter(prefix="/dashboard/knowledge-sources", tags=["knowledge"])


@router.get("")
def list_sources(account: dict = Depends(current_account)) -> dict:
    return {"items": repo.list_sources(int(account["id"]))}


@router.post("", status_code=201)
def create_source(body: KnowledgeSourceBody, account: dict = Depends(current_account)) -> dict:
    return repo.create_source(int(account["id"]), body.model_dump())


@router.get("/{source_id}")
def get_source(source_id: int, account: dict = Depends(current_account)) -> dict:
    sources = [source for source in repo.list_sources(int(account["id"])) if int(source["id"]) == source_id]
    if not sources:
        raise HTTPException(status_code=404, detail="source_not_found")
    return sources[0]


@router.get("/{source_id}/entries")
def list_entries(source_id: int, q: str = "", account: dict = Depends(current_account)) -> dict:
    get_source(source_id, account)
    items = repo.list_entries(source_id)
    if q:
        needle = q.lower()
        items = [item for item in items if needle in f"{item.get('title','')} {item.get('content','')}".lower()]
    return {"items": items}


@router.post("/{source_id}/entries", status_code=201)
def create_entry(source_id: int, body: KnowledgeEntryBody, account: dict = Depends(current_account)) -> dict:
    get_source(source_id, account)
    return repo.create_entry(source_id, body.model_dump())


@router.post("/{source_id}/extract")
def extract(source_id: int, account: dict = Depends(current_account)) -> dict:
    """Placeholder for the vision/LLM extraction step.

    Production: read the source room's messages, run the extraction instruction
    over them (vision for images/PDFs), and insert entries with provenance.
    """
    get_source(source_id, account)
    return {"status": "not_implemented", "note": "wire an LLM extraction job here"}
