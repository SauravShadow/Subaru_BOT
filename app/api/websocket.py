"""
Single-WebSocket multi-agent endpoint.

Protocol (client → server):
  {"type": "message",        "agent": "ceo",  "text": "..."}
  {"type": "clear",          "agent": "ceo"}
  {"type": "model",          "model": "claude" | "chatgpt" | "gemini"}
  {"type": "force_complete", "task_id": 5}
  {"type": "reset_task",     "task_id": 5}
  {"type": "cancel_worker",  "agent": "reinhard"}

Protocol (server → client):
  {"type": "init",           "agents": {...}, "workdir": "...", "work_queue": [...]}
  {"type": "thinking",       "agent": "ceo"}
  {"type": "assistant",      "agent": "ceo",  "message": {"content": [...]}}
  {"type": "tool_call",      "agent": "...",  "tool": "bash", "path": "...", "label": "..."}
  {"type": "done",           "agent": "ceo"}
  {"type": "worker_done",    "agent": "reinhard", "task_id": 5, "summary": "..."}
  {"type": "delegation",     "item": {...}}
  {"type": "cleared",        "agent": "ceo"}
  {"type": "failover",       "agent": "...",  "message": "..."}
  {"type": "error",          "agent": "...",  "message": "..."}
  {"type": "email_sent",     "subject": "...", "ok": true}
  {"type": "queue_update",   "work_queue": [...]}
"""
import asyncio
import json
import logging
from typing import Any, Dict, Set

from fastapi import WebSocket, WebSocketDisconnect, Query

from app.agents import backend_state
from app.agents import definitions as defs
from app.agents.executor import run_agent
from app.services import delegation as deleg_svc
from app.services import email as email_svc
from app.state import manager as state
from app.skills import skill_loader

logger = logging.getLogger(__name__)

# Module-level registry of active WebSocket sessions for broadcasting
_sessions: set["Session"] = set()


async def broadcast_event(data: dict) -> None:
    """Send an event to all currently connected WebSocket sessions."""
    for session in list(_sessions):
        try:
            await session.send(data)
        except Exception:
            pass


# ── Session helpers ────────────────────────────────────────────────────────────

class Session:
    """Per-WebSocket session state."""

    def __init__(self, ws: WebSocket, model: str):
        self.ws     = ws
        self.model  = model
        self._lock  = asyncio.Lock()
        self.bg_tasks: Set[asyncio.Task] = set()
        # agent_id → asyncio.Task for cancellable background workers
        self.worker_tasks: Dict[str, asyncio.Task] = {}

    async def send(self, data: dict) -> None:
        """Thread-safe WS send that handles a special _raw_json passthrough."""
        async with self._lock:
            try:
                if "_raw_json" in data:
                    await self.ws.send_text(data["_raw_json"])
                else:
                    if data.get("type") == "audio":
                        audio_len = len(data.get("data", ""))
                        logger.info("WS send: audio payload %d bytes", audio_len)
                    await self.ws.send_json(data)
                    if data.get("type") == "audio":
                        logger.info("WS send: audio sent successfully")
            except Exception as exc:
                logger.warning("WS send error (type=%s): %s", data.get("type"), exc)

    def make_sender(self, agent_id: str):
        """Return a Sender coroutine that always tags the agent_id."""
        async def _send(data: dict) -> None:
            # Ensure every event carries the agent tag
            if "agent" not in data and "_raw_json" not in data:
                data = {**data, "agent": agent_id}
            await self.send(data)
        return _send

    def cancel_all(self) -> None:
        for t in list(self.bg_tasks):
            t.cancel()
        for t in list(self.worker_tasks.values()):
            t.cancel()


# ── Background worker runner ───────────────────────────────────────────────────

async def _run_worker_bg(
    session: Session,
    agent_id: str,
    task_text: str,
    task_id: int,
) -> None:
    """Execute a delegated task in the background, streaming updates to the browser."""
    _completed_ok = False
    try:
        send = session.make_sender(agent_id)

        # Mark task running in state
        for item in state.work_queue:
            if item["id"] == task_id:
                item["status"] = "running"
                state.active_agent_tasks[agent_id] = task_id
                state.save_state()
                break

        await session.send({
            "type": "thinking", "agent": agent_id,
            "task_id": task_id,
        })

        state.record(agent_id, "user", task_text)
        full_resp = await run_agent(agent_id, task_text, send, session.model)
        state.record(agent_id, "assistant", deleg_svc.clean_response(full_resp))

        # Summarise completion
        import re
        done_m = re.search(r'\[DONE:\s*(.*?)\]', full_resp, re.DOTALL)
        summary = done_m.group(1).strip() if done_m else (full_resp.strip()[:120] + "…")

        completed = state.complete_work_item(task_id, summary)
        await session.send({
            "type":    "worker_done",
            "agent":   agent_id,
            "task_id": task_id,
            "summary": summary,
        })
        await session.send({"type": "queue_update", "work_queue": state.work_queue})
        await session.send({"type": "task_history_update",
                            "task_history": list(reversed(state.task_history))})
        await session.send({"type": "done", "agent": agent_id})
        _completed_ok = True

    except asyncio.CancelledError:
        logger.info("Worker %s task %d cancelled", agent_id, task_id)
        state.reset_work_item(task_id)
        await session.send({
            "type": "assistant", "agent": agent_id,
            "message": {"content": [{"type": "text",
                "text": f"\n[Worker {agent_id} task cancelled by user]\n"
            }]},
        })
    except Exception as exc:
        logger.exception("Worker %s failed: %s", agent_id, exc)
        state.reset_work_item(task_id)
        await session.send({"type": "error", "agent": agent_id, "message": str(exc)})
    finally:
        session.worker_tasks.pop(agent_id, None)
        if _completed_ok:
            # Chain to next pending task for this agent (sequential queue processing)
            next_item = next(
                (i for i in state.work_queue
                 if i.get("agent") == agent_id and i.get("status") == "pending"),
                None,
            )
            if next_item:
                bg = asyncio.create_task(
                    _run_worker_bg(session, agent_id, next_item["task"], next_item["id"])
                )
                session.bg_tasks.add(bg)
                bg.add_done_callback(session.bg_tasks.discard)
                session.worker_tasks[agent_id] = bg
                logger.info(
                    "Chaining to next pending task #%d for agent '%s'",
                    next_item["id"], agent_id,
                )


async def handle_browser_result(data: dict) -> None:
    """Feed a completed browser-svc task back into the originating worker's
    conversation, mirroring _run_worker_bg's record → run_agent → record sequence
    so the worker is grounded in a real result instead of narrating unconfirmed claims."""
    agent_id   = data.get("agent_id", "maya")
    slot_id    = data.get("slot_id")
    tool       = data.get("tool", "browser action")
    result     = data.get("result", "")
    slot_label = f" (slot {slot_id})" if slot_id is not None else ""
    task_text  = f"[Browser result{slot_label} — {tool}] {result}"

    async def send(payload: dict) -> None:
        if "agent" not in payload and "_raw_json" not in payload:
            payload = {**payload, "agent": agent_id}
        await broadcast_event(payload)

    await broadcast_event({"type": "thinking", "agent": agent_id})
    state.record(agent_id, "user", task_text)
    full_resp = await run_agent(agent_id, task_text, send)
    state.record(agent_id, "assistant", deleg_svc.clean_response(full_resp))
    await broadcast_event({"type": "done", "agent": agent_id})


# ── Message router ─────────────────────────────────────────────────────────────

async def _heartbeat_loop(session: Session) -> None:
    """Send periodic heartbeats so proxies/firewalls don't drop idle connections."""
    while True:
        await asyncio.sleep(5)
        await session.send({"type": "heartbeat"})


async def _handle_message(session: Session, agent_id: str, text: str) -> None:
    """Execute a user message to a specific agent."""
    state.record(agent_id, "user", text)
    send = session.make_sender(agent_id)

    await session.send({"type": "thinking", "agent": agent_id})

    hb = asyncio.create_task(_heartbeat_loop(session))
    try:
        full_resp = await run_agent(agent_id, text, send, session.model)
    finally:
        hb.cancel()

    # Handle CEO delegations
    if agent_id == "ceo":
        for role, task_text in deleg_svc.parse_delegations(full_resp):
            item = state.create_work_item(role, task_text, "ceo")
            await session.send({"type": "delegation", "item": item})
            await session.send({"type": "queue_update", "work_queue": state.work_queue})

            # Spawn background worker
            bg = asyncio.create_task(
                _run_worker_bg(session, role, task_text, item["id"])
            )
            session.bg_tasks.add(bg)
            bg.add_done_callback(session.bg_tasks.discard)
            session.worker_tasks[role] = bg

    state.record(agent_id, "assistant", deleg_svc.clean_delegations(full_resp))
    await session.send({"type": "done", "agent": agent_id})


async def _handle_vision_message(
    session: "Session",
    agent_id: str,
    text: str,
    images: list[dict],
) -> None:
    """Handle a message with image attachments — routes to Claude Vision."""
    from app.agents.executor import run_claude_vision

    user_label = f"{text} [+{len(images)} image(s)]" if text else f"[{len(images)} image(s)]"
    state.record(agent_id, "user", user_label)
    send = session.make_sender(agent_id)

    await session.send({"type": "thinking", "agent": agent_id})
    full_resp = await run_claude_vision(agent_id, text, images, send)

    state.record(agent_id, "assistant", full_resp)
    await session.send({"type": "done", "agent": agent_id})


async def _handle_force_complete(session: Session, task_id: int) -> None:
    item = state.force_complete_item(task_id)
    if item:
        agent_id = item.get("agent", "")
        # Cancel any running background task for this agent
        t = session.worker_tasks.pop(agent_id, None)
        if t:
            t.cancel()
        await session.send({"type": "queue_update", "work_queue": state.work_queue})
        await session.send({
            "type": "assistant", "agent": "ceo",
            "message": {"content": [{"type": "text",
                "text": f"\n🛠 Task #{task_id} for {agent_id} was force-completed.\n"
            }]},
        })


async def _handle_reset_task(session: Session, task_id: int) -> None:
    item = state.reset_work_item(task_id)
    if item:
        agent_id = item.get("agent", "")
        t = session.worker_tasks.pop(agent_id, None)
        if t:
            t.cancel()
        await session.send({"type": "queue_update", "work_queue": state.work_queue})


async def _handle_cancel_worker(session: Session, agent_id: str) -> None:
    t = session.worker_tasks.pop(agent_id, None)
    if t:
        t.cancel()
    # Also reset the running task in the queue for this agent
    for item in state.work_queue:
        if item.get("agent") == agent_id and item.get("status") == "running":
            item["status"] = "pending"
            state.save_state()
    await session.send({"type": "queue_update", "work_queue": state.work_queue})


# ── WebSocket endpoint ─────────────────────────────────────────────────────────

async def ws_endpoint(ws: WebSocket, model: str = Query(default="claude")) -> None:
    session = Session(ws, model)
    await ws.accept()
    _sessions.add(session)

    agents  = defs.all_agents()
    await session.send({
        "type":         "init",
        "agents":       {k: defs.public_agent_info(k, v) for k, v in agents.items()},
        "workdir":      str(state._get_workdir()),
        "work_queue":   state.work_queue,
        "backend":      backend_state.status_dict(),
        "changelog":    state.load_changelog()[-5:],
        "task_history": list(reversed(state.task_history)),
        "skills":       skill_loader.list_tools(),
    })
    # Clear any stale thinking/spinner state from a previous disconnected session
    for agent_id in agents:
        await session.send({"type": "done", "agent": agent_id})

    # Reset tasks left as "running" by a previous session whose workers were cancelled
    stale = [i for i in state.work_queue if i.get("status") == "running"]
    if stale:
        for item in stale:
            item["status"] = "pending"
        state.save_state()
        logger.info("Reset %d stale 'running' task(s) to pending on new connection", len(stale))

    # Auto-resume pending background tasks — one per agent, in queue order
    resumed: set[str] = set()
    for item in state.work_queue:
        if item.get("status") != "pending":
            continue
        worker_agent = item.get("agent", "")
        if worker_agent not in agents or worker_agent in resumed:
            continue
        resumed.add(worker_agent)
        bg = asyncio.create_task(
            _run_worker_bg(session, worker_agent, item["task"], item["id"])
        )
        session.bg_tasks.add(bg)
        bg.add_done_callback(session.bg_tasks.discard)
        session.worker_tasks[worker_agent] = bg
        logger.info("Auto-resuming pending task #%d for agent '%s'", item["id"], worker_agent)

    if resumed:
        await session.send({"type": "queue_update", "work_queue": state.work_queue})

    try:
        while True:
            raw = await ws.receive_text()
            raw = raw.strip()
            if not raw:
                continue

            # Parse — fall back to plain CEO text for backward compat
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                msg = {"type": "message", "agent": "ceo", "text": raw}

            msg_type = msg.get("type", "message")

            if msg_type == "message":
                agent_id    = msg.get("agent", "ceo")
                text        = msg.get("text", "").strip()
                attachments = msg.get("attachments", [])
                if agent_id not in defs.all_agents():
                    agent_id = "ceo"
                images = [
                    a for a in attachments
                    if a.get("media_type", "").startswith("image/")
                    and a.get("data")
                ]
                if images:
                    await _handle_vision_message(session, agent_id, text, images)
                elif text:
                    await _handle_message(session, agent_id, text)
                else:
                    continue

            elif msg_type == "model":
                session.model = msg.get("model", "claude")

            elif msg_type == "clear":
                agent_id = msg.get("agent", "ceo")
                state.conversation_histories[agent_id] = []
                state.save_state()
                await session.send({"type": "cleared", "agent": agent_id})

            elif msg_type == "force_complete":
                await _handle_force_complete(session, int(msg.get("task_id", -1)))

            elif msg_type == "reset_task":
                await _handle_reset_task(session, int(msg.get("task_id", -1)))

            elif msg_type == "cancel_worker":
                await _handle_cancel_worker(session, msg.get("agent", ""))

            elif msg_type == "ping":
                await session.send({"type": "pong"})

    except WebSocketDisconnect as exc:
        logger.info("WebSocket disconnected (code=%s reason=%r)", exc.code, exc.reason)
    except Exception as exc:
        logger.exception("WS handler error: %s", exc)
        try:
            await session.send({"type": "error", "agent": "system", "message": str(exc)})
        except Exception:
            pass
    finally:
        _sessions.discard(session)
        session.cancel_all()
