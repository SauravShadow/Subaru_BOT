"""
Shadow Garden — FastAPI application factory.
Initialises the app, mounts static files, registers routes and WS endpoint.
"""
import logging
from pathlib import Path

import asyncio
from typing import Optional

from fastapi import FastAPI, WebSocket, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.state.manager import load_state
from app.api import router as api_router_module
from app.api import websocket as ws_module

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)

app = FastAPI(title="Shadow Garden Command Center")

STATIC_DIR = Path(__file__).parent / "static"

_poller_task: Optional[asyncio.Task] = None


# ── Startup / Shutdown ─────────────────────────────────────────────────────────

@app.on_event("startup")
async def on_startup():
    global _poller_task
    load_state()

    # Initialize memory database
    from app.services import memory as mem_svc
    mem_svc.init_db()

    # Load all skills (core metadata + learned handlers)
    from app.skills import skill_loader
    skill_loader.load_all()

    # Start email poller
    from app.services import email_poller
    _poller_task = asyncio.create_task(email_poller.start())


@app.on_event("shutdown")
async def on_shutdown():
    global _poller_task
    if _poller_task and not _poller_task.done():
        _poller_task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(_poller_task), timeout=3.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass


# ── REST routes ────────────────────────────────────────────────────────────────

app.include_router(api_router_module.router)


# ── WebSocket ──────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, model: str = Query(default="claude")):
    await ws_module.ws_endpoint(ws, model)


# ── Static frontend ────────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root():
    return FileResponse(str(STATIC_DIR / "index.html"))
