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
                    await self.ws.send_json(data)
            except Exception as exc:
                logger.debug("WS send error (likely disconnected): %s", exc)

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


# ── Message router ─────────────────────────────────────────────────────────────

async def _handle_message(session: Session, agent_id: str, text: str) -> None:
    """Execute a user message to a specific agent."""
    state.record(agent_id, "user", text)
    send = session.make_sender(agent_id)

    await session.send({"type": "thinking", "agent": agent_id})

    full_resp = await run_agent(agent_id, text, send, session.model)

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

        # Send any emails
        for subj, body in deleg_svc.parse_emails(full_resp):
            result = await email_svc.send_mail(f"[Shadow Garden] {subj}", body)
            await session.send({
                "type": "email_sent", "subject": subj,
                "ok": result["ok"], "error": result.get("error", ""),
            })

    state.record(agent_id, "assistant", deleg_svc.clean_response(full_resp))
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
                agent_id = msg.get("agent", "ceo")
                text     = msg.get("text", "").strip()
                if not text:
                    continue
                if agent_id not in defs.all_agents():
                    agent_id = "ceo"
                await _handle_message(session, agent_id, text)

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

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as exc:
        logger.exception("WS handler error: %s", exc)
        try:
            await session.send({"type": "error", "agent": "system", "message": str(exc)})
        except Exception:
            pass
    finally:
        session.cancel_all()
