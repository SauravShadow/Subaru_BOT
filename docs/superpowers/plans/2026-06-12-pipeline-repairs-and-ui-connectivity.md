# Pipeline Repairs & UI Connectivity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make every existing NEXUS backend feature actually work end-to-end and be visible in the UI — service recovery, memory fixes, direct worker chat, work queue, and handlers for all currently-dropped WS events.

**Architecture:** Backend fixes are surgical edits to `app/api/websocket.py`, `app/services/memory.py`, `app/services/email_poller.py`, and `docker-compose.yml`. UI work extends the Zustand store with the missing event cases and adds small HUD panels (BrowserViewport, DesignPreview, SystemVitals) plus an expanded OpsDrawer. No new server processes.

**Tech Stack:** FastAPI, LangGraph, SQLite FTS5, React 18 + zustand + react-three-fiber (existing deps only).

**Project root:** `/mnt/HC_Volume_105874680/virtual-company` — all paths below are relative to it. Backend tests run inside the repo: `python -m pytest tests/ -q`. Always use `127.0.0.1`, never `localhost`, in curl commands.

---

### Task 1: Service recovery — restart policies + bring bark-svc/browser-svc back up

**Files:**
- Modify: `docker-compose.yml`

bark-svc and browser-svc exited 32h ago and never came back because no service has a restart policy.

- [x] **Step 1: Add restart policy to all three services**

In `docker-compose.yml`, add `restart: unless-stopped` under each of the three services (`app` top-level service with `container_name: virtual-company`, `bark-svc`, `browser-svc`), at the same indent level as `container_name`:

```yaml
    restart: unless-stopped
```

- [x] **Step 2: Recreate the stack**

```bash
cd /mnt/HC_Volume_105874680/virtual-company
docker compose up -d
```

Expected: all three containers report `Started` or `Running`.

- [x] **Step 3: Verify all three containers are up and healthy**

```bash
docker ps --format "{{.Names}} {{.Status}}" | grep -E "virtual-company|bark|browser"
docker exec virtual-company curl -s -m 5 http://bark-svc:9001/health
docker exec virtual-company curl -s -m 5 http://browser-svc:9002/health
```

Expected: three `Up` lines; both health curls return JSON (both services define `GET /health`).

- [x] **Step 4: Confirm bark errors stopped**

```bash
docker logs virtual-company --since 2m 2>&1 | grep -c "bark_client.speak failed" || echo OK
```

Expected: `0` or `OK`.

- [x] **Step 5: Commit**

```bash
git add docker-compose.yml
git commit -m "fix: restart policies so bark-svc/browser-svc survive reboots"
```

---

### Task 2: `/api/health` aggregate endpoint

**Files:**
- Modify: `app/api/router.py` (add route near `/api/capabilities`)
- Test: `tests/test_health.py` (create)

The UI (SystemVitals, Task 12) needs one endpoint that reports app/bark/browser/email status.

- [x] **Step 1: Write the failing test**

Create `tests/test_health.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport


@pytest.mark.asyncio
async def test_health_reports_all_services(monkeypatch):
    from app.api import router as router_module

    async def fake_probe(url: str) -> bool:
        return "bark" in url  # bark up, browser down

    monkeypatch.setattr(router_module, "_probe_service", fake_probe)

    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router_module.router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/health")

    assert res.status_code == 200
    body = res.json()
    assert body["app"] is True
    assert body["bark"] is True
    assert body["browser"] is False
    assert "email" in body
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_health.py -v`
Expected: FAIL — `_probe_service` does not exist / 404 on `/api/health`.

- [x] **Step 3: Implement the endpoint**

In `app/api/router.py`, add directly above the `# ── SPA fallback` section (it must come before the catch-all):

```python
# ── Health ─────────────────────────────────────────────────────────────────────

async def _probe_service(url: str) -> bool:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(url)
            return r.status_code == 200
    except Exception:
        return False


@router.get("/api/health")
async def api_health():
    bark_ok, browser_ok = await asyncio.gather(
        _probe_service(f"{config.BARK_SVC_URL}/health"),
        _probe_service(f"{config.BROWSER_SVC_URL}/health"),
    )
    return {
        "app":     True,
        "bark":    bark_ok,
        "browser": browser_ok,
        "email":   all([config.SMTP_USER, config.SMTP_PASS, config.USER_EMAIL]),
    }
```

Note: `config` and `asyncio` are already imported at the top of `router.py`. Confirm `config.BARK_SVC_URL` exists in `app/config.py` (env `BARK_SVC_URL` is set in docker-compose); `BROWSER_SVC_URL` is referenced at `router.py:468` already.

- [x] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_health.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add app/api/router.py tests/test_health.py
git commit -m "feat: /api/health aggregate service status endpoint"
```

---

### Task 3: Memory fixes — FTS5 escaping + WAL/busy_timeout

**Files:**
- Modify: `app/services/memory.py:14-17` (`_conn`), `:20` (`init_db`), `:64-95` (`get_relevant_memories`)
- Test: `tests/test_memory.py` (extend)

Live logs show `fts5: syntax error near ","` (escape regex misses commas/colons/hyphens) and `database is locked` (no WAL, no busy timeout).

- [x] **Step 1: Write the failing tests**

Append to `tests/test_memory.py`:

```python
def test_fts_escape_handles_commas_and_colons():
    from app.services.memory import _fts_escape
    assert _fts_escape('deploy app, port 3030: done') == '"deploy" "app" "port" "3030" "done"'


def test_fts_escape_empty_punctuation_only():
    from app.services.memory import _fts_escape
    assert _fts_escape('?!,;') == ''


def test_query_with_commas_does_not_error(tmp_path, monkeypatch):
    from app.services import memory
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "mem.db")
    memory.init_db()
    memory.save_memory("ceo", "deployed trading dashboard on port 8002")
    rows = memory.get_relevant_memories("ceo", "trading, dashboard: port")
    assert rows and "trading" in rows[0]
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_memory.py -v -k "fts_escape or commas"`
Expected: FAIL — `_fts_escape` not defined; third test raises/returns [] via OperationalError path.

- [x] **Step 3: Implement**

In `app/services/memory.py`, replace `_conn` and add WAL to `init_db`:

```python
def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH), timeout=5.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=5000")
    return c
```

At the top of `init_db()` body, before `executescript`:

```python
    with _conn() as c:
        c.execute("PRAGMA journal_mode=WAL")
```

(keep the existing `executescript` block in the same `with` or a second one — either is fine).

Then in `get_relevant_memories`, replace lines 67-73 (the `if re.search(...)` escaping block) with a call to a new helper, and define the helper above the function:

```python
def _fts_escape(query: str) -> str:
    """Tokenize to alphanumerics and quote each token — immune to FTS5 syntax."""
    tokens = re.findall(r"[A-Za-z0-9_]+", query)
    return " ".join(f'"{t}"' for t in tokens)
```

```python
    escaped_query = _fts_escape(query)
    if not escaped_query:
        return []
```

- [x] **Step 4: Run the full memory test file**

Run: `python -m pytest tests/test_memory.py -v`
Expected: ALL PASS (existing tests must keep passing — quoted-token AND semantics are a superset of the old behaviour for plain queries).

- [x] **Step 5: Commit**

```bash
git add app/services/memory.py tests/test_memory.py
git commit -m "fix: FTS5 token escaping + WAL/busy_timeout for memory DB"
```

---

### Task 4: Direct worker chat — honor the `agent` field on WS messages

**Files:**
- Modify: `app/api/websocket.py` (`ws_endpoint` message branch; add `_run_direct`)
- Test: `tests/test_websocket.py` (extend)

The UI sends `{type:'message', agent:'backend', text}` from `AgentDetailView`, but the backend always runs the CEO graph. Messages to a specific worker must run that worker directly.

- [x] **Step 1: Write the failing test**

Append to `tests/test_websocket.py`:

```python
import asyncio
import pytest
from app.api import websocket as ws_module


@pytest.mark.asyncio
async def test_run_direct_calls_worker_and_broadcasts_lifecycle(monkeypatch):
    events = []

    async def fake_broadcast(data):
        events.append(data)

    called = {}

    async def fake_run_agent(agent_id, prompt, send, model="claude"):
        called["agent"] = agent_id
        called["prompt"] = prompt
        return "done"

    monkeypatch.setattr(ws_module, "broadcast_event", fake_broadcast)
    import app.agents.runner as runner
    monkeypatch.setattr(runner, "run_agent", fake_run_agent)

    await ws_module._run_direct("backend", "fix the API", "claude")

    assert called["agent"] == "backend"
    types = [e["type"] for e in events]
    assert types[0] == "delegation"
    assert types[-1] == "worker_done"


@pytest.mark.asyncio
async def test_run_direct_rejects_unknown_agent(monkeypatch):
    events = []

    async def fake_broadcast(data):
        events.append(data)

    monkeypatch.setattr(ws_module, "broadcast_event", fake_broadcast)
    await ws_module._run_direct("nonexistent_agent_xyz", "hi", "claude")
    assert events and events[0]["type"] == "error"
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_websocket.py -v -k run_direct`
Expected: FAIL — `_run_direct` does not exist.

- [x] **Step 3: Implement `_run_direct`**

In `app/api/websocket.py`, add below `_run_and_stream`:

```python
async def _run_direct(agent_id: str, task: str, model: str) -> None:
    """1:1 chat with a single agent — bypasses the CEO orchestration graph."""
    if agent_id not in defs.all_agents():
        await broadcast_event({"type": "error", "agent": "ceo",
                               "message": f"Unknown agent '{agent_id}'"})
        return
    from app.agents.runner import run_agent
    await broadcast_event({"type": "delegation", "agent": agent_id})
    try:
        await run_agent(agent_id, task, broadcast_event, model)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("direct chat error for %s", agent_id)
        await broadcast_event({"type": "error", "agent": agent_id,
                               "message": str(exc)[:200]})
    finally:
        await broadcast_event({"type": "worker_done", "agent": agent_id})
```

Note: `run_agent` must be imported *inside* the function (as shown) so the test's `monkeypatch.setattr(runner, "run_agent", ...)` takes effect.

- [x] **Step 4: Route on the `agent` field**

In `ws_endpoint`, replace the `if msg_type == "message":` branch:

```python
            if msg_type == "message":
                target = msg.get("agent") or "ceo"
                if target == "ceo":
                    t = asyncio.create_task(
                        _run_and_stream(msg["text"], thread_id, session.model)
                    )
                else:
                    t = asyncio.create_task(
                        _run_direct(target, msg["text"], session.model)
                    )
                _active_runs[thread_id] = t
```

- [x] **Step 5: Run the websocket test file**

Run: `python -m pytest tests/test_websocket.py -v`
Expected: ALL PASS.

- [x] **Step 6: Commit**

```bash
git add app/api/websocket.py tests/test_websocket.py
git commit -m "fix: direct 1:1 worker chat — honor agent field on ws messages"
```

---

### Task 5: Emit `queue_update` events from the graph stream

**Files:**
- Modify: `app/api/websocket.py` (add `_queues` + `_queue_updates`; call from `_run_and_stream`)
- Test: `tests/graph/test_event_translation.py` (extend)

The UI's SmartIsland QUEUE tab listens for `queue_update` but the backend never sends it. Delegations are available in the `ceo_node` `on_chain_end` output.

- [x] **Step 1: Write the failing tests**

Append to `tests/graph/test_event_translation.py` (reuse the `_evt` helper defined at the top of that file):

```python
def test_ceo_end_emits_queue_from_delegations():
    from app.api.websocket import _queue_updates, _queues
    _queues.clear()
    event = _evt(
        "on_chain_end", "ceo_node",
        metadata={"langgraph_checkpoint_ns": "ceo_node"},
        data={"output": {"ceo_response": "ok", "delegations": [
            {"agent": "backend", "task": "build api"},
            {"agent": "qa", "task": "write tests"},
        ]}},
    )
    msg = _queue_updates(event, "ws_q1")
    assert msg["type"] == "queue_update"
    assert len(msg["queue"]) == 2
    assert msg["queue"][0] == {
        "id": "ws_q1:0", "task": "build api", "status": "active", "agent": "backend",
    }


def test_worker_output_end_marks_completed():
    from app.api.websocket import _queue_updates, _queues
    _queues.clear()
    _queues["ws_q2"] = [
        {"id": "ws_q2:0", "task": "build api", "status": "active", "agent": "backend"},
    ]
    event = _evt(
        "on_chain_end", "output_node",
        metadata={"langgraph_checkpoint_ns": "backend:sub1"},
        data={"output": {}},
    )
    msg = _queue_updates(event, "ws_q2")
    assert msg["type"] == "queue_update"
    assert msg["queue"][0]["status"] == "completed"


def test_non_queue_events_return_none():
    from app.api.websocket import _queue_updates
    event = _evt("on_tool_start", "bash",
                 metadata={"langgraph_checkpoint_ns": "backend:x"},
                 data={"input": {"command": "ls"}})
    assert _queue_updates(event, "ws_q3") is None
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/graph/test_event_translation.py -v -k queue`
Expected: FAIL — `_queue_updates` not defined.

- [x] **Step 3: Implement**

In `app/api/websocket.py`, below the `_checkpoint_counters` declarations add:

```python
_queues: dict[str, list[dict]] = {}  # thread_id → live work-queue items
```

Below `_translate_event`, add:

```python
def _queue_updates(event: dict, thread_id: str) -> dict | None:
    """Maintain a per-thread work queue from delegations; emit queue_update."""
    kind = event.get("event", "")
    name = event.get("name", "")
    data = event.get("data", {})

    if kind == "on_chain_end" and name == "ceo_node":
        output = data.get("output") or {}
        delegations = output.get("delegations", []) if isinstance(output, dict) else []
        _queues[thread_id] = [
            {"id": f"{thread_id}:{i}", "task": d["task"][:100],
             "status": "active", "agent": d["agent"]}
            for i, d in enumerate(delegations)
        ]
        return {"type": "queue_update", "queue": _queues[thread_id],
                "thread_id": thread_id}

    if kind == "on_chain_end" and name == "output_node":
        agent_id = _extract_agent_id(event.get("metadata", {}))
        queue = _queues.get(thread_id)
        if not queue:
            return None
        changed = False
        for item in queue:
            if item["agent"] == agent_id and item["status"] == "active":
                item["status"] = "completed"
                changed = True
        if changed:
            return {"type": "queue_update", "queue": queue, "thread_id": thread_id}

    return None
```

In `_run_and_stream`, inside the `async for event ...` loop, after the existing `msg = _translate_event(...)` block:

```python
            qmsg = _queue_updates(event, thread_id)
            if qmsg:
                await broadcast_event(qmsg)
```

And in the `finally:` block add `_queues.pop(thread_id, None)` before `bcast.unregister(thread_id)`.

- [x] **Step 4: Run the full translation test file**

Run: `python -m pytest tests/graph/test_event_translation.py -v`
Expected: ALL PASS.

- [x] **Step 5: Commit**

```bash
git add app/api/websocket.py tests/graph/test_event_translation.py
git commit -m "feat: emit queue_update events — SmartIsland queue tab now live"
```

---

### Task 6: Real `/api/email-tasks` — track email graph activity

**Files:**
- Modify: `app/services/email_poller.py`, `app/api/router.py:130-132`
- Test: `tests/graph/test_email_graph.py` (extend)

The email pipeline runs but is invisible: `/api/email-tasks` returns `[]` hardcoded.

- [x] **Step 1: Write the failing test**

Append to `tests/graph/test_email_graph.py`:

```python
def test_email_task_tracking_records_and_lists():
    from app.services import email_poller as ep
    ep._email_tasks.clear()
    ep._track_task("email_abc", {"subject": "Deploy app", "from_email": "x@y.com"},
                   status="processing")
    ep._track_task("email_abc", {"subject": "Deploy app", "from_email": "x@y.com"},
                   status="waiting_reply")
    tasks = ep.list_tasks()
    assert len(tasks) == 1
    assert tasks[0]["id"] == "email_abc"
    assert tasks[0]["status"] == "waiting_reply"
    assert tasks[0]["subject"] == "Deploy app"
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/graph/test_email_graph.py -v -k tracking`
Expected: FAIL — `_email_tasks` / `_track_task` not defined.

- [x] **Step 3: Implement tracking in `email_poller.py`**

Add near the top of `app/services/email_poller.py` (it already imports `logging`; add `from datetime import datetime` to imports):

```python
_email_tasks: dict[str, dict] = {}  # thread_id → task summary (runtime cache)


def _track_task(thread_id: str, email: dict, status: str) -> None:
    _email_tasks[thread_id] = {
        "id":      thread_id,
        "subject": email.get("subject", "(no subject)"),
        "from":    email.get("from_email", ""),
        "status":  status,
        "updated": datetime.now().isoformat(),
    }


def list_tasks() -> list[dict]:
    return sorted(_email_tasks.values(), key=lambda t: t["updated"], reverse=True)[:20]
```

In `poll_once`, inside the `for email in emails:` loop, instrument both branches:

```python
        thread_id = f"email_{email['message_id']}"
        try:
            cfg = {"configurable": {"thread_id": thread_id}}
            graph_state = await email_graph.aget_state(cfg)
            _track_task(thread_id, email,
                        "resuming" if graph_state.next else "processing")
            if graph_state.next:
                reply_body = _extract_reply_body(email.get("body", ""))
                await email_graph.ainvoke({"user_reply": reply_body}, cfg)
            else:
                await email_graph.ainvoke(
                    {
                        "email": email,
                        "is_owner": _is_trusted(email.get("from_email", "")),
                        "sent_message_ids": [],
                    },
                    cfg,
                )
            new_state = await email_graph.aget_state(cfg)
            _track_task(thread_id, email,
                        "waiting_reply" if new_state.next else "done")
        except Exception as exc:
            _track_task(thread_id, email, "error")
            logger.warning("email dispatch error for %s: %s", thread_id, exc)
```

- [x] **Step 4: Wire the endpoint**

In `app/api/router.py`, replace the stub at lines 130-132:

```python
@router.get("/api/email-tasks")
async def api_email_tasks():
    from app.services import email_poller
    return email_poller.list_tasks()
```

- [x] **Step 5: Run tests**

Run: `python -m pytest tests/graph/test_email_graph.py -v`
Expected: ALL PASS.

- [x] **Step 6: Commit**

```bash
git add app/services/email_poller.py app/api/router.py tests/graph/test_email_graph.py
git commit -m "feat: live email-task tracking — /api/email-tasks returns real data"
```

---

### Task 7: UI store — handle every dropped WS event

**Files:**
- Modify: `nexus-ui/src/types.ts`, `nexus-ui/src/store.ts`

One task because all changes land in two files and ship atomically. No unit-test runner is configured for nexus-ui; verification is `npm run build` (tsc) + the E2E task.

- [x] **Step 1: Extend types.ts**

In `nexus-ui/src/types.ts`, extend the `Notification` type union and add `BrowserView`:

```typescript
export interface Notification {
  id: string
  text: string
  ts: number
  type: 'done' | 'delegation' | 'queue' | 'message'
      | 'routine' | 'email' | 'approval' | 'system'
}

export interface BrowserView {
  image: string          // base64 (no data: prefix)
  mime: 'image/jpeg' | 'image/png'
  url: string
  caption: string
  ts: number
}
```

(Keep all existing exports. If `Notification` already exists, only widen its `type` union.)

- [x] **Step 2: Add store fields + actions**

In `nexus-ui/src/store.ts`, add to the `NexusStore` interface:

```typescript
  browserView: BrowserView | null
  browserVisible: boolean
  designPreviewTs: number | null
  designPreviewVisible: boolean
  pendingApprovals: number

  setBrowserVisible: (v: boolean) => void
  setDesignPreviewVisible: (v: boolean) => void
  setPendingApprovals: (n: number) => void
```

Import `BrowserView` from `./types`. Add the initial values + actions in the `create` call:

```typescript
  browserView: null,
  browserVisible: false,
  designPreviewTs: null,
  designPreviewVisible: false,
  pendingApprovals: 0,

  setBrowserVisible: (v) => set({ browserVisible: v }),
  setDesignPreviewVisible: (v) => set({ designPreviewVisible: v }),
  setPendingApprovals: (n) => set({ pendingApprovals: n }),
```

- [x] **Step 3: Patch the assistant case to keep image blocks**

Replace the body of `case 'assistant'` content extraction so image blocks become renderable markers instead of being dropped:

```typescript
        case 'assistant': {
          if (!agentId) break
          const raw = (event.message as { content?: unknown })?.content
          let content = ''
          if (typeof raw === 'string') {
            content = raw
          } else if (Array.isArray(raw)) {
            content = (raw as Array<{ type?: string; text?: string; media_type?: string; data?: string }>)
              .map(b => {
                if (b.type === 'text') return b.text ?? ''
                if (b.type === 'image' && b.data) return ` img:${b.media_type ?? 'image/png'}:${b.data}`
                return ''
              })
              .join('')
          }
          if (!content.trim()) break
          const prev3 = agents[agentId] ?? defaultAgent(agentId)
          updateAgent(agentId, {
            recentOutput: [...prev3.recentOutput, content].slice(-500)
          })
          break
        }
```

- [x] **Step 4: Add the missing event cases**

Inside the same `switch (type)`, add before the final `case 'done'`:

```typescript
        case 'backend_status': {
          const backend = event.backend as WsModel | undefined
          if (backend) return { agents, edges, notifications, wsModel: backend }
          break
        }

        case 'browser_navigated':
          if (event.screenshot) {
            return {
              agents, edges, notifications,
              browserVisible: true,
              browserView: {
                image: event.screenshot as string, mime: 'image/png' as const,
                url: (event.url as string) ?? '', caption: (event.title as string) ?? '',
                ts: Date.now(),
              },
            }
          }
          break

        case 'browser_frame':
          if (event.frame) {
            return {
              agents, edges, notifications,
              browserVisible: true,
              browserView: {
                image: event.frame as string, mime: 'image/jpeg' as const,
                url: (event.url as string) ?? '', caption: (event.action as string) ?? '',
                ts: Date.now(),
              },
            }
          }
          break

        case 'browser_result':
          addNotif(`Maya: ${String(event.summary ?? event.message ?? 'browser job finished').slice(0, 80)}`, 'done')
          break

        case 'design_preview_updated':
          addNotif('Design preview updated', 'system')
          return { agents, edges, notifications, designPreviewTs: Date.now(), designPreviewVisible: true }

        case 'routine_completed':
          addNotif(`Routine ${event.routine_id}: ${event.status}`, 'routine')
          break

        case 'standup':
          addNotif('Standup briefing generated', 'routine')
          break

        case 'email_sent':
          addNotif(`Email sent: ${String(event.subject ?? '').slice(0, 60)}`, 'email')
          break

        case 'source_file_modified':
          addNotif(`${event.agent} modified ${event.path} (${event.zone})`, 'system')
          break

        case 'approval_requested':
          addNotif(`Approval needed: ${event.file_path}`, 'approval')
          return { agents, edges, notifications, pendingApprovals: state.pendingApprovals + 1 }

        case 'approval_applied':
        case 'approval_denied':
          addNotif(`Approval ${event.approval_id}: ${type === 'approval_applied' ? 'applied' : 'denied'}`, 'approval')
          return { agents, edges, notifications, pendingApprovals: Math.max(0, state.pendingApprovals - 1) }
```

- [x] **Step 5: Add the speech-fallback emitter**

Below the existing audio listener block in `store.ts` (module level, next to `onAudioEvent`):

```typescript
// Speech-synthesis fallback channel — fired when an assistant reply arrives
// without Bark audio (bark_ok !== true). useVoice decides whether to speak it.
type SpeechListener = (text: string) => void
const _speechListeners: SpeechListener[] = []
export function onSpeechFallback(cb: SpeechListener) { _speechListeners.push(cb) }
export function offSpeechFallback(cb: SpeechListener) {
  const i = _speechListeners.indexOf(cb)
  if (i >= 0) _speechListeners.splice(i, 1)
}
```

In `connectWebSocket`'s `onmessage`, after `useNexusStore.getState().handleEvent(data)`:

```typescript
      if (data.type === 'assistant' && data.bark_ok !== true) {
        const raw = (data.message as { content?: Array<{ type?: string; text?: string }> })?.content
        const text = Array.isArray(raw)
          ? raw.filter(b => b.type === 'text').map(b => b.text ?? '').join(' ')
          : typeof raw === 'string' ? raw : ''
        if (text.trim()) _speechListeners.forEach(cb => cb(text))
      }
```

- [x] **Step 6: Typecheck**

Run: `cd nexus-ui && npx tsc --noEmit`
Expected: no errors.

- [x] **Step 7: Commit**

```bash
git add nexus-ui/src/types.ts nexus-ui/src/store.ts
git commit -m "feat(ui): handle all backend WS events — browser frames, images, approvals, routine/email notifications"
```

---

### Task 8: Web Speech synthesis fallback in `useVoice`

**Files:**
- Modify: `nexus-ui/src/hooks/useVoice.ts`

When Bark is down (`bark_ok` false), responses must still be spoken via the browser's built-in `speechSynthesis` — zero server cost.

- [x] **Step 1: Subscribe to the fallback channel**

In `useVoice.ts`, import the new emitter and add an effect after the existing audio-listener effect:

```typescript
import { onAudioEvent, offAudioEvent, onSpeechFallback, offSpeechFallback } from '../store'
```

```typescript
  // Web Speech fallback when Bark produced no audio
  useEffect(() => {
    if (!ttsEnabled) return
    const cb = (text: string) => {
      if (AudioQueue._playing) return                 // Bark audio wins
      if (!('speechSynthesis' in window)) return
      const clean = text
        .replace(/```[\s\S]*?```/g, ' code block omitted ')
        .replace(/[*_#>`]/g, '')
        .slice(0, 300)
      if (!clean.trim()) return
      window.speechSynthesis.cancel()
      const utter = new SpeechSynthesisUtterance(clean)
      utter.rate = 1.05
      utter.onstart = () => setIsSpeaking(true)
      utter.onend = () => setIsSpeaking(false)
      window.speechSynthesis.speak(utter)
    }
    onSpeechFallback(cb)
    return () => offSpeechFallback(cb)
  }, [ttsEnabled])
```

- [x] **Step 2: Typecheck**

Run: `cd nexus-ui && npx tsc --noEmit`
Expected: no errors.

- [x] **Step 3: Commit**

```bash
git add nexus-ui/src/hooks/useVoice.ts
git commit -m "feat(ui): speechSynthesis fallback when Bark audio unavailable"
```

---

### Task 9: AgentDetailView — history hydration + image rendering

**Files:**
- Modify: `nexus-ui/src/components/AgentDetailView.tsx`

Panels are empty on reload (`/api/chat/{id}/history` never fetched) and generated images (Task 7's ` img:` markers) need rendering.

- [x] **Step 1: Hydrate history on open**

In `AgentDetailView.tsx`, add a store action call via direct mutation of agent output. Add this effect after the entrance-animation effect (uses `useNexusStore.setState` — import is already there via `useNexusStore`):

```typescript
  // Hydrate conversation history once, only if the terminal is empty
  useEffect(() => {
    if (!selectedId || !agent || agent.recentOutput.length > 0) return
    fetch(`/api/chat/${selectedId}/history`)
      .then(r => r.json())
      .then((history: Array<{ role: string; content: string }>) => {
        if (!Array.isArray(history) || history.length === 0) return
        const lines = history.slice(-30).map(m =>
          m.role === 'user' ? `> you: ${m.content}` : m.content)
        useNexusStore.setState(s => ({
          agents: {
            ...s.agents,
            [selectedId]: {
              ...s.agents[selectedId],
              recentOutput: s.agents[selectedId].recentOutput.length === 0
                ? lines
                : s.agents[selectedId].recentOutput,
            },
          },
        }))
      })
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId])
```

- [x] **Step 2: Render image markers and user lines in the terminal**

Replace the terminal line renderer (the `agent.recentOutput.map(...)` block):

```typescript
            agent.recentOutput.map((line, i) => {
              if (line.startsWith(' img:')) {
                const rest = line.slice(5)
                const sep = rest.indexOf(':')
                const mime = rest.slice(0, sep)
                const data = rest.slice(sep + 1)
                return (
                  <img
                    key={i}
                    src={`data:${mime};base64,${data}`}
                    alt="generated"
                    style={{ maxWidth: '100%', borderRadius: 6, margin: '6px 0', border: `1px solid ${color}44` }}
                  />
                )
              }
              const isUser = line.startsWith('> you:')
              return (
                <div key={i} style={{
                  color: (line.startsWith('Tool:') || line.startsWith('> Tool:')) ? color
                    : isUser ? '#64748b' : '#e2e8f0',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                }}>
                  {line}
                </div>
              )
            })
```

- [x] **Step 3: Typecheck + commit**

```bash
cd nexus-ui && npx tsc --noEmit && cd ..
git add nexus-ui/src/components/AgentDetailView.tsx
git commit -m "feat(ui): hydrate chat history on open + render generated images"
```

---

### Task 10: BrowserViewport HUD panel (Maya's live view)

**Files:**
- Create: `nexus-ui/src/components/BrowserViewport.tsx`
- Modify: `nexus-ui/src/components/NexusScene.tsx`

Live CDP frames already reach the store (Task 7). Show them.

- [x] **Step 1: Create the component**

```tsx
// nexus-ui/src/components/BrowserViewport.tsx
import { useNexusStore } from '../store'

const VIOLET = '#8b5cf6'

export function BrowserViewport() {
  const view    = useNexusStore(s => s.browserView)
  const visible = useNexusStore(s => s.browserVisible)
  const setVisible = useNexusStore(s => s.setBrowserVisible)

  if (!view || !visible) return null

  return (
    <div style={{
      position: 'fixed',
      top: 16,
      right: 16,
      width: 380,
      zIndex: 120,
      background: 'rgba(8, 14, 28, 0.92)',
      backdropFilter: 'blur(20px)',
      border: `1px solid ${VIOLET}66`,
      boxShadow: `0 0 32px ${VIOLET}33`,
      borderRadius: 10,
      overflow: 'hidden',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '8px 12px', borderBottom: `1px solid ${VIOLET}33`,
      }}>
        <span style={{ width: 7, height: 7, borderRadius: '50%', background: VIOLET, boxShadow: `0 0 6px ${VIOLET}` }} />
        <span style={{
          flex: 1, fontFamily: 'Orbitron, sans-serif', fontSize: 10,
          color: VIOLET, letterSpacing: '0.1em',
        }}>
          MAYA — LIVE BROWSER
        </span>
        <button onClick={() => setVisible(false)} style={{
          background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', fontSize: 13,
        }}>✕</button>
      </div>
      <img
        src={`data:${view.mime};base64,${view.image}`}
        alt="browser"
        style={{ width: '100%', display: 'block' }}
      />
      <div style={{
        padding: '6px 12px', fontFamily: 'JetBrains Mono, monospace',
        fontSize: 10, color: '#94a3b8',
        whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
      }}>
        {view.caption ? `${view.caption} · ` : ''}{view.url}
      </div>
    </div>
  )
}
```

- [x] **Step 2: Mount it**

In `NexusScene.tsx`: `import { BrowserViewport } from './BrowserViewport'` and render `<BrowserViewport />` next to `<ModelPill />` in the HUD layer.

- [x] **Step 3: Typecheck + commit**

```bash
cd nexus-ui && npx tsc --noEmit && cd ..
git add nexus-ui/src/components/BrowserViewport.tsx nexus-ui/src/components/NexusScene.tsx
git commit -m "feat(ui): live browser viewport panel fed by browser_frame events"
```

---

### Task 11: DesignPreview panel (Emilia's live preview)

**Files:**
- Create: `nexus-ui/src/components/DesignPreviewPanel.tsx`
- Modify: `nexus-ui/src/components/NexusScene.tsx`

The preview HTML is served at `/static/previews/index.html` (`browser.py:write_preview`); `design_preview_updated` now sets `designPreviewTs`.

- [x] **Step 1: Create the component**

```tsx
// nexus-ui/src/components/DesignPreviewPanel.tsx
import { useNexusStore } from '../store'

const PINK = '#ec4899'

export function DesignPreviewPanel() {
  const ts      = useNexusStore(s => s.designPreviewTs)
  const visible = useNexusStore(s => s.designPreviewVisible)
  const setVisible = useNexusStore(s => s.setDesignPreviewVisible)

  if (!ts || !visible) return null

  return (
    <div style={{
      position: 'fixed',
      bottom: 16,
      left: 16,
      width: 420,
      height: 320,
      zIndex: 120,
      background: 'rgba(8, 14, 28, 0.92)',
      backdropFilter: 'blur(20px)',
      border: `1px solid ${PINK}66`,
      boxShadow: `0 0 32px ${PINK}26`,
      borderRadius: 10,
      overflow: 'hidden',
      display: 'flex',
      flexDirection: 'column',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '8px 12px', borderBottom: `1px solid ${PINK}33`,
      }}>
        <span style={{ width: 7, height: 7, borderRadius: '50%', background: PINK, boxShadow: `0 0 6px ${PINK}` }} />
        <span style={{ flex: 1, fontFamily: 'Orbitron, sans-serif', fontSize: 10, color: PINK, letterSpacing: '0.1em' }}>
          EMILIA — DESIGN PREVIEW
        </span>
        <a href={`/static/previews/index.html?t=${ts}`} target="_blank" rel="noreferrer"
           style={{ color: '#64748b', fontSize: 10, textDecoration: 'none', marginRight: 8 }}>
          open ↗
        </a>
        <button onClick={() => setVisible(false)} style={{
          background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', fontSize: 13,
        }}>✕</button>
      </div>
      <iframe
        key={ts}
        src={`/static/previews/index.html?t=${ts}`}
        title="design preview"
        sandbox="allow-scripts"
        style={{ flex: 1, border: 'none', background: '#fff' }}
      />
    </div>
  )
}
```

- [x] **Step 2: Mount in `NexusScene.tsx`** (same pattern as Task 10): `<DesignPreviewPanel />` in the HUD layer.

- [x] **Step 3: Typecheck + commit**

```bash
cd nexus-ui && npx tsc --noEmit && cd ..
git add nexus-ui/src/components/DesignPreviewPanel.tsx nexus-ui/src/components/NexusScene.tsx
git commit -m "feat(ui): live design preview panel on design_preview_updated"
```

---

### Task 12: SystemVitals HUD (health + storage)

**Files:**
- Create: `nexus-ui/src/components/SystemVitals.tsx`
- Modify: `nexus-ui/src/components/NexusScene.tsx`

- [x] **Step 1: Create the component** (polls `/api/health` + `/api/storage` every 60s — trivial server load)

```tsx
// nexus-ui/src/components/SystemVitals.tsx
import { useEffect, useState } from 'react'

interface Health { app: boolean; bark: boolean; browser: boolean; email: boolean }
interface Storage { used_gb: number; max_gb: number; percent: number }

function Dot({ ok, label }: { ok: boolean; label: string }) {
  const c = ok ? '#22c55e' : '#ef4444'
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, marginRight: 10 }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: c, boxShadow: `0 0 5px ${c}` }} />
      <span style={{ color: '#64748b', fontSize: 9 }}>{label}</span>
    </span>
  )
}

export function SystemVitals() {
  const [health, setHealth] = useState<Health | null>(null)
  const [storage, setStorage] = useState<Storage | null>(null)

  useEffect(() => {
    const load = () => {
      fetch('/api/health').then(r => r.json()).then(setHealth).catch(() => setHealth(null))
      fetch('/api/storage').then(r => r.json()).then(setStorage).catch(() => {})
    }
    load()
    const id = setInterval(load, 60_000)
    return () => clearInterval(id)
  }, [])

  return (
    <div style={{
      position: 'fixed', bottom: 16, left: '50%', transform: 'translateX(-50%)',
      zIndex: 40, padding: '6px 14px',
      background: 'rgba(8, 14, 28, 0.85)', backdropFilter: 'blur(12px)',
      border: '1px solid rgba(0, 240, 255, 0.12)', borderRadius: 8,
      fontFamily: 'JetBrains Mono, monospace', whiteSpace: 'nowrap',
    }}>
      <Dot ok={!!health?.app} label="CORE" />
      <Dot ok={!!health?.bark} label="VOICE" />
      <Dot ok={!!health?.browser} label="BROWSER" />
      <Dot ok={!!health?.email} label="EMAIL" />
      {storage && (
        <span style={{ color: storage.percent > 85 ? '#ef4444' : '#64748b', fontSize: 9 }}>
          DISK {storage.percent}%
        </span>
      )}
    </div>
  )
}
```

- [x] **Step 2: Mount in `NexusScene.tsx`** HUD layer: `<SystemVitals />`.

- [x] **Step 3: Typecheck + commit**

```bash
cd nexus-ui && npx tsc --noEmit && cd ..
git add nexus-ui/src/components/SystemVitals.tsx nexus-ui/src/components/NexusScene.tsx
git commit -m "feat(ui): system vitals strip — service health + disk usage"
```

---

### Task 13: OpsDrawer expansion — routines CRUD + logs, skill actions, EMAIL & TEAM tabs, approvals badge

**Files:**
- Modify: `nexus-ui/src/components/OpsDrawer.tsx`, `nexus-ui/src/components/NexusScene.tsx`

All endpoints already exist; this is pure UI. Keep the existing visual language (Orbitron headers, `#0f172a` cards).

- [x] **Step 1: Add tabs + state**

In `OpsDrawer.tsx` change `type OpsTab = 'routines' | 'skills' | 'approvals' | 'email' | 'team'`, add tab buttons `EMAIL` and `TEAM`, and extend `fetchAll` to also load:

```typescript
      fetch('/api/email-tasks').then(r => r.json()).catch(() => []),
      fetch('/api/agents').then(r => r.json()).catch(() => ({})),
```

storing into `const [emailTasks, setEmailTasks] = useState<EmailTask[]>([])` and `const [agents, setAgents] = useState<Record<string, AgentInfo>>({})` with:

```typescript
interface EmailTask { id: string; subject: string; from: string; status: string; updated: string }
interface AgentInfo { name: string; title: string; description: string }
```

- [x] **Step 2: Routines — create / delete / logs**

Add handlers + a minimal creation form at the top of the routines tab:

```typescript
  const [newRoutine, setNewRoutine] = useState({ id: '', name: '', agent: 'ceo', schedule: '0 9 * * *', prompt: '' })
  const [logsFor, setLogsFor] = useState<string | null>(null)
  const [logs, setLogs] = useState<Array<{ status: string; output: string; timestamp: string }>>([])

  const createRoutine = async () => {
    if (!newRoutine.id || !newRoutine.name || !newRoutine.prompt) return
    await fetch('/api/routines', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newRoutine),
    }).catch(() => null)
    setNewRoutine({ id: '', name: '', agent: 'ceo', schedule: '0 9 * * *', prompt: '' })
    fetchAll()
  }

  const deleteRoutine = async (id: string) => {
    await fetch(`/api/routines/${id}`, { method: 'DELETE' }).catch(() => null)
    fetchAll()
  }

  const toggleRoutine = async (r: Routine) => {
    await fetch(`/api/routines/${r.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: !r.enabled }),
    }).catch(() => null)
    fetchAll()
  }

  const showLogs = async (id: string) => {
    if (logsFor === id) { setLogsFor(null); return }
    const data = await fetch(`/api/routines/${id}/logs?limit=5`).then(r => r.json()).catch(() => [])
    setLogs(Array.isArray(data) ? data : [])
    setLogsFor(id)
  }
```

Render in each routine card, next to RUN: `LOGS` button (`onClick={() => showLogs(r.id)}`), `ON/OFF` toggle (`onClick={() => toggleRoutine(r)}`, label `r.enabled ? 'ON' : 'OFF'`, green/grey), `✕` delete (`onClick={() => deleteRoutine(r.id)}`, red border). When `logsFor === r.id`, render under the card:

```tsx
                {logsFor === r.id && logs.map((l, i) => (
                  <div key={i} style={{ background: '#020408', border: '1px solid #1e293b', borderRadius: 4, padding: 6, fontSize: 10, color: '#94a3b8', fontFamily: 'JetBrains Mono, monospace', marginTop: 4 }}>
                    <span style={{ color: l.status === 'success' ? '#22c55e' : '#ef4444' }}>{l.status}</span>
                    {' · '}{l.timestamp.slice(0, 16).replace('T', ' ')}
                    <div style={{ whiteSpace: 'pre-wrap', maxHeight: 80, overflowY: 'auto' }}>{l.output.slice(0, 300)}</div>
                  </div>
                ))}
```

The creation form (top of routines tab) — five inputs bound to `newRoutine` fields (id, name, schedule, agent, prompt) styled like the chat input, plus a `+ CREATE` button calling `createRoutine`.

- [x] **Step 3: Skills — rollback + delete buttons**

In each learned-skill card add:

```tsx
                <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                  <button onClick={async () => { await fetch(`/api/skills/${s.id}/rollback`, { method: 'POST' }).catch(() => null); fetchAll() }}
                    style={{ background: 'none', border: '1px solid #334155', color: '#94a3b8', borderRadius: 5, padding: '2px 8px', fontSize: 10, cursor: 'pointer' }}>
                    ROLLBACK
                  </button>
                  <button onClick={async () => { await fetch(`/api/skills/${s.id}`, { method: 'DELETE' }).catch(() => null); fetchAll() }}
                    style={{ background: 'none', border: '1px solid #ef444444', color: '#ef4444', borderRadius: 5, padding: '2px 8px', fontSize: 10, cursor: 'pointer' }}>
                    DELETE
                  </button>
                </div>
```

- [x] **Step 4: EMAIL tab**

```tsx
        {!loading && tab === 'email' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <button onClick={async () => { await fetch('/api/email-tasks/poll', { method: 'POST' }).catch(() => null); setTimeout(fetchAll, 2000) }}
              style={{ background: `${ACCENT}18`, border: `1px solid ${ACCENT}44`, color: ACCENT, borderRadius: 5, padding: '4px 10px', fontSize: 10, cursor: 'pointer', fontFamily: 'Orbitron, sans-serif', alignSelf: 'flex-start' }}>
              POLL INBOX NOW
            </button>
            {emailTasks.length === 0 && (
              <div style={{ color: '#334155', fontSize: 12, fontStyle: 'italic', padding: '24px 0' }}>No email tasks yet</div>
            )}
            {emailTasks.map(t => (
              <div key={t.id} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 14px' }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <span style={{ flex: 1, color: '#e2e8f0', fontSize: 12, fontFamily: 'JetBrains Mono, monospace' }}>{t.subject}</span>
                  <StatusBadge status={t.status === 'done' ? 'ok' : t.status === 'error' ? 'error' : t.status} />
                </div>
                <div style={{ color: '#475569', fontSize: 10, marginTop: 2 }}>{t.from} · {t.updated.slice(0, 16).replace('T', ' ')}</div>
              </div>
            ))}
          </div>
        )}
```

- [x] **Step 5: TEAM tab (hire/fire)**

```tsx
        {!loading && tab === 'team' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {Object.entries(agents).map(([id, a]) => (
              <div key={id} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 8 }}>
                <div style={{ flex: 1 }}>
                  <div style={{ color: '#e2e8f0', fontSize: 12, fontWeight: 600 }}>{a.name}</div>
                  <div style={{ color: '#64748b', fontSize: 10 }}>{a.title}</div>
                </div>
                {!['ceo', 'backend', 'frontend', 'qa', 'devops', 'browser'].includes(id) && (
                  <button onClick={async () => { await fetch(`/api/hire/${id}`, { method: 'DELETE' }).catch(() => null); fetchAll() }}
                    style={{ background: 'none', border: '1px solid #ef444444', color: '#ef4444', borderRadius: 5, padding: '2px 8px', fontSize: 10, cursor: 'pointer' }}>
                    FIRE
                  </button>
                )}
              </div>
            ))}
            <HireForm onHired={fetchAll} />
          </div>
        )}
```

With `HireForm` defined in the same file:

```tsx
function HireForm({ onHired }: { onHired: () => void }) {
  const [form, setForm] = useState({ id: '', name: '', role: '', stack: '' })
  const inputStyle = {
    background: '#0f172a', border: '1px solid #334155', borderRadius: 5,
    color: '#e2e8f0', padding: '5px 8px', fontSize: 11, outline: 'none', width: '100%',
  } as const
  const hire = async () => {
    if (!form.id || !form.name || !form.role) return
    await fetch('/api/hire', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...form, title: form.role }),
    }).catch(() => null)
    setForm({ id: '', name: '', role: '', stack: '' })
    onHired()
  }
  return (
    <div style={{ background: '#0f172a', border: '1px dashed #334155', borderRadius: 8, padding: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
      <span style={{ fontFamily: 'Orbitron, sans-serif', color: '#64748b', fontSize: 10, letterSpacing: '0.1em' }}>HIRE CONTRACTOR</span>
      <input style={inputStyle} placeholder="id (e.g. data_analyst)" value={form.id} onChange={e => setForm({ ...form, id: e.target.value })} />
      <input style={inputStyle} placeholder="Name" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} />
      <input style={inputStyle} placeholder="Role (e.g. Data Analyst)" value={form.role} onChange={e => setForm({ ...form, role: e.target.value })} />
      <input style={inputStyle} placeholder="Stack (e.g. pandas, SQL)" value={form.stack} onChange={e => setForm({ ...form, stack: e.target.value })} />
      <button onClick={hire} style={{ background: '#22c55e18', border: '1px solid #22c55e44', color: '#22c55e', borderRadius: 5, padding: '4px 0', fontSize: 11, cursor: 'pointer', fontFamily: 'Orbitron, sans-serif' }}>+ HIRE</button>
    </div>
  )
}
```

(Note: hired agents appear in chat/history APIs immediately; they appear in the 3D scene after Plan B Task 2's dynamic roster.)

- [x] **Step 6: Approvals badge on the OPS button**

In `NexusScene.tsx`, read `const pendingApprovals = useNexusStore(s => s.pendingApprovals)` and inside the OPS `<button>` append:

```tsx
        OPS{pendingApprovals > 0 && (
          <span style={{
            marginLeft: 6, background: '#f59e0b', color: '#020408',
            borderRadius: 8, padding: '0 5px', fontSize: 9, fontWeight: 700,
          }}>{pendingApprovals}</span>
        )}
```

Also sync the badge when OpsDrawer fetches: in `OpsDrawer.fetchAll`'s `.then`, after `setApprovals(...)`, add `useNexusStore.getState().setPendingApprovals(Object.keys(a && typeof a === 'object' ? a : {}).length)` (import `useNexusStore` from `../store`).

- [x] **Step 7: Typecheck + commit**

```bash
cd nexus-ui && npx tsc --noEmit && cd ..
git add nexus-ui/src/components/OpsDrawer.tsx nexus-ui/src/components/NexusScene.tsx
git commit -m "feat(ui): ops center — routines CRUD+logs, skill actions, email tasks, team hire/fire, approvals badge"
```

---

### Task 14: Build, deploy, end-to-end verification

**Files:** none (build + verify)

- [x] **Step 1: Run the full backend test suite**

```bash
cd /mnt/HC_Volume_105874680/virtual-company && python -m pytest tests/ -q
```

Expected: all pass. Fix any regression before continuing.

- [x] **Step 2: Production build**

```bash
cd nexus-ui && npm run build
```

Expected: vite build success, output in `app/static/`.

- [x] **Step 3: Rebuild + restart the app container**

```bash
cd /mnt/HC_Volume_105874680/virtual-company && docker compose up -d --build
```

- [x] **Step 4: End-to-end verification (per deployment-verification practice: container first, then endpoints, then UI)**

```bash
docker ps --format "{{.Names}} {{.Status}}" | grep -E "virtual-company|bark|browser"
curl -s -m 5 http://127.0.0.1:3031/api/health
curl -s -m 5 http://127.0.0.1:3031/api/email-tasks
curl -s -m 5 http://127.0.0.1:3031/ | grep -o '<title>[^<]*'
```

Expected: 3 containers Up; health JSON with `"bark":true,"browser":true`; email-tasks returns an array; HTML title served.

- [x] **Step 5: Browser smoke test** — open the dashboard, send a CEO task ("create a hello.txt file"), confirm: queue appears in SmartIsland QUEUE tab, ModelPill changes with `backend_status`, worker panel shows steps, notification on completion. Open Reinhard's panel, send "what files did you touch?" and confirm the reply comes from Reinhard (direct chat), not a CEO delegation.

- [x] **Step 6: Commit any fixes + final build artifact**

```bash
git add -A && git commit -m "build: pipeline repairs + UI connectivity production build"
```
