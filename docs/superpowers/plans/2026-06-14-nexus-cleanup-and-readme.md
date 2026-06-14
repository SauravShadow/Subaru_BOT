# NEXUS: Full Cleanup, Pipeline Fix & README Generation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Fix the double-pipeline bug that causes SPEAK/EMAIL/BROWSER actions to fire twice for worker responses, remove all confirmed dead code, seed the standup routine, tighten UI selectors, and write 7 READMEs so future sessions have instant context.

**Architecture:** Backend fix is surgical — pipeline.process() moves from inside runner functions to their callers (ceo_node, _run_direct, output_node already has it). Dead code is pure deletion. Standup is seeded as a disabled default routine in scheduler. READMEs are written last once all code is clean.

**Tech Stack:** FastAPI, LangGraph, React 18 + zustand + react-three-fiber. Backend tests: `python -m pytest tests/ -q` inside repo. Always use `127.0.0.1` in curl. Build: `cd nexus-ui && npx vite build`.

**Project root:** `/mnt/HC_Volume_105874680/virtual-company` — all paths below are relative to it.

---

## Files Changed

| File | Action |
|---|---|
| `app/agents/runner.py` | Remove `pipeline.process()` from `run_tgpt_agent`, `run_claude_agent`, `run_gemini_agent` |
| `app/graph/nodes/ceo.py` | Add `pipeline.process()` after `run_claude_agent()` call |
| `app/api/websocket.py` | Capture result from `runner.run_agent()` in `_run_direct`; add `pipeline.process()` |
| `app/api/router.py` | Delete 6 dead routes |
| `app/services/scheduler.py` | Add `_seed_default_routines()`, call it in `start_scheduler_loop()` |
| `app/services/browser_svc.py` | Delete file |
| `nexus-ui/src/store.ts` | Remove `browser_frame` case (lines 236-248) |
| `nexus-ui/src/components/ReactorRing.tsx` | Fix `busyCount` selector; fix live clock |
| `nexus-ui/src/components/Background.tsx` | Fix `ceoStatus` selector |
| `README.md` | Create |
| `app/graph/README.md` | Create |
| `app/agents/README.md` | Create |
| `app/output/README.md` | Create |
| `app/services/README.md` | Create |
| `app/api/README.md` | Create |
| `nexus-ui/README.md` | Create |

---

### Task 1: Fix double pipeline.process() — runner.py

**Files:**
- Modify: `app/agents/runner.py` (3 locations)
- Test: `tests/test_pipeline.py`

The three runner functions (`run_tgpt_agent`, `run_claude_agent`, `run_gemini_agent`) each call `pipeline.process()` at the end. For the LangGraph worker path, `output_node` then calls it again — doubling every SPEAK, EMAIL, and BROWSER action. For the scheduler path, the duplicate also doubles emails. Fix: strip these calls from runner functions. Callers (ceo_node, _run_direct, output_node, run_routine) own processing.

- [ ] **Step 1: Write a failing test that confirms output_node processes the pipeline (proves it won't be lost)**

Add to `tests/test_pipeline.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

@pytest.mark.asyncio
async def test_output_node_calls_pipeline_exactly_once():
    """output_node must call pipeline.process exactly once — it's the canonical
    pipeline caller for all LangGraph worker responses."""
    from app.graph.nodes.output import output_node
    from langchain_core.runnables import RunnableConfig

    state = {"result": "[SPEAK: hello]", "agent_id": "backend"}
    config = RunnableConfig(configurable={"thread_id": "test-t1"})

    with patch("app.graph.nodes.output.pipeline.process", new_callable=AsyncMock) as mock_proc, \
         patch("app.graph.broadcast.send", new_callable=AsyncMock):
        await output_node(state, config)
        assert mock_proc.call_count == 1
        args = mock_proc.call_args[0]
        assert args[0] == "[SPEAK: hello]"
        assert args[1] == "backend"
```

- [ ] **Step 2: Run test to confirm it passes (output_node already calls pipeline)**

```bash
cd /mnt/HC_Volume_105874680/virtual-company
docker exec virtual-company python -m pytest tests/test_pipeline.py::test_output_node_calls_pipeline_exactly_once -v
```

Expected: PASS (output_node already calls it).

- [ ] **Step 3: Remove pipeline.process() from run_tgpt_agent**

In `app/agents/runner.py`, find the block near line 350:

```python
    if full_resp.strip():
        await pipeline.process(full_resp, agent_id, send)

    return full_resp
```

This is inside `run_tgpt_agent`. Delete those two lines (keep only `return full_resp`):

```python
    return full_resp
```

- [ ] **Step 4: Remove pipeline.process() from run_claude_agent**

In `app/agents/runner.py`, find the block near line 437 (inside `run_claude_agent`, just before `return full_resp`):

```python
    if full_resp.strip():
        await pipeline.process(full_resp, agent_id, send)

    return full_resp
```

Delete those two lines, keep only:

```python
    return full_resp
```

- [ ] **Step 5: Remove pipeline.process() from run_gemini_agent**

In `app/agents/runner.py`, find the block near line 534 (inside the Gemini success path):

```python
        await pipeline.process(text, agent_id, send)
        return text
```

Replace with:

```python
        return text
```

- [ ] **Step 6: Run existing pipeline + delegation tests to confirm nothing else broke**

```bash
docker exec virtual-company python -m pytest tests/test_pipeline.py tests/test_delegation.py -v
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
cd /mnt/HC_Volume_105874680/virtual-company
git add app/agents/runner.py tests/test_pipeline.py
git commit -m "fix: remove pipeline.process() from runner functions — output_node is canonical caller"
```

---

### Task 2: Fix double pipeline — ceo_node and _run_direct

**Files:**
- Modify: `app/graph/nodes/ceo.py`
- Modify: `app/api/websocket.py`

CEO doesn't go through output_node so it needs pipeline.process() added to ceo_node. _run_direct (direct 1:1 agent chat, bypasses LangGraph) also bypasses output_node so it needs it too.

- [ ] **Step 1: Add pipeline.process() to ceo_node**

In `app/graph/nodes/ceo.py`, add import at top:

```python
from app.output import pipeline
```

Then inside `ceo_node`, after `response = await run_claude_agent("ceo", task, send)` and before parsing delegations:

```python
    response = await run_claude_agent("ceo", task, send)

    # Process output tags (SPEAK, EMAIL_USER, etc.) exactly once here.
    # CEO doesn't flow through output_node, so pipeline lives in ceo_node.
    await pipeline.process(response, "ceo", send)

    delegations = parse_delegations_from_response(response)
```

- [ ] **Step 2: Add pipeline.process() to _run_direct in websocket.py**

In `app/api/websocket.py`, add import near the top (after existing imports):

```python
from app.output import pipeline as _output_pipeline
```

Then in `_run_direct`, capture the result and process it:

```python
async def _run_direct(agent_id: str, task: str, model: str) -> None:
    """1:1 chat with a single agent — bypasses the CEO orchestration graph."""
    if agent_id not in defs.all_agents():
        await broadcast_event({"type": "error", "agent": "ceo",
                               "message": f"Unknown agent '{agent_id}'"})
        return
    import app.agents.runner as runner
    await broadcast_event({"type": "delegation", "agent": agent_id})
    try:
        result = await runner.run_agent(agent_id, task, broadcast_event, model)
        if result and result.strip():
            await _output_pipeline.process(result, agent_id, broadcast_event)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("direct chat error for %s", agent_id)
        await broadcast_event({"type": "error", "agent": agent_id,
                               "message": str(exc)[:200]})
    finally:
        await broadcast_event({"type": "worker_done", "agent": agent_id})
```

- [ ] **Step 3: Run health check to confirm app still starts**

```bash
docker exec virtual-company python -m pytest tests/test_health.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd /mnt/HC_Volume_105874680/virtual-company
git add app/graph/nodes/ceo.py app/api/websocket.py
git commit -m "fix: add pipeline.process() to ceo_node and _run_direct — each path now processes exactly once"
```

---

### Task 3: Remove dead API routes

**Files:**
- Modify: `app/api/router.py`
- Test: `tests/test_health.py`

Six routes return stubs/errors and are never called by the frontend.

- [ ] **Step 1: Delete the 6 dead routes from router.py**

In `app/api/router.py`, delete these blocks entirely:

```python
# DELETE THIS BLOCK (lines ~65-82):
@router.get("/api/workqueue")
async def api_wq():
    return []

@router.post("/api/workqueue/{item_id}/complete")
async def api_complete_item(item_id: int, body: dict):
    return {"ok": False, "error": "work queue replaced by LangGraph"}

@router.post("/api/workqueue/{item_id}/force-complete")
async def api_force_complete(item_id: int):
    return {"ok": False, "error": "work queue replaced by LangGraph"}

@router.post("/api/workqueue/{item_id}/reset")
async def api_reset_item(item_id: int):
    return {"ok": False, "error": "work queue replaced by LangGraph"}

# DELETE THIS BLOCK (line ~136-138):
@router.get("/api/task-history")
async def api_task_history():
    return []

# DELETE THIS BLOCK (line ~186-188):
@router.get("/api/email-tasks/{task_id}")
async def api_email_task_detail(task_id: str):
    return JSONResponse({"error": "not found"}, status_code=404)
```

- [ ] **Step 2: Confirm health endpoint still works**

```bash
docker exec virtual-company python -m pytest tests/test_health.py -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
cd /mnt/HC_Volume_105874680/virtual-company
git add app/api/router.py
git commit -m "chore: remove 6 dead API routes (workqueue stubs, task-history, email-tasks detail)"
```

---

### Task 4: Delete dead files and frontend handler

**Files:**
- Delete: `app/services/browser_svc.py`
- Modify: `nexus-ui/src/store.ts`

- [ ] **Step 1: Delete browser_svc.py**

```bash
rm /mnt/HC_Volume_105874680/virtual-company/app/services/browser_svc.py
```

- [ ] **Step 2: Remove browser_frame case from store.ts**

In `nexus-ui/src/store.ts`, delete the `browser_frame` case from the `handleEvent` switch. Find and remove this block (approximately lines 236-248):

```typescript
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
```

- [ ] **Step 3: Confirm TypeScript still compiles**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/nexus-ui && npx tsc --noEmit
```

Expected: exit 0, no errors.

- [ ] **Step 4: Commit**

```bash
cd /mnt/HC_Volume_105874680/virtual-company
git add -A
git commit -m "chore: delete unused browser_svc.py and dead browser_frame UI handler"
```

---

### Task 5: Wire standup — seed default routine

**Files:**
- Modify: `app/services/scheduler.py`
- Test: `tests/test_scheduler.py`

Add `_seed_default_routines()` which inserts a disabled "morning_standup" routine if it doesn't already exist. Called at startup so it appears in the OPS → Routines panel immediately. User can enable it there.

- [ ] **Step 1: Write failing test**

Add to `tests/test_scheduler.py`:

```python
def test_seed_default_routines_adds_standup_when_missing(tmp_path, monkeypatch):
    """First startup creates the morning_standup routine in disabled state."""
    from app.services import scheduler
    monkeypatch.setattr(scheduler, "ROUTINES_FILE", tmp_path / "routines.json")

    scheduler._seed_default_routines()

    routines = scheduler.load_routines()
    ids = [r["id"] for r in routines]
    assert "morning_standup" in ids

    standup = next(r for r in routines if r["id"] == "morning_standup")
    assert standup["enabled"] is False        # off by default
    assert standup["schedule"] == "0 9 * * 1-5"
    assert standup["agent"] == "ceo"


def test_seed_default_routines_is_idempotent(tmp_path, monkeypatch):
    """Calling seed twice doesn't create duplicate routines."""
    from app.services import scheduler
    monkeypatch.setattr(scheduler, "ROUTINES_FILE", tmp_path / "routines.json")

    scheduler._seed_default_routines()
    scheduler._seed_default_routines()

    routines = scheduler.load_routines()
    standup_count = sum(1 for r in routines if r["id"] == "morning_standup")
    assert standup_count == 1
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
docker exec virtual-company python -m pytest tests/test_scheduler.py::test_seed_default_routines_adds_standup_when_missing -v
```

Expected: FAIL — `_seed_default_routines` not defined yet.

- [ ] **Step 3: Implement _seed_default_routines in scheduler.py**

Add to `app/services/scheduler.py` after `save_routines()` (before `update_routine_run`):

```python
_DEFAULT_ROUTINES: list[dict] = [
    {
        "id":          "morning_standup",
        "name":        "Morning Standup",
        "description": "Daily 9am weekday briefing — CEO summarises activity and emails it",
        "schedule":    "0 9 * * 1-5",
        "timezone":    "UTC",
        "enabled":     False,
        "agent":       "ceo",
        "prompt":      (
            "Generate a morning standup briefing for today. "
            "Summarise: any completed tasks since yesterday, current work in progress, "
            "and today's priorities. Then email it to me with subject "
            f"'Morning Standup — {{datetime.now().strftime(\"%Y-%m-%d\")}}'."
        ),
        "run_count":   0,
    }
]


def _seed_default_routines() -> None:
    """Insert built-in routines that should always exist (disabled by default).

    Called at startup. Safe to call multiple times — skips any id already present.
    """
    routines = load_routines()
    existing_ids = {r["id"] for r in routines}
    added = False
    for default in _DEFAULT_ROUTINES:
        if default["id"] not in existing_ids:
            routines.append(default)
            added = True
    if added:
        save_routines(routines)
```

**Note:** The f-string inside `prompt` uses `datetime.now()` which would be evaluated at module load time. Change the prompt to a static string:

```python
        "prompt":      (
            "Generate a morning standup briefing for today. "
            "Summarise: any completed tasks since yesterday, current work in progress, "
            "and today's priorities. Then email it to me with subject "
            "'Morning Standup — [today\\'s date]'."
        ),
```

- [ ] **Step 4: Call _seed_default_routines in start_scheduler_loop**

In `app/services/scheduler.py`, in `start_scheduler_loop()`, add the seed call at the top:

```python
async def start_scheduler_loop() -> None:
    """Check routines every 30 s; fire each at most once per scheduled minute."""
    _seed_default_routines()
    logger.info("Subaru Scheduler started.")
    fired: dict[str, str] = {}

    while True:
        try:
            _tick(fired)
        except Exception as exc:
            logger.error("Scheduler tick error: %s", exc)
        await asyncio.sleep(30)
```

- [ ] **Step 5: Run the new tests**

```bash
docker exec virtual-company python -m pytest tests/test_scheduler.py::test_seed_default_routines_adds_standup_when_missing tests/test_scheduler.py::test_seed_default_routines_is_idempotent -v
```

Expected: both PASS.

- [ ] **Step 6: Run full scheduler test suite**

```bash
docker exec virtual-company python -m pytest tests/test_scheduler.py -v
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
cd /mnt/HC_Volume_105874680/virtual-company
git add app/services/scheduler.py tests/test_scheduler.py
git commit -m "feat: seed morning_standup routine on startup (disabled by default, toggle in OPS panel)"
```

---

### Task 6: Fix UI selectors and ReactorRing clock

**Files:**
- Modify: `nexus-ui/src/components/ReactorRing.tsx`
- Modify: `nexus-ui/src/components/Background.tsx`

ReactorRing subscribes to the entire `agents` map (re-renders on every event) to count 2 active agents. Background.tsx does the same just for CEO status. Fix with narrow selectors. Also fix the ReactorRing clock which is frozen (computed at render time, never updates).

- [ ] **Step 1: Fix ReactorRing selector and live clock**

In `nexus-ui/src/components/ReactorRing.tsx`, replace:

```typescript
import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { Billboard, Text } from '@react-three/drei'
import * as THREE from 'three'
import { useNexusStore } from '../store'
```

with:

```typescript
import { useMemo, useRef, useState, useEffect } from 'react'
import { useFrame } from '@react-three/fiber'
import { Billboard, Text } from '@react-three/drei'
import * as THREE from 'three'
import { useNexusStore } from '../store'
```

Replace the store subscription line:

```typescript
  const agents = useNexusStore(s => s.agents)

  const busyCount = Object.values(agents)
    .filter(a => a.status === 'working' || a.status === 'thinking').length
```

with a narrow selector that only re-renders when the count changes:

```typescript
  const busyCount = useNexusStore(s =>
    Object.values(s.agents).filter(a => a.status === 'working' || a.status === 'thinking').length
  )
```

Replace the frozen clock line:

```typescript
  const clock = new Date().toTimeString().slice(0, 5)
```

with a live clock that updates every minute:

```typescript
  const [clock, setClock] = useState(() => new Date().toTimeString().slice(0, 5))
  useEffect(() => {
    const id = setInterval(() => setClock(new Date().toTimeString().slice(0, 5)), 60_000)
    return () => clearInterval(id)
  }, [])
```

- [ ] **Step 2: Fix Background.tsx selector**

In `nexus-ui/src/components/Background.tsx`, replace:

```typescript
  const agents = useNexusStore(s => s.agents)
  const ceoStatus = agents['ceo']?.status ?? 'idle'
```

with:

```typescript
  const ceoStatus = useNexusStore(s => s.agents['ceo']?.status ?? 'idle')
```

- [ ] **Step 3: TypeScript check**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/nexus-ui && npx tsc --noEmit
```

Expected: exit 0.

- [ ] **Step 4: Build frontend**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/nexus-ui && npx vite build
```

Expected: `✓ built in ~15s`.

- [ ] **Step 5: Commit**

```bash
cd /mnt/HC_Volume_105874680/virtual-company
git add nexus-ui/src/components/ReactorRing.tsx nexus-ui/src/components/Background.tsx
git commit -m "perf: narrow store selectors in ReactorRing + Background; fix frozen clock"
```

---

### Task 7: Run full test suite + verify live

- [ ] **Step 1: Run all backend tests**

```bash
docker exec virtual-company python -m pytest tests/ -q
```

Expected: all pass (or same failures as before — do not introduce new failures).

- [ ] **Step 2: Verify standup routine appears in OPS panel**

```bash
curl -s http://127.0.0.1:3031/api/routines | python3 -m json.tool | grep -A5 morning_standup
```

Expected: JSON block with `"id": "morning_standup"`, `"enabled": false`.

- [ ] **Step 3: Verify dead routes are gone**

```bash
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3031/api/workqueue
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3031/api/task-history
```

Expected: both `404`.

---

### Task 8: Write READMEs

**Files:** 7 new files (no tests needed — documentation)

- [ ] **Step 1: Write root README.md**

Create `/mnt/HC_Volume_105874680/virtual-company/README.md`:

```markdown
# NEXUS Virtual Company

AI multi-agent company powered by LangGraph + FastAPI + React Three Fiber.

## Architecture

```
User → WebSocket (/ws) → CEO (LangGraph) → Workers (LangGraph subgraphs)
                                         → Output Pipeline (SPEAK/EMAIL/BROWSER tags)
                                         → Frontend (Zustand store → R3F solar system UI)
```

## Ports

| Service | External | Internal |
|---|---|---|
| Main app (FastAPI + React) | 3031 | 3030 |
| Bark TTS | — | 9001 |
| Browser automation | — | 9002 |

## Running

```bash
cd /mnt/HC_Volume_105874680/virtual-company
docker compose up -d
# UI: http://127.0.0.1:3031
```

## Frontend build

```bash
cd nexus-ui && npx vite build   # outputs to app/static/
```

## Backend tests

```bash
docker exec virtual-company python -m pytest tests/ -q
```

## Key directories

| Path | Purpose |
|---|---|
| `app/graph/` | LangGraph nodes, edges, state |
| `app/agents/` | Agent personas, execution engine |
| `app/output/` | Output tag pipeline (SPEAK, EMAIL, etc.) |
| `app/services/` | Memory, email, scheduler, bark, browser, jira |
| `app/api/` | FastAPI routes + WebSocket handler |
| `nexus-ui/src/` | React + R3F frontend |
| `docs/superpowers/plans/` | Implementation plans |
| `docs/superpowers/specs/` | Design specs |
```

- [ ] **Step 2: Write app/graph/README.md**

Create `/mnt/HC_Volume_105874680/virtual-company/app/graph/README.md`:

```markdown
# LangGraph Flow

## Graph topology

```
START
  └─→ ceo_node          (planning, delegation, SPEAK/EMAIL processing)
        ├─→ END           (no delegation needed)
        ├─→ backend       (worker subgraph)
        ├─→ frontend      (worker subgraph)
        ├─→ qa            (worker subgraph)
        ├─→ devops        (worker subgraph)
        └─→ browser       (worker subgraph)
              └─→ ceo_review_node
                    ├─→ END        (approved / done)
                    └─→ ceo_node   (revise / delegate_more)
```

## Worker subgraph (per agent)

```
START → worker_node → output_node → END
```

`worker_node`: calls `run_agent()`, returns raw text in `state["result"]`.  
`output_node`: calls `pipeline.process(result)` — processes SPEAK/EMAIL/BROWSER tags ONCE, extracts artifacts.

## Key files

| File | Role |
|---|---|
| `nexus_graph.py` | Builds the full graph; `route_after_ceo()` fans out delegations via `Send()` |
| `nodes/ceo.py` | CEO node — runs agent, processes pipeline, parses delegations |
| `nodes/output.py` | Output node — pipeline + artifact extraction for workers |
| `nodes/review.py` | Review node — Gemini structured verdict (approved/revise/delegate_more/done) |
| `workers/base.py` | `make_worker_graph()` factory — one compiled subgraph per agent |
| `broadcast.py` | Thread-scoped send registry — decouples nodes from WebSocket layer |
| `state.py` | `NexusState` and `WorkerState` TypedDicts |

## Adding a new agent

1. Add persona function in `app/agents/definitions.py`
2. Add agent id to `AGENT_DEFS` in `definitions.py`
3. Add to `_KNOWN_AGENTS` list in `nexus_graph.py` (line ~20)
4. The worker subgraph is created automatically by `make_worker_graph(agent_id)`
5. Add position to `AGENT_POSITIONS` in `nexus-ui/src/types.ts`

## Pipeline processing rule

`pipeline.process()` is called EXACTLY ONCE per response:
- Workers: in `output_node` (after `worker_node` returns)
- CEO: in `ceo_node` (after `run_claude_agent()`)
- Direct chat path: in `_run_direct` in `websocket.py`

**Never call `pipeline.process()` inside runner functions** (`run_claude_agent` etc.) — those functions are reused across paths and the caller owns processing.
```

- [ ] **Step 3: Write app/agents/README.md**

Create `/mnt/HC_Volume_105874680/virtual-company/app/agents/README.md`:

```markdown
# Agent System

## Agent definitions (`definitions.py`)

Six built-in agents (CEO + 5 workers). Each has:
- `id`: used throughout the system as the routing key
- `name`: display name in UI
- `persona`: callable returning the full system prompt string

| id | Name | Role |
|---|---|---|
| `ceo` | Subaru Natsuki | Orchestrator — delegates via `[DELEGATE:role]` tags |
| `backend` | Reinhard van Astrea | Python, FastAPI, databases. Can self-modify `/app/` files |
| `frontend` | Emilia | React, TypeScript. Uses `[WRITE_PREVIEW:]` for live HTML preview |
| `qa` | Beatrice | Testing, security |
| `devops` | Otto Suwen | Docker, deployment, port registry |
| `browser` | Maya | Job search, CV tailoring via `[BROWSER_*]` tags |

Custom agents can be created at runtime via `POST /api/hire` and live in `custom_agents` dict.

## Execution engine (`runner.py`)

`run_agent(agent_id, task, send, model)` — main entry point.

Routes to one of three backends based on quota/availability:
1. `run_claude_agent()` — Claude CLI subprocess, streaming JSON
2. `run_gemini_agent()` — Gemini API via google-genai
3. `run_tgpt_agent()` — tgpt CLI fallback

All three return raw text. **The caller is responsible for calling `pipeline.process()`.** Do not add pipeline calls inside these functions.

## Memory injection

Before every agent call, `run_agent()` fetches relevant memories from SQLite FTS5 (`app/services/memory.py`) and prepends them to the prompt context.

## Backend state machine (`backend_state.py`)

Tracks Claude quota exhaustion → Gemini fallback → Claude recovery. Emits `backend_status` WebSocket events when backend changes.
```

- [ ] **Step 4: Write app/output/README.md**

Create `/mnt/HC_Volume_105874680/virtual-company/app/output/README.md`:

```markdown
# Output Pipeline

Post-processes every LLM response. Scans for registered `[TAG: ...]` patterns, dispatches to handlers, strips tags from display text, sends a single `assistant` WS message with `bark_ok` flag.

## Pipeline flow (`pipeline.py`)

```
raw LLM text
  → for each registered handler: find matches → handler.handle() → send side-effects
  → cleaned display text
  → send {type: "assistant", bark_ok: true|false}
```

`bark_ok=true` if any handler produced Bark audio. Frontend uses this to decide whether to trigger Web Speech fallback.

## Handlers (`handlers/`)

| Handler | Tag | Side effect |
|---|---|---|
| `speak.py` | `[SPEAK: text \| emotion: X]` | Sends Bark audio via bark-svc → `{type: "audio"}` |
| `sing.py` | `[SING: text]` | Sends Bark singing audio → `{type: "audio"}` |
| `image.py` | `[GENERATE_IMAGE: prompt]` | Calls pollinations.ai → sends image as `assistant` block |
| `email.py` | `[EMAIL_USER: subject \| body]` | Sends email via SMTP |
| `browser_apply.py` | `[BROWSER_APPLY: url]` | Triggers browser-svc job application |
| `browser_discover.py` | `[BROWSER_DISCOVER: query]` | Triggers job discovery |
| `browser_company.py` | `[BROWSER_COMPANY: name]` | Company research |
| `browser_profile_match.py` | `[BROWSER_PROFILE_MATCH: url]` | CV/profile matching |

## Adding a new output tag

1. Create `app/output/handlers/mytag.py` with:
   - `TAG = "MYTAG"`
   - `PATTERN = re.compile(r'\[MYTAG:\s*(.*?)\]', re.DOTALL)`
   - `async def handle(args, agent_id, send) -> tuple[str, bool]` — return (display_text, produced_audio)
2. Import and register in `app/output/registry.py`
3. Write test in `tests/test_handlers.py`

## Registry (`registry.py`)

`get_registry()` returns `{tag_name: handler_module}`. Pipeline iterates this dict on every response.
```

- [ ] **Step 5: Write app/services/README.md**

Create `/mnt/HC_Volume_105874680/virtual-company/app/services/README.md`:

```markdown
# Services

## memory.py
SQLite FTS5 semantic memory. Agents read relevant memories as context before each call.
- `save_memory(agent_id, text, mem_type, importance)` — write
- `get_relevant_memories(agent_id, query, limit)` — FTS5 search
- Init: `init_db()` called in `app/main.py` on startup
- DB file: `nexus_memory.db`

## email.py + email_inbox.py
- `email.py`: `send_mail()`, `read_emails()` — SMTP/IMAP via stdlib
- `email_inbox.py`: IMAP4_SSL with header decoding, used by email_poller and email graph nodes

## email_poller.py
Background IMAP poller. Runs every 30s (started in `main.py`). Dispatches new emails to `email_graph`.
- `poll_once(email_graph)` — one poll cycle
- `list_tasks()` — last 20 dispatched email tasks (for `/api/email-tasks` UI)

## scheduler.py
Cron-based routine runner. Runs every 30s (started in `main.py`).
- Routines stored in `nexus_routines.json`
- Race-condition-safe: `fire_key = "<id>:<YYYYMMDDHHMM>"` ensures at-most-once-per-minute
- `_seed_default_routines()` — called at startup, adds built-in routines (morning_standup) if absent
- Routine fields: `id`, `name`, `schedule` (cron), `timezone`, `enabled`, `agent`, `prompt`
- Manageable via OPS → Routines panel in UI

## bark_client.py
HTTP client to bark-svc (port 9001 internal). `speak(text, emotion)`, `sing(text)`, `get_filler()`.

## browser.py
Playwright direct browser operations (used by `/api/browser/*` routes). Primary browser automation is via browser-svc HTTP proxy.

## jira.py
Jira REST API v3. `get_ticket()`, `search_tickets()`, `add_comment()`, etc. Lazily imported in runner.py tool dispatch.

## self_heal.py
Zone-based source file protection + approval workflow.
- Zones: `immutable` (never touched), `protected` (needs approval), `surface` (auto-applied), `learning` (auto if tests pass)
- Approvals stored in `nexus_approvals.json`, manageable via OPS → Approvals panel

## standup.py
Generates morning briefing prompt and emails it via CEO agent. Not called directly — triggered when the `morning_standup` scheduler routine runs (enabled via OPS → Routines).
```

- [ ] **Step 6: Write app/api/README.md**

Create `/mnt/HC_Volume_105874680/virtual-company/app/api/README.md`:

```markdown
# API Layer

## WebSocket (`websocket.py`)

**Endpoint:** `ws://host/ws?model=claude|gemini`

### Message types (client → server)

| type | Fields | Effect |
|---|---|---|
| `message` | `text`, optionally `agent` | If no `agent` or `agent="ceo"`: CEO orchestration via LangGraph. If `agent=<worker>`: direct 1:1 chat via `_run_direct`. |
| `cancel` | — | Cancels active run for this thread |
| `model` | `model` | Switches backend for this session |

### Event types (server → client)

| type | When |
|---|---|
| `init` | On connect — full agent roster |
| `thinking` | CEO starts planning |
| `delegation` | Worker agent assigned task |
| `worker_step` | Tool invocation begins |
| `worker_checkpoint` | Worker completes step |
| `worker_done` | Worker finished |
| `done` | CEO task complete |
| `error` | Any error |
| `assistant` | LLM text chunk (streaming) or final cleaned text with `bark_ok` |
| `audio` | Bark audio payload (base64 WAV) |
| `queue_update` | Work queue changed |
| `backend_switch` / `backend_status` | Backend model changed |
| `browser_navigated` | Browser screenshot ready |
| `browser_result` | Browser job finished |
| `design_preview_updated` | Frontend wrote a preview file |
| `routine_completed` | Scheduler routine ran |
| `standup` | Morning standup generated |
| `email_sent` | Email dispatched |
| `source_file_modified` | Agent modified a source file |
| `approval_requested` / `approval_applied` / `approval_denied` | Self-heal approval flow |

### Two execution paths

**CEO path** (`_run_and_stream`): Message with no `agent` field → LangGraph `astream_events()` → CEO → workers → `ceo_review_node` → done.

**Direct path** (`_run_direct`): Message with `agent: "backend"` (or any worker id) → bypasses LangGraph → `run_agent()` → `pipeline.process()` → done. Used for direct 1:1 chat from agent detail panel.

## REST Routes (`router.py`)

### Active routes

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/agents` | List all agents |
| GET | `/api/chat/{id}/history` | Conversation history for agent |
| POST | `/api/hire` | Create custom agent |
| DELETE | `/api/hire/{id}` | Remove custom agent |
| GET | `/api/health` | System health (app/bark/browser) |
| GET | `/api/routines` | List scheduler routines |
| POST | `/api/routines` | Create routine |
| PUT | `/api/routines/{id}` | Update routine |
| DELETE | `/api/routines/{id}` | Delete routine |
| POST | `/api/routines/{id}/run` | Run routine now |
| GET | `/api/routines/{id}/logs` | Routine run logs |
| GET | `/api/skills` | List registered output handlers |
| GET | `/api/approvals` | List pending approvals |
| POST | `/api/approvals/{id}/apply` | Apply approval |
| POST | `/api/approvals/{id}/deny` | Deny approval |
| GET | `/api/email-tasks` | Last 20 email tasks |
| POST | `/api/email-tasks/poll` | Manual email poll |
| POST | `/api/design/preview` | Write design preview HTML |
| GET/POST | `/api/browser/*` | Browser automation |
```

- [ ] **Step 7: Write nexus-ui/README.md**

Create `/mnt/HC_Volume_105874680/virtual-company/nexus-ui/README.md`:

```markdown
# NEXUS UI

React 18 + React Three Fiber solar-system dashboard. Built with Vite; output goes to `../app/static/`.

## Build

```bash
cd nexus-ui
npx vite build         # production build → ../app/static/
npx tsc --noEmit       # type-check only
```

## Architecture

```
main.tsx → App → NexusScene
  ├── Canvas (R3F)
  │     ├── Background (starfield, floor wave)
  │     ├── CeoNode (CEO reactor at center)
  │     ├── ReactorRing (instanced activity bars)
  │     ├── AgentNode × N (glass spheres orbiting CEO)
  │     ├── NeuralEdge × N (lines CEO → workers)
  │     ├── EdgeTaskLabel × N (floating task text)
  │     ├── HoloBrowser (browser viewport above Maya)
  │     ├── CameraDirector (fly-to on select, idle orbit)
  │     └── PostProcessing (Bloom, ChromaticAberration, Vignette, Scanline, Noise)
  └── DOM overlays (z-indexed above canvas)
        ├── ModelPill (backend indicator)
        ├── SmartIsland (notifications, queue, active tasks)
        ├── HudFrame (corner brackets)
        ├── CommandBar (CEO chat input)
        ├── SystemVitals (health status)
        ├── BrowserViewport (screenshot panel)
        ├── DesignPreviewPanel (frontend preview iframe)
        ├── OpsDrawer (routines, skills, approvals, email, team)
        ├── AgentDetailView (agent chat panel, shown when agent selected)
        └── BootOverlay (startup sequence)
```

## Store (`store.ts`)

Zustand store. All WebSocket events funnel through `handleEvent(event)`.

Key state:
- `agents: Record<string, AgentState>` — status, recentOutput, steps, checkpoints per agent
- `edges: EdgeState[]` — CEO → worker connection active/inactive state
- `wsStatus` — connected/offline
- `workQueue` — active/completed task queue
- `notifications` — last 10 notifications
- `selectedAgent` — which agent panel is open

Audio events bypass the store and go directly to module-level `_audioListeners` (avoids re-renders). Voice playback is a singleton — `useVoice` initialises it once regardless of how many components call the hook.

## WebSocket event → UI mapping

| Event | UI effect |
|---|---|
| `thinking` | CEO sphere pulses |
| `delegation` | Edge activates, worker sphere shifts to `working` state |
| `assistant` | Text appended to agent's recentOutput |
| `worker_step` | Step added to NodeFlowPanel |
| `worker_checkpoint` | Checkpoint diamond in NodeFlowPanel |
| `worker_done` | Worker sphere → `done` (bright), then back to idle after 3s |
| `audio` | Bark WAV plays via AudioQueue singleton |
| `queue_update` | SmartIsland QUEUE tab updates |
| `browser_navigated` | BrowserViewport + HoloBrowser show screenshot |
| `approval_requested` | OPS badge increments; opens Approvals tab |
| `routine_completed` | Notification in SmartIsland |

## PostProcessing note

`PostProcessing` is wrapped in `React.memo` and uses `multisampling={0}` on `EffectComposer`. **Do not remove either.** `memo` prevents pass-chain rebuilds on every WS event. `multisampling={0}` prevents whole-scene flicker from stacked MSAA on Chrome/ANGLE.

## Adding a new agent to the UI

1. Add position to `AGENT_POSITIONS` in `src/types.ts`
2. Add color to `AGENT_COLORS` in `src/types.ts`
3. Add radius to `AGENT_RADII` in `src/types.ts`
4. The agent node renders automatically from the `agents` store map
```

- [ ] **Step 8: Commit all READMEs**

```bash
cd /mnt/HC_Volume_105874680/virtual-company
git add README.md app/graph/README.md app/agents/README.md app/output/README.md app/services/README.md app/api/README.md nexus-ui/README.md
git commit -m "docs: add README.md for all major subsystems (graph, agents, output, services, api, ui)"
```

---

### Task 9: Final build + verification

- [ ] **Step 1: Full backend test suite**

```bash
docker exec virtual-company python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: no new failures vs. baseline.

- [ ] **Step 2: Frontend build**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/nexus-ui && npx vite build 2>&1 | grep -E "built in|error"
```

Expected: `✓ built in ~15s`.

- [ ] **Step 3: Smoke test pipeline double fix**

With the app running, send a task that triggers a worker with a `[SPEAK:]` tag (e.g., tell CEO "Ask Reinhard to say hello using [SPEAK: hello from backend]"). Confirm you hear the audio exactly ONCE.

- [ ] **Step 4: Final commit**

```bash
cd /mnt/HC_Volume_105874680/virtual-company
git add -A
git commit -m "build: full cleanup — pipeline fix, dead code removed, standup wired, READMEs complete"
```
