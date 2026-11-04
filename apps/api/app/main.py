"""Wasignal API — a WhatsApp-native AI agent platform.

Run:  uvicorn app.main:app --reload --port 8000
Docs: http://127.0.0.1:8000/docs
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .deps import require_writer
from .routers import (
    accounts,
    agents,
    auth,
    billing,
    channels,
    chat,
    integrations,
    internal,
    knowledge,
    models,
    organizations,
    providers,
    rooms,
    scheduling,
    webhooks,
    workspace,
)
from .services import billing as billing_service
from .services import outbound, scheduler
from .storage import init_storage
from .seed import seed_demo


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_storage()
    billing_service.ensure_plans()
    if settings.seed_demo:
        seed_demo()
    outbound.start_worker()
    if settings.scheduler_enabled:
        scheduler.start_ticker(settings.tick_seconds)
    try:
        yield
    finally:
        await scheduler.stop_ticker()
        await outbound.stop_worker()


app = FastAPI(
    title=settings.app_name,
    description="WhatsApp-native AI agents: tenants, roles, plans, the agent runtime and scheduling.",
    version="0.2.0",
    lifespan=lifespan,
)

if settings.cors_origins:
    # Required for a split deployment (frontend on Cloudflare, API on your box).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["set-cookie"],
        max_age=600,
    )

# Reads are open to any member; mutations need `member` or better (viewers blocked).
for router in (
    auth.router,
    accounts.router,
    organizations.router,
    billing.router,
    models.router,
    providers.router,
    internal.router,
    billing.webhooks,
):
    app.include_router(router)

for guarded in (
    rooms.router,
    agents.router,
    chat.router,
    scheduling.router,
    webhooks.router,
    knowledge.router,
    channels.router,
    integrations.router,
    workspace.router,
):
    app.include_router(guarded, dependencies=[Depends(require_writer)])


@app.get("/")
def root() -> dict:
    return {
        "service": settings.app_name,
        "environment": settings.env,
        "llm_provider": settings.llm_provider,
        "channel": settings.channel,
        "docs": "/docs",
    }
