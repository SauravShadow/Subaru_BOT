# app/main.py
"""Shadow Garden — FastAPI application factory with LangGraph lifespan."""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.websockets import WebSocketDisconnect

from app.api import router as api_router_module
from app.api import websocket as ws_module
from app.api.websocket import broadcast_event

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # DB + memory
    from app.services import memory as mem_svc
    mem_svc.init_db()

    # Skills
    from app.skills import skill_loader
    skill_loader.load_all()

    # LangGraph checkpointer + graphs
    from app.graph.checkpointer import get_checkpointer
    from app.graph.nexus_graph import build_nexus_graph
    from app.graph.email.graph import build_email_graph

    cp = await get_checkpointer()
    app.state.nexus_graph = build_nexus_graph(cp)
    app.state.email_graph = build_email_graph(cp)

    # Background services
    from app.services import email_poller, scheduler
    asyncio.create_task(email_poller.start(app.state.email_graph))
    asyncio.create_task(scheduler.start_scheduler_loop())

    yield

    from app.graph.checkpointer import close_checkpointer
    await close_checkpointer()


app = FastAPI(title="Shadow Garden Command Center", lifespan=lifespan)

app.include_router(api_router_module.router)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, model: str = Query(default="claude")):
    await ws_module.ws_endpoint(ws, model)


@app.websocket("/ws/browser-relay")
async def browser_relay_endpoint(ws: WebSocket):
    """Receives browser_frame events from browser-svc."""
    secret = os.environ.get("BROWSER_RELAY_SECRET", "")
    if secret:
        auth = ws.headers.get("authorization", "")
        if auth != f"Bearer {secret}":
            await ws.close(code=4401)
            return
    await ws.accept()
    try:
        while True:
            try:
                data = await ws.receive_json()
            except WebSocketDisconnect:
                break
            except Exception:
                break
            if data.get("type") == "browser_result":
                active_model = next((s.model for s in ws_module._sessions), "claude")
                asyncio.create_task(ws_module.handle_browser_result(data, active_model))
            elif data.get("type") == "browser_blocker_resolved":
                asyncio.create_task(ws_module.handle_browser_blocker_resolved(data))
            else:
                await broadcast_event(data)
    except Exception:
        logging.getLogger(__name__).exception("browser_relay_endpoint error")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root():
    return FileResponse(str(STATIC_DIR / "index.html"))
