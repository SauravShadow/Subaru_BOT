# LangGraph Transformation — Full System Design

**Project:** Shadow Garden / NEXUS  
**Date:** 2026-06-10  
**Status:** Approved for implementation planning  
**Replaces orchestration in:** `executor.py`, `websocket.py`, `delegation.py`, `email_poller.py`, `state/manager.py`

---

## 0. Motivation

The system has hit the Phase 2 ceiling:

- Tasks requiring 2+ workers collaborating need shared context (workers currently run blind to each other's outputs)
- Multi-hour tasks have no crash recovery — a container restart loses all progress
- Human approval gates (self-heal protected writes) use a fragile email-scan polling loop
- The CEO never reviews or course-corrects worker output
- Maya's `[BROWSER_*]` tags silently fail on Claude/Gemini backends (only fire on tgpt fallback)

LangGraph addresses all of these at the orchestration layer without touching the execution layer.

---

## 1. Core Principle

**LangGraph owns: when each component runs, what state it receives, and what happens with its output.**  
**Existing code owns: everything that happens inside each component.**

Claude CLI subprocess loops, Gemini API calls, tgpt fallback, output pipeline tag parsing, browser_svc, email services — all unchanged. LangGraph is a wrapper around them, not a replacement.

---

## 2. Architecture Overview

Two compiled LangGraph graphs sharing one `AsyncSqliteSaver` on `nexus.db`:

```
nexus_graph   — WebSocket-driven, real-time
                CEO node → parallel worker nodes → CEO review → loop/end

email_graph   — Email-driven, async, long-lived
                7-node state machine with interrupt_before for approval gates
```

### New directory structure

```
app/
  graph/
    __init__.py
    state.py              ← NexusState, WorkerState, EmailState TypedDicts
    checkpointer.py       ← singleton AsyncSqliteSaver("nexus.db")
    nexus_graph.py        ← compiled nexus_graph
    email_graph.py        ← compiled email_graph
    nodes/
      ceo.py              ← CEO node (Claude CLI + [DELEGATE:] parsing)
      review.py           ← CEO review node (Gemini structured output)
      output.py           ← output pipeline node (wraps pipeline.process())
    workers/
      base.py             ← make_worker_graph() factory
      tools/
        core.py           ← list_available_skills, call_skill meta-tools
    email/
      nodes.py            ← verify, plan, execute, report, subdomain, wire_cf nodes
      graph.py            ← compiled email_graph + thread ID helpers

  # Entirely unchanged ───────────────────────────────────────
  output/                 ← pipeline, registry, all handlers
  services/               ← memory, browser_svc, browser, email,
  │                          email_inbox, jira, bark_client,
  │                          scheduler, standup, self_heal
  agents/
    definitions.py        ← all personas
    tools.py              ← bash/read/write/edit implementations
    backend_state.py      ← Claude→Gemini→tgpt routing logic
```

### Files deleted

| File | LOC | Replaced by |
|---|---|---|
| `agents/executor.py` | 1,071 | `app/graph/` |
| `services/delegation.py` | 53 | CEO node tag parsing + conditional edge |

### Files gutted and rewritten small

| File | Before | After | What stays |
|---|---|---|---|
| `api/websocket.py` | 443 LOC | ~120 LOC | Session class, broadcast_event, WS protocol |
| `services/email_poller.py` | 773 LOC | ~100 LOC | IMAP poll loop, automated email detection |
| `state/manager.py` | 228 LOC | ~80 LOC | changelog, projects, memory helpers |

**Net:** ~2,750 LOC removed, ~650 LOC added.

---

## 3. Shared State

### `NexusState` — top-level graph state

```python
class NexusState(TypedDict):
    task: str
    source: Literal["browser", "api"]
    session_id: str
    model: str                                       # "claude" | "gemini" | "chatgpt"

    # CEO planning
    ceo_response: str                                # raw CEO text (for display)
    delegations: list[dict]                          # [{agent, task, depends_on}]

    # Shared context — every worker reads and writes this
    artifacts: dict                                  # {"api_base": "...", "db_schema": "..."}

    # Worker results — parallel-safe merge via operator.add
    worker_results: Annotated[list[dict], operator.add]

    # CEO review
    ceo_verdict: Literal["approved", "revise", "delegate_more", "done"]
    revision_notes: str
```

### `WorkerState` — scoped to each worker subgraph

```python
class WorkerState(TypedDict):
    task: str
    agent_id: str
    model: str
    artifacts: dict                                  # read from parent NexusState
    messages: Annotated[list, add_messages]          # internal tool loop history
    result: str
    new_artifacts: dict                              # produced by this worker → merged up
```

### `EmailState` — scoped to email_graph

```python
class EmailState(TypedDict):
    email: dict
    is_owner: bool
    verified: bool
    plan: str
    user_reply: str
    execution_result: str
    port_used: str
    subdomain: str
    sent_message_ids: list[str]                      # for reply threading
```

### Checkpointer

```python
# app/graph/checkpointer.py
_checkpointer: AsyncSqliteSaver | None = None

async def get_checkpointer() -> AsyncSqliteSaver:
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = AsyncSqliteSaver.from_conn_string(str(config.MEMORY_DB))
        await _checkpointer.setup()
    return _checkpointer
```

Both graphs share one checkpointer instance. Thread namespaces:
- WebSocket: `ws_{session_uuid}`
- Email tasks: `email_{message_id}`

`state/manager.py` drops `conversation_histories`, `work_queue`, `active_agent_tasks`, and all `save_state()`/`load_state()` logic. It keeps `load_changelog()`, `log_feature()`, `load_projects()`, `save_project()`.

---

## 4. `nexus_graph`

### Topology

```
START → ceo_node → route_after_ceo → [worker subgraphs, parallel] → ceo_review → END
            ↑                                                              │
            └────────────── "revise" / "delegate_more" ──────────────────┘
```

### CEO node (`graph/nodes/ceo.py`)

Calls Claude CLI via `run_claude_agent()` (existing `executor.py` function, extracted).  
CEO persona from `agents/definitions.py` is unchanged.  
Live context injection (`_build_context_block()`) is unchanged.  
After the CLI call, `[DELEGATE:]` tags are parsed from the response using the existing `parse_delegations()` logic (inlined — `services/delegation.py` is deleted but its two functions move here).

Returns:
```python
{"ceo_response": text, "delegations": parsed_delegations, "artifacts": updated_artifacts}
```

### `route_after_ceo` conditional edge

```python
def route_after_ceo(state: NexusState):
    if not state["delegations"]:
        return END                  # CEO handled it directly
    return [
        Send(d["agent"], {
            "task": d["task"],
            "agent_id": d["agent"],
            "model": state["model"],
            "artifacts": state["artifacts"],
            "messages": [],
            "new_artifacts": {},
        })
        for d in state["delegations"]
    ]
```

All workers with no `depends_on` fire in parallel. Dependency ordering is handled by the review loop: CEO delegates the first batch (e.g. backend + devops), reviews their results and artifacts, then delegates the second batch (e.g. frontend — which now has `artifacts["api_base"]` available).

### Worker subgraph (`graph/workers/base.py`)

Each agent gets a compiled inner graph built by `make_worker_graph(agent_id)`:

```
START → worker_node → output_node → END
```

**`worker_node`** — calls `run_agent(agent_id, task, send, model)` from the existing executor. This is the complete multi-turn tool loop (Claude CLI subprocess or Gemini API or tgpt, all routing via `backend_state.py`). Entirely unchanged internals.

**`output_node`** — calls `pipeline.process(result, agent_id, send)`. Existing output pipeline, completely unchanged.

Returns `{"result": text, "new_artifacts": {}}` to parent `NexusState`. `new_artifacts` starts as an empty dict in this migration — workers write artifacts into shared state by including structured markers (e.g. `[ARTIFACT: api_base | http://...:8090]`) in their output, parsed by a lightweight regex in `output_node`. Full artifact extraction is a follow-on enhancement.

**This fixes the Maya browser bug:** Maya's task now runs through `worker_node` which calls `run_tgpt_agent` when tgpt is active — and for Claude/Gemini backends, the browser result is now fed back through the review loop rather than silently dropped. Longer term, `run_claude_agent` and `run_gemini_agent` should gain a tool-feedback loop matching `run_tgpt_agent` — but that is a separate improvement from this migration.

### CEO review node (`graph/nodes/review.py`)

Lightweight structured Gemini call — cheap, fast, has API key, supports function calling:

```python
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

class ReviewDecision(BaseModel):
    verdict: Literal["approved", "revise", "delegate_more", "done"]
    notes: str

review_llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash").with_structured_output(ReviewDecision)

def ceo_review_node(state: NexusState) -> dict:
    decision = review_llm.invoke(build_review_prompt(state))
    return {"ceo_verdict": decision.verdict, "revision_notes": decision.notes}
```

`route_after_review` edge:
- `"approved"` / `"done"` → `END`
- `"revise"` / `"delegate_more"` → back to `ceo_node`

### Self-heal approval gate

The existing email-approval mechanism in `services/self_heal.py` is preserved unchanged in this migration. The worker node calls `run_agent()` which internally handles zone classification and sends approval emails exactly as today. `nexus_pending_approvals.json`, `apply_approval()`, and the APPROVE/DENY scan in `email_poller` all stay.

**Future upgrade (not in scope here):** Add a dedicated `write_protected` node to worker subgraphs and compile with `interrupt_before=["write_protected"]`. This would let the graph pause natively at the approval gate and resume via `nexus_graph.ainvoke(None, thread_id)` — eliminating the scan loop entirely. This requires restructuring the worker subgraph from `worker_node → output_node` to `worker_node → write_protected → output_node` and is a clean follow-on task once the core migration is stable.

### Dynamic skills

Every worker subgraph gets two fixed tools compiled in:

```python
@tool
def list_available_skills() -> list[str]:
    """List all dynamically available skill tools."""
    return skill_loader.list_tools()

@tool
async def call_skill(skill_name: str, args: dict) -> str:
    """Call a dynamically loaded skill by name."""
    handler = skill_loader.get_tool(skill_name)
    if not handler:
        return f"Skill '{skill_name}' not found. Available: {list_available_skills()}"
    return str(await handler(args))
```

`app/skills/` hot-loading directory is completely unchanged. No graph recompilation needed when skills are added.

---

## 5. `email_graph`

### Topology

```
                     ┌─[trusted]──────────────────────────────┐
START → verify_node ─┤                                         ▼
                     └─[unknown]→ send_challenge_node      plan_node
                                       │                       │
                                  [INTERRUPT]            [INTERRUPT]
                                  wait for reply          wait for approval
                                       │                       │
                                  verify again           execute_node
                                                               │
                              ┌─[is_owner]────────────────────┤
                              ▼                                └─[external]──┐
                        report_node                                          ▼
                              │                                  ask_subdomain_node
                         [INTERRUPT]                                         │
                        wait for feedback                               [INTERRUPT]
                              │                                  wait for subdomain
                             END                                             │
                                                                    wire_cf_node → END
```

`interrupt_before=["execute_node", "wire_cf_node"]`

### Node responsibilities

| Node | Calls | Replaces |
|---|---|---|
| `verify_node` | `_is_trusted()` check | Trust routing logic |
| `send_challenge_node` | `inbox.send_reply()` | `_send_verification_challenge()` |
| `plan_node` | `_run_ceo_headless()` + `inbox.send_reply()` | `_run_planning()` |
| `execute_node` | `_run_ceo_headless()` | `_run_execution()` |
| `report_node` | `inbox.send_reply()` | Report-sending block in `_run_execution()` |
| `ask_subdomain_node` | `inbox.send_reply()` | Subdomain request block |
| `wire_cf_node` | sidecar API + `inbox.send_reply()` | `_handle_subdomain_reply()` |

All service functions (`inbox.send_reply`, sidecar API calls) are unchanged.

### Thin polling loop

`email_poller.py` becomes ~100 lines: IMAP poll + automated-email detection (unchanged) + graph dispatch:

```python
async def poll_once(email_graph):
    emails = await inbox.fetch_new_emails(max_emails=10)
    for email in emails:
        if _is_automated_email(email):
            continue
        thread_id = resolve_thread_id(email)           # message_id or matched original
        graph_state = await email_graph.aget_state(
            {"configurable": {"thread_id": thread_id}}
        )
        if graph_state.next:
            await email_graph.ainvoke(
                {"user_reply": _extract_reply_body(email["body"])},
                {"configurable": {"thread_id": thread_id}}
            )
        else:
            await email_graph.ainvoke(
                {"email": email, "is_owner": _is_trusted(email["from_email"])},
                {"configurable": {"thread_id": email["message_id"]}}
            )
```

### Reply threading

A lightweight `(sent_message_id → original_thread_id)` lookup table in `nexus.db` replaces `_find_task_by_reply()`. Each email node appends sent message IDs to `EmailState.sent_message_ids` (persisted by checkpointer). Table is rebuilt from checkpointer on startup.

### What disappears

- `_recover_stuck_tasks()` — checkpointer auto-recovers on restart
- `state.email_tasks` dict — EmailState lives in checkpointer
- All `state.save_state()` calls throughout email flow
- APPROVE/DENY email scanning loop — approval resumes via `nexus_graph.ainvoke(None, thread_id)`

---

## 6. WebSocket Handler

`api/websocket.py` simplifies to ~120 lines.

### Simplified `Session`

```python
class Session:
    def __init__(self, ws, model):
        self.ws = ws
        self.model = model
        self._lock = asyncio.Lock()

    async def send(self, data):
        async with self._lock:
            await self.ws.send_json(data)

_sessions: set[Session] = set()
_active_runs: dict[str, asyncio.Task] = {}   # thread_id → running graph task
```

No `bg_tasks`, no `worker_tasks`, no manual cancellation management.

### Message handling

```python
async def ws_endpoint(ws, model="claude"):
    session = Session(ws, model)
    thread_id = f"ws_{uuid4().hex}"
    _sessions.add(session)
    await ws.accept()
    await session.send({"type": "init", "agents": ..., ...})

    while True:
        msg = json.loads(await ws.receive_text())
        if msg["type"] == "message":
            t = asyncio.create_task(
                _run_and_stream(msg["text"], thread_id, session.model)
            )
            _active_runs[thread_id] = t
        elif msg["type"] == "cancel_worker":
            t = _active_runs.pop(thread_id, None)
            if t: t.cancel()
        elif msg["type"] == "model":
            session.model = msg["model"]
        elif msg["type"] == "clear":
            await nexus_graph.update_state(
                {"configurable": {"thread_id": thread_id}},
                {"worker_results": [], "delegations": [], "artifacts": {}}
            )
```

### Event streaming

```python
async def _run_and_stream(task, thread_id, model):
    config = {"configurable": {"thread_id": thread_id, "model": model}}
    async for event in nexus_graph.astream_events(
        {"task": task, "session_id": thread_id, "model": model},
        config, version="v2"
    ):
        msg = _translate_event(event)
        if msg:
            await broadcast_event(msg)
```

`_translate_event()` maps LangGraph events to the **unchanged** frontend WS protocol. Agent identity is extracted from the event's `metadata["langgraph_checkpoint_ns"]` field, which encodes the subgraph name (e.g. `"backend:abc123"` → `agent_id = "backend"`):

| LangGraph event | Frontend message |
|---|---|
| `on_chain_start` / `ceo_node` | `{"type": "thinking", "agent": "ceo"}` |
| `on_chat_model_stream` | `{"type": "assistant", "agent": "...", "message": {...}}` |
| `on_tool_start` | `{"type": "tool_call", "agent": "...", "tool": "bash", ...}` |
| `on_chain_end` / `output_node` | `{"type": "worker_done", "agent": "...", "summary": "..."}` |
| `on_chain_end` / `ceo_node` | `{"type": "done", "agent": "ceo"}` |
| `on_chain_error` | `{"type": "error", "agent": "...", "message": "..."}` |

Frontend JavaScript is **unchanged**.

### App startup (`main.py`)

```python
@asynccontextmanager
async def lifespan(app):
    cp = await get_checkpointer()
    app.state.nexus_graph = build_nexus_graph(cp)
    app.state.email_graph  = build_email_graph(cp)
    asyncio.create_task(email_poller.start(app.state.email_graph))
    asyncio.create_task(standup.start())
    asyncio.create_task(scheduler.start())
    yield
```

---

## 7. Three-Backend Routing

`backend_state.py` is **unchanged**. The `model` preference flows through `NexusState` and each worker node reads `state["model"]` before calling `run_agent()`:

```
Primary:    Claude CLI  (claude -p subprocess, CLAUDE_BIN env var)
Fallback:   Gemini API  (google-genai SDK, GEMINI_API_KEY env var)
Last resort: tgpt       (tgpt subprocess, TGPT_BIN env var)
```

`CLAUDE_BIN`, `TGPT_BIN`, `GEMINI_API_KEY` configs are all preserved. No `ANTHROPIC_API_KEY` required.

CEO review node is the only place that uses `langchain-google-genai` directly (for structured output). All other LLM calls go through the existing `run_agent()` routing.

---

## 8. Error Handling

| Scenario | Handling |
|---|---|
| Tool exception in worker | Worker catches, logs, returns error text to LLM for recovery (existing behaviour) |
| Claude quota hit | `backend_state.py` switches to Gemini (existing behaviour) |
| Gemini failure | `backend_state.py` falls back to tgpt (existing behaviour) |
| Worker node unhandled exception | `on_chain_error` event → `{"type": "error"}` sent to frontend |
| Container crash mid-worker | Checkpointer resumes from last node boundary on restart |
| WebSocket disconnect mid-task | asyncio task continues, broadcasts to reconnected sessions |

---

## 9. Testing

New test directory: `app/tests/graph/`

| Test file | Covers |
|---|---|
| `test_ceo_node.py` | `[DELEGATE:]` parsing produces correct delegations |
| `test_worker_node.py` | worker node calls run_agent, output_node called at end |
| `test_email_graph.py` | each state transition with mock email data + MemorySaver |
| `test_event_translation.py` | LangGraph events → correct WS protocol messages |
| `test_review_node.py` | Gemini structured output produces valid ReviewDecision |

Worker subgraph tests use `MemorySaver` (in-memory, no SQLite I/O). Existing `app/tests/` suite is unchanged.

---

## 10. Dependencies

Add to `requirements.txt`:

```
langgraph>=0.3.0
langgraph-checkpoint-sqlite>=0.1.0
langchain-google-genai>=2.0.0
langchain-core>=0.3.0
```

Remove from `requirements.txt` (if present): nothing — all existing deps stay.

`langchain-google-genai` is used only in the CEO review node. All other Gemini calls continue using `google-genai` SDK directly.

---

## 11. Migration Notes

- `nexus_state.json` (current work queue + conversation histories) is superseded by the LangGraph checkpointer. It can be deleted after cutover — no migration of existing state is needed.
- `nexus_memory.db` is extended (new tables added by checkpointer setup) but existing memory rows are preserved.
- The `CLAUDE_BIN` env var and subprocess approach are preserved — no change to `entrypoint.sh` or `docker-compose.yml`.
- The frontend (`app/static/`) receives the identical WebSocket event shapes — no frontend changes required.
- Self-heal zone definitions (`_IMMUTABLE`, `_PROTECTED`, `_SURFACE_PREFIX`) in `services/self_heal.py` are unchanged.
