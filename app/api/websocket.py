# app/api/websocket.py
"""WebSocket handler — wraps nexus_graph.astream_events() and broadcasts to clients."""
import asyncio
import json
import logging
import re
from uuid import uuid4

from fastapi import WebSocket
from fastapi.websockets import WebSocketDisconnect

from app.agents import definitions as defs
from app.graph import broadcast as bcast

logger = logging.getLogger(__name__)

# ── In-memory step/checkpoint counters (per thread+agent) ──────────────────────

_step_counters: dict[str, int] = {}        # f"{thread_id}:{agent_id}" → count
_checkpoint_counters: dict[str, int] = {}  # f"{thread_id}:{agent_id}" → count

_DONE_RE = re.compile(r'\[DONE:\s*([^\]]{1,120})\]')


def _agent_key(thread_id: str, agent_id: str) -> str:
    return f"{thread_id}:{agent_id}"


def _extract_agent_id(metadata: dict) -> str:
    """Extract agent_id from langgraph_checkpoint_ns like 'backend:abc123'."""
    ns = metadata.get("langgraph_checkpoint_ns", "")
    return ns.split(":")[0] if ":" in ns else ns


def _extract_summary(result: str) -> str:
    m = _DONE_RE.search(result)
    return m.group(1).strip() if m else result.strip()[:120]


def _translate_event(event: dict, thread_id: str) -> dict | None:
    """Map a LangGraph astream_events v2 event to a frontend WS message."""
    kind = event.get("event", "")
    name = event.get("name", "")
    metadata = event.get("metadata", {})
    data = event.get("data", {})
    agent_id = _extract_agent_id(metadata)

    # Reset counters at start of new CEO task
    if kind == "on_chain_start" and name == "ceo_node":
        for k in list(_step_counters):
            if k.startswith(thread_id + ":"):
                del _step_counters[k]
        for k in list(_checkpoint_counters):
            if k.startswith(thread_id + ":"):
                del _checkpoint_counters[k]
        return {"type": "thinking", "agent": "ceo", "thread_id": thread_id}

    if kind == "on_chain_start" and name in defs.all_agents():
        return {"type": "delegation", "agent": name, "thread_id": thread_id}

    if kind == "on_tool_start":
        key = _agent_key(thread_id, agent_id)
        _step_counters[key] = _step_counters.get(key, 0) + 1
        step = _step_counters[key]
        tool_name = data.get("name") or name
        tool_input = data.get("input", {})
        label = (
            tool_input.get("command")
            or tool_input.get("file_path")
            or tool_input.get("query")
            or tool_name
        )
        if isinstance(label, str) and len(label) > 80:
            label = label[:80] + "…"
        return {
            "type": "worker_step",
            "agent": agent_id,
            "step": step,
            "tool": tool_name,
            "label": str(label),
            "thread_id": thread_id,
        }

    if kind == "on_chain_end" and name == "worker_node":
        key = _agent_key(thread_id, agent_id)
        _checkpoint_counters[key] = _checkpoint_counters.get(key, 0) + 1
        step = _step_counters.get(key, 0)
        output = data.get("output", {})
        summary = _extract_summary(output.get("result", ""))
        return {
            "type": "worker_checkpoint",
            "agent": agent_id,
            "index": _checkpoint_counters[key],
            "summary": summary,
            "step": step,
            "thread_id": thread_id,
        }

    if kind == "on_chain_end" and name == "output_node":
        return {"type": "worker_done", "agent": agent_id, "thread_id": thread_id}

    if kind == "on_chain_end" and name == "ceo_node":
        return {"type": "done", "agent": "ceo", "thread_id": thread_id}

    if kind == "on_chain_error":
        err = str(data.get("error", "unknown error"))[:200]
        return {"type": "error", "agent": agent_id or "unknown", "message": err, "thread_id": thread_id}

    if kind == "on_chat_model_stream":
        chunk = data.get("chunk", {})
        content = getattr(chunk, "content", "") if hasattr(chunk, "content") else ""
        if content:
            return {"type": "assistant", "agent": agent_id or "ceo", "message": {"content": content}, "thread_id": thread_id}

    return None


# ── Sessions + active runs ─────────────────────────────────────────────────────

class Session:
    def __init__(self, ws: WebSocket, model: str):
        self.ws = ws
        self.model = model
        self._lock = asyncio.Lock()

    async def send(self, data: dict) -> None:
        async with self._lock:
            try:
                await self.ws.send_json(data)
            except Exception:
                pass


_sessions: set[Session] = set()
_active_runs: dict[str, asyncio.Task] = {}


async def broadcast_event(data: dict) -> None:
    for session in list(_sessions):
        await session.send(data)


def _build_init_payload() -> dict:
    agents = defs.all_agents()
    return {
        "type": "init",
        "agents": [
            {"id": aid, "name": a["name"], "role": a["role"], "status": "idle"}
            for aid, a in agents.items()
        ],
        "work_queue": [],
    }


async def _run_and_stream(task: str, thread_id: str, model: str) -> None:
    from app.graph.nexus_graph import build_nexus_graph
    from app.graph.checkpointer import get_checkpointer

    cp = await get_checkpointer()
    graph = build_nexus_graph(cp)

    async def send_fn(data: dict) -> None:
        await broadcast_event(data)

    bcast.register(thread_id, send_fn)
    try:
        config = {"configurable": {"thread_id": thread_id, "model": model}}
        async for event in graph.astream_events(
            {"task": task, "session_id": thread_id, "model": model,
             "source": "browser", "worker_results": [], "delegations": [],
             "artifacts": {}, "ceo_verdict": "approved", "revision_notes": "",
             "ceo_response": "", "worker_progress": {}},
            config,
            version="v2",
        ):
            msg = _translate_event(event, thread_id)
            if msg:
                await broadcast_event(msg)
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.exception("nexus_graph run error: %s", exc)
        await broadcast_event({"type": "error", "agent": "ceo", "message": str(exc)})
    finally:
        bcast.unregister(thread_id)


async def ws_endpoint(ws: WebSocket, model: str = "claude") -> None:
    session = Session(ws, model)
    thread_id = f"ws_{uuid4().hex}"
    _sessions.add(session)
    await ws.accept()
    await session.send(_build_init_payload())

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type", "")

            if msg_type == "message":
                t = asyncio.create_task(
                    _run_and_stream(msg["text"], thread_id, session.model)
                )
                _active_runs[thread_id] = t

            elif msg_type == "cancel_worker":
                task = _active_runs.pop(thread_id, None)
                if task:
                    task.cancel()

            elif msg_type == "model":
                session.model = msg.get("model", session.model)

            elif msg_type == "clear":
                task = _active_runs.pop(thread_id, None)
                if task:
                    task.cancel()

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("ws_endpoint error")
    finally:
        _sessions.discard(session)
        task = _active_runs.pop(thread_id, None)
        if task:
            task.cancel()


async def handle_browser_result(data: dict, model: str) -> None:
    await broadcast_event(data)


async def handle_browser_blocker_resolved(data: dict) -> None:
    await broadcast_event(data)
