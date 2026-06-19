# JARVIS Phase 1 — Goal Persistence & Memory Threading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give NEXUS cross-session context continuity — persistent goals in SQLite, memories threaded by goal, an outcome-feedback record, a goals API, and CEO auto-loading active goals on session start.

**Architecture:** A new `app/services/goals.py` store (mirrors the existing `call_store.py` pattern) owns two tables in the shared `nexus_memory.db`: `goals` and `goal_outcomes`. `NexusState` gains goal fields so the active `goal_id` flows through the graph. `memory.save_memory` gains an optional `goal_id` column (added via an idempotent `ALTER TABLE` migration) so memories can be retrieved per goal. A read-only `GET /api/goals` endpoint exposes goals, and `ceo_node` injects active goals into the CEO prompt.

**Tech Stack:** Python 3.12 · FastAPI · SQLite (WAL) · LangGraph · pytest. Tests run in-container: `docker exec -w /app virtual-company python -m pytest <target> -v`. Server uses uvicorn `--reload`.

**Spec:** `docs/superpowers/specs/2026-06-16-jarvis-autonomy-upgrade-roadmap.md` — Phase 1 (F1.1–F1.7).

**Reality note (F1.7):** The roadmap's Quick Win #1 / GAP-011 (`max_revision_loops` guard) is **already resolved** — the revision loop was removed in commit `5c9b1f0` ("replace dead review loop with terminal CEO spoken wrap-up"). The current `nexus_graph.py` is linear (`ceo → workers → wrapup → END`) with no `route_after_review`. So F1.7 is re-scoped to **Task 7: remove the dead `review.py` + stale README**, which is the genuinely useful version of that item.

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `app/services/goals.py` | Goal + outcome CRUD store over `nexus_memory.db` | Create |
| `app/main.py` | Call `goal_store.init_db()` in lifespan | Modify |
| `app/graph/state.py` | Add goal fields to `NexusState` | Modify |
| `app/api/websocket.py` | Seed goal fields in initial graph state | Modify |
| `app/services/memory.py` | `goal_id` column + param; `get_memories_by_goal()` | Modify |
| `app/api/router.py` | `GET /api/goals` endpoint | Modify |
| `app/graph/nodes/ceo.py` | Inject active goals into CEO prompt | Modify |
| `app/graph/nodes/review.py` | Dead code — delete (Task 7) | Delete |
| `app/graph/README.md` | Remove stale review-loop topology docs | Modify |
| `tests/test_goals.py` | Goal + outcome store unit tests | Create |
| `tests/test_memory.py` | Add goal-threading tests | Modify |
| `tests/test_goals_api.py` | `/api/goals` endpoint test | Create |
| `tests/graph/test_ceo_goals.py` | CEO goal-injection test | Create |

**Execution protocol:** one Task at a time. After each Task, run its tests + the live check, report results, and get the user's go-ahead before the next. Order: 1 → 2 → 3 → 4 → 5 → 6 → 7. Tasks 1–6 are independent enough to also run in subagent-per-task mode; Task 5 depends on Task 1 (store) being merged.

---

## Task 1: Goal store module + tables

Creates the persistence layer. Mirrors `app/services/call_store.py` (separate module, shared `config.MEMORY_DB`, own `init_db`).

**Files:**
- Create: `app/services/goals.py`
- Modify: `app/main.py:29-30` (lifespan DB init)
- Test: `tests/test_goals.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_goals.py`:
```python
import pytest


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "test_goals.db"
    import app.services.goals as g
    original = g.DB_PATH
    g.DB_PATH = db
    g.init_db()
    yield g
    g.DB_PATH = original


def test_create_goal_returns_id(store):
    gid = store.create_goal("Ship the payments API", deadline="2026-07-01")
    assert isinstance(gid, str) and gid


def test_get_goals_active_only(store):
    a = store.create_goal("Active goal")
    b = store.create_goal("Done goal")
    store.update_goal_status(b, "done")
    active = store.get_goals(status="active")
    titles = {row["title"] for row in active}
    assert "Active goal" in titles
    assert "Done goal" not in titles


def test_get_goals_all(store):
    store.create_goal("One")
    store.create_goal("Two")
    assert len(store.get_goals()) == 2


def test_update_goal_status_persists(store):
    gid = store.create_goal("Movable")
    store.update_goal_status(gid, "done", outcome_score=0.8)
    row = store.get_goal(gid)
    assert row["status"] == "done"
    assert row["outcome_score"] == 0.8


def test_subtasks_roundtrip(store):
    gid = store.create_goal("With subtasks", subtasks=["a", "b", "c"])
    row = store.get_goal(gid)
    assert row["subtasks"] == ["a", "b", "c"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec -w /app virtual-company python -m pytest tests/test_goals.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.goals'`.

- [ ] **Step 3: Create `app/services/goals.py`**

```python
"""Persistent goals + outcomes over the shared nexus_memory.db."""
import json
import logging
import sqlite3
import uuid
from datetime import datetime

from app import config

logger  = logging.getLogger(__name__)
DB_PATH = config.MEMORY_DB


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH), timeout=5.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=5000")
    return c


def init_db() -> None:
    with _conn() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript("""
            CREATE TABLE IF NOT EXISTS goals (
                goal_id        TEXT PRIMARY KEY,
                parent_goal_id TEXT,
                title          TEXT NOT NULL,
                status         TEXT NOT NULL DEFAULT 'active',
                created_at     TEXT NOT NULL,
                deadline       TEXT,
                success_criteria TEXT,
                subtasks_json  TEXT NOT NULL DEFAULT '[]',
                outcome_score  REAL
            );
            CREATE TABLE IF NOT EXISTS goal_outcomes (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                goal_id        TEXT,
                task           TEXT NOT NULL,
                approach_taken TEXT,
                duration_ms    INTEGER,
                success_score  REAL,
                blockers_json  TEXT NOT NULL DEFAULT '[]',
                created_at     TEXT NOT NULL
            );
        """)


def create_goal(
    title: str,
    *,
    parent_goal_id: str | None = None,
    deadline: str | None = None,
    success_criteria: str | None = None,
    subtasks: list[str] | None = None,
) -> str:
    goal_id = uuid.uuid4().hex
    with _conn() as c:
        c.execute(
            "INSERT INTO goals (goal_id, parent_goal_id, title, status, created_at,"
            " deadline, success_criteria, subtasks_json)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (goal_id, parent_goal_id, title, "active", datetime.now().isoformat(),
             deadline, success_criteria, json.dumps(subtasks or [])),
        )
    return goal_id


def _row_to_goal(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["subtasks"] = json.loads(d.pop("subtasks_json") or "[]")
    return d


def get_goal(goal_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM goals WHERE goal_id=?", (goal_id,)).fetchone()
        return _row_to_goal(row) if row else None


def get_goals(status: str | None = None, limit: int = 50) -> list[dict]:
    with _conn() as c:
        if status:
            rows = c.execute(
                "SELECT * FROM goals WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM goals ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_row_to_goal(r) for r in rows]


def update_goal_status(goal_id: str, status: str, outcome_score: float | None = None) -> None:
    with _conn() as c:
        if outcome_score is None:
            c.execute("UPDATE goals SET status=? WHERE goal_id=?", (status, goal_id))
        else:
            c.execute(
                "UPDATE goals SET status=?, outcome_score=? WHERE goal_id=?",
                (status, outcome_score, goal_id),
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec -w /app virtual-company python -m pytest tests/test_goals.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Wire `init_db` into the lifespan**

In `app/main.py`, the lifespan currently has (around line 28-30):
```python
    # DB + memory
    from app.services import memory as mem_svc
    mem_svc.init_db()
```
Change it to:
```python
    # DB + memory
    from app.services import memory as mem_svc
    from app.services import goals as goal_store
    mem_svc.init_db()
    goal_store.init_db()
```

- [ ] **Step 6: Live verification**

`docker logs virtual-company --tail 8 2>&1 | grep -iE 'startup complete|Error'` → shows "Application startup complete", no errors.
`docker exec -w /app virtual-company python -c "from app.services import goals as g; print(sorted(c[1] for c in __import__('sqlite3').connect(str(g.DB_PATH)).execute('PRAGMA table_info(goals)')))"`
Expected: includes `created_at, deadline, goal_id, outcome_score, parent_goal_id, status, subtasks_json, success_criteria, title`.

- [ ] **Step 7: Commit**

```bash
git add app/services/goals.py app/main.py tests/test_goals.py
git commit -m "feat(goals): persistent goal store + outcomes table in nexus_memory.db

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Goal fields in NexusState + initial graph state

Threads the active goal through the orchestration graph (F1.1).

**Files:**
- Modify: `app/graph/state.py:8-24` (`NexusState`)
- Modify: `app/api/websocket.py:203-206` (initial state literal)
- Test: `tests/graph/test_ceo_goals.py` (created here, extended in Task 5)

- [ ] **Step 1: Write the failing test**

Create `tests/graph/test_ceo_goals.py`:
```python
def test_nexus_state_has_goal_fields():
    from app.graph.state import NexusState
    ann = NexusState.__annotations__
    assert "goal_id" in ann
    assert "parent_goal_id" in ann
    assert "deadline" in ann
    assert "success_criteria" in ann


def test_initial_state_seeds_goal_fields():
    import inspect
    import app.api.websocket as ws
    src = inspect.getsource(ws._run_and_stream)
    # The initial state dict must seed all four goal keys.
    for key in ("goal_id", "parent_goal_id", "deadline", "success_criteria"):
        assert f'"{key}"' in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec -w /app virtual-company python -m pytest tests/graph/test_ceo_goals.py -v`
Expected: FAIL — `assert "goal_id" in ann`.

- [ ] **Step 3: Add the fields to `NexusState`**

In `app/graph/state.py`, the `NexusState` class currently ends with:
```python
    worker_progress: dict  # {agent_id: {"step": int, "checkpoints": list[str]}}
```
Add below that line (still inside `NexusState`):
```python

    goal_id: str
    parent_goal_id: str
    deadline: str
    success_criteria: str
```

- [ ] **Step 4: Seed the fields in the initial graph state**

In `app/api/websocket.py`, the `_run_and_stream` initial state (around line 203-206) is:
```python
            {"task": task, "session_id": thread_id, "model": model,
             "source": "browser", "worker_results": [], "delegations": [],
             "artifacts": {}, "ceo_verdict": "approved", "revision_notes": "",
             "ceo_response": "", "worker_progress": {}},
```
Change it to:
```python
            {"task": task, "session_id": thread_id, "model": model,
             "source": "browser", "worker_results": [], "delegations": [],
             "artifacts": {}, "ceo_verdict": "approved", "revision_notes": "",
             "ceo_response": "", "worker_progress": {},
             "goal_id": "", "parent_goal_id": "", "deadline": "",
             "success_criteria": ""},
```

- [ ] **Step 5: Run test to verify it passes**

Run: `docker exec -w /app virtual-company python -m pytest tests/graph/test_ceo_goals.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Regression check + live**

Run: `docker exec -w /app virtual-company python -m pytest tests/test_websocket.py tests/graph/ -q`
Expected: PASS.
Live: `docker logs virtual-company --tail 6 2>&1 | grep -iE 'startup complete|Error'` → clean reload.

- [ ] **Step 7: Commit**

```bash
git add app/graph/state.py app/api/websocket.py tests/graph/test_ceo_goals.py
git commit -m "feat(graph): goal_id/deadline/success_criteria fields in NexusState

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Thread memories by goal_id

Adds an optional `goal_id` column to the existing `memories` table (idempotent migration, since `nexus_memory.db` already exists in the repo) plus a per-goal retrieval (F1.3).

**Files:**
- Modify: `app/services/memory.py:21-63` (`init_db`, `save_memory`), add `get_memories_by_goal`
- Test: `tests/test_memory.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_memory.py`:
```python
def test_save_memory_with_goal_id(mem):
    mem.save_memory("ceo", "Picked Postgres for payments", goal_id="goal-123")
    results = mem.get_memories_by_goal("goal-123")
    assert any("Postgres" in r for r in results)


def test_get_memories_by_goal_filters(mem):
    mem.save_memory("ceo", "Belongs to goal A", goal_id="A")
    mem.save_memory("ceo", "Belongs to goal B", goal_id="B")
    mem.save_memory("ceo", "No goal at all")
    a = mem.get_memories_by_goal("A")
    assert any("goal A" in r for r in a)
    assert not any("goal B" in r for r in a)
    assert not any("No goal" in r for r in a)


def test_save_memory_without_goal_still_works(mem):
    # Backward compatibility — goal_id is optional.
    mem.save_memory("ceo", "Plain memory, no goal")
    results = mem.get_relevant_memories("ceo", "Plain memory")
    assert any("Plain memory" in r for r in results)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec -w /app virtual-company python -m pytest tests/test_memory.py -k goal -v`
Expected: FAIL — `TypeError: save_memory() got an unexpected keyword argument 'goal_id'`.

- [ ] **Step 3: Add the idempotent migration to `init_db`**

In `app/services/memory.py`, the `init_db` function ends its `executescript` with the `user_preferences` table and a closing `""")`. Immediately after that `executescript(...)` call (still inside the `with _conn() as c:` block), add the column migration:
```python
        # Idempotent migration: add goal_id to pre-existing memories tables.
        cols = {r["name"] for r in c.execute("PRAGMA table_info(memories)")}
        if "goal_id" not in cols:
            c.execute("ALTER TABLE memories ADD COLUMN goal_id TEXT")
```

- [ ] **Step 4: Add the `goal_id` parameter to `save_memory`**

Replace the `save_memory` function with:
```python
def save_memory(
    agent_id: str,
    content: str,
    mem_type: str = "conversation",
    importance: float = 0.5,
    goal_id: str | None = None,
) -> None:
    now = datetime.now().isoformat()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO memories (agent_id, mem_type, content, importance, created_at, goal_id)"
            " VALUES (?,?,?,?,?,?)",
            (agent_id, mem_type, content, importance, now, goal_id),
        )
        c.execute(
            "INSERT INTO memories_fts (rowid, content, agent_id) VALUES (?,?,?)",
            (cur.lastrowid, content, agent_id),
        )
```

- [ ] **Step 5: Add `get_memories_by_goal`**

In `app/services/memory.py`, add after `get_shared_memories`:
```python
def get_memories_by_goal(goal_id: str, limit: int = 20) -> list[str]:
    """All memories tagged with a goal_id, newest first — no keyword match needed."""
    try:
        with _conn() as c:
            rows = c.execute("""
                SELECT content
                FROM   memories
                WHERE  goal_id = ?
                ORDER  BY created_at DESC
                LIMIT  ?
            """, (goal_id, limit)).fetchall()
            return [r["content"] for r in rows]
    except sqlite3.OperationalError as exc:
        logger.warning("goal memory query failed: %s", exc)
        return []
```

- [ ] **Step 6: Run test to verify it passes**

Run: `docker exec -w /app virtual-company python -m pytest tests/test_memory.py -k goal -v`
Expected: PASS (2 goal tests; `test_save_memory_without_goal_still_works` matches `-k goal` only if it contains "goal" — run the next step's broad suite to confirm it too).

- [ ] **Step 7: Full memory suite + live migration check**

Run: `docker exec -w /app virtual-company python -m pytest tests/test_memory.py -v`
Expected: PASS (all existing + new tests).
Live: confirm the live DB migrated cleanly:
`docker exec -w /app virtual-company python -c "import sqlite3; from app import config; print('goal_id' in {r[1] for r in sqlite3.connect(str(config.MEMORY_DB)).execute('PRAGMA table_info(memories)')})"`
Expected: `True`.

- [ ] **Step 8: Commit**

```bash
git add app/services/memory.py tests/test_memory.py
git commit -m "feat(memory): thread memories by goal_id (idempotent column migration)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: GET /api/goals endpoint

Read-only goal retrieval for the UI and CEO context (F1.4).

**Files:**
- Modify: `app/api/router.py` (add endpoint after the Health section, ~line 558)
- Test: `tests/test_goals_api.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_goals_api.py`:
```python
import pytest
from httpx import AsyncClient, ASGITransport


@pytest.fixture
def goal_db(tmp_path):
    import app.services.goals as g
    original = g.DB_PATH
    g.DB_PATH = tmp_path / "api_goals.db"
    g.init_db()
    yield g
    g.DB_PATH = original


@pytest.mark.asyncio
async def test_api_goals_returns_active(goal_db):
    goal_db.create_goal("Active one")
    done = goal_db.create_goal("Done one")
    goal_db.update_goal_status(done, "done")

    from app.api import router as router_module
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router_module.router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/goals?status=active")

    assert res.status_code == 200
    titles = {g["title"] for g in res.json()["goals"]}
    assert "Active one" in titles
    assert "Done one" not in titles


@pytest.mark.asyncio
async def test_api_goals_all_when_no_status(goal_db):
    goal_db.create_goal("G1")
    goal_db.create_goal("G2")

    from app.api import router as router_module
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router_module.router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/goals")

    assert res.status_code == 200
    assert len(res.json()["goals"]) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec -w /app virtual-company python -m pytest tests/test_goals_api.py -v`
Expected: FAIL — 404 (route not defined), so `res.status_code == 200` fails.

- [ ] **Step 3: Add the import**

In `app/api/router.py`, near the other service imports (around line 27, `from app.services import call_store`), add:
```python
from app.services import goals as goal_store
```

- [ ] **Step 4: Add the endpoint**

In `app/api/router.py`, immediately after the `api_health` function (the Health section ends at ~line 558, before the `# ── Outbound call` comment), add:
```python
# ── Goals ──────────────────────────────────────────────────────────────────────

@router.get("/api/goals")
async def api_goals(status: str | None = None):
    """Active or all persistent goals (status=active|done|... or omit for all)."""
    return {"goals": goal_store.get_goals(status=status)}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `docker exec -w /app virtual-company python -m pytest tests/test_goals_api.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Live verification**

Run: `curl -s "http://127.0.0.1:3031/api/goals?status=active"` (after reload).
Expected: JSON `{"goals": [...]}` (likely `{"goals": []}` if none created yet) — HTTP 200, valid JSON.

- [ ] **Step 7: Commit**

```bash
git add app/api/router.py tests/test_goals_api.py
git commit -m "feat(api): GET /api/goals — active/all persistent goals

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: CEO auto-loads active goals into prompt context

On each CEO turn, prepend a compact list of active goals to the task so planning is goal-aware (F1.5). Depends on Task 1 (`goal_store`).

**Files:**
- Modify: `app/graph/nodes/ceo.py:32-50` (`ceo_node`)
- Test: `tests/graph/test_ceo_goals.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/graph/test_ceo_goals.py`:
```python
def test_build_goal_context_lists_active_goals(monkeypatch):
    import app.graph.nodes.ceo as ceo

    def fake_get_goals(status=None, limit=50):
        assert status == "active"
        return [
            {"title": "Ship payments API", "deadline": "2026-07-01"},
            {"title": "Refactor auth", "deadline": None},
        ]

    monkeypatch.setattr(ceo.goal_store, "get_goals", fake_get_goals)
    block = ceo._build_goal_context()
    assert "Ship payments API" in block
    assert "2026-07-01" in block
    assert "Refactor auth" in block


def test_build_goal_context_empty_when_no_goals(monkeypatch):
    import app.graph.nodes.ceo as ceo
    monkeypatch.setattr(ceo.goal_store, "get_goals", lambda status=None, limit=50: [])
    assert ceo._build_goal_context() == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec -w /app virtual-company python -m pytest tests/graph/test_ceo_goals.py -k goal_context -v`
Expected: FAIL — `AttributeError: module 'app.graph.nodes.ceo' has no attribute 'goal_store'`.

- [ ] **Step 3: Add the import + helper, and inject into `ceo_node`**

In `app/graph/nodes/ceo.py`, add to the imports (after `from app.output import pipeline`):
```python
from app.services import goals as goal_store
```
Add this helper above `ceo_node`:
```python
def _build_goal_context() -> str:
    """Compact list of active goals injected into CEO planning prompts."""
    try:
        active = goal_store.get_goals(status="active", limit=10)
    except Exception:
        return ""
    if not active:
        return ""
    lines = []
    for g in active:
        deadline = g.get("deadline")
        suffix = f" (due {deadline})" if deadline else ""
        lines.append(f"  - {g['title']}{suffix}")
    return "ACTIVE GOALS:\n" + "\n".join(lines) + "\n\n"
```
In `ceo_node`, the task is currently built as:
```python
    task = state["task"]
    if state.get("revision_notes"):
        task = f"{task}\n\n[REVISION REQUESTED]\n{state['revision_notes']}"
```
Change it to:
```python
    task = state["task"]
    goal_context = _build_goal_context()
    if goal_context:
        task = f"{goal_context}{task}"
    if state.get("revision_notes"):
        task = f"{task}\n\n[REVISION REQUESTED]\n{state['revision_notes']}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec -w /app virtual-company python -m pytest tests/graph/test_ceo_goals.py -k goal_context -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Full graph suite + live**

Run: `docker exec -w /app virtual-company python -m pytest tests/graph/ tests/test_delegation.py -q`
Expected: PASS.
Live: `docker logs virtual-company --tail 6 2>&1 | grep -iE 'startup complete|Error'` → clean reload.

- [ ] **Step 6: Commit**

```bash
git add app/graph/nodes/ceo.py tests/graph/test_ceo_goals.py
git commit -m "feat(ceo): inject active goals into CEO planning context

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Outcome feedback record

Persist `(goal_id, task, approach_taken, duration_ms, success_score, blockers)` so future learning phases can mine it (F1.6). The `goal_outcomes` table already exists from Task 1; this adds the write/read API.

**Files:**
- Modify: `app/services/goals.py` (add `save_outcome`, `get_outcomes`)
- Test: `tests/test_goals.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_goals.py`:
```python
def test_save_and_get_outcome(store):
    gid = store.create_goal("Deploy service")
    store.save_outcome(
        goal_id=gid,
        task="Deploy on port 8080",
        approach_taken="docker compose up",
        duration_ms=4200,
        success_score=0.3,
        blockers=["port 8080 conflict"],
    )
    outs = store.get_outcomes(goal_id=gid)
    assert len(outs) == 1
    assert outs[0]["task"] == "Deploy on port 8080"
    assert outs[0]["success_score"] == 0.3
    assert outs[0]["blockers"] == ["port 8080 conflict"]


def test_get_outcomes_filters_by_goal(store):
    g1 = store.create_goal("G1")
    g2 = store.create_goal("G2")
    store.save_outcome(goal_id=g1, task="t1", success_score=0.9)
    store.save_outcome(goal_id=g2, task="t2", success_score=0.5)
    outs = store.get_outcomes(goal_id=g1)
    assert len(outs) == 1
    assert outs[0]["task"] == "t1"


def test_save_outcome_without_goal(store):
    store.save_outcome(task="orphan task", success_score=0.7)
    outs = store.get_outcomes()
    assert any(o["task"] == "orphan task" for o in outs)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec -w /app virtual-company python -m pytest tests/test_goals.py -k outcome -v`
Expected: FAIL — `AttributeError: module 'app.services.goals' has no attribute 'save_outcome'`.

- [ ] **Step 3: Add `save_outcome` and `get_outcomes`**

In `app/services/goals.py`, add at the end of the file:
```python
def save_outcome(
    task: str,
    *,
    goal_id: str | None = None,
    approach_taken: str | None = None,
    duration_ms: int | None = None,
    success_score: float | None = None,
    blockers: list[str] | None = None,
) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO goal_outcomes (goal_id, task, approach_taken, duration_ms,"
            " success_score, blockers_json, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (goal_id, task, approach_taken, duration_ms, success_score,
             json.dumps(blockers or []), datetime.now().isoformat()),
        )


def _row_to_outcome(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["blockers"] = json.loads(d.pop("blockers_json") or "[]")
    return d


def get_outcomes(goal_id: str | None = None, limit: int = 50) -> list[dict]:
    with _conn() as c:
        if goal_id:
            rows = c.execute(
                "SELECT * FROM goal_outcomes WHERE goal_id=? ORDER BY created_at DESC LIMIT ?",
                (goal_id, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM goal_outcomes ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_row_to_outcome(r) for r in rows]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec -w /app virtual-company python -m pytest tests/test_goals.py -k outcome -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Full goals suite + live**

Run: `docker exec -w /app virtual-company python -m pytest tests/test_goals.py -v`
Expected: PASS (all tests).
Live: `docker logs virtual-company --tail 6 2>&1 | grep -iE 'startup complete|Error'` → clean reload.

- [ ] **Step 6: Commit**

```bash
git add app/services/goals.py tests/test_goals.py
git commit -m "feat(goals): outcome feedback record (task/approach/score/blockers)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Remove the dead review loop (re-scoped F1.7)

GAP-011's infinite-loop risk is already gone (loop removed in `5c9b1f0`). `app/graph/nodes/review.py` and the README's review-loop topology are stale leftovers — delete them so the codebase matches reality and no future worker wires a misleading node back in.

**Pre-check:** confirm `ceo_review_node` is genuinely unused before deleting.
Run: `docker exec -w /app virtual-company grep -rn "ceo_review_node\|nodes.review\|nodes import review" app/ --include='*.py'`
Expected: matches ONLY inside `app/graph/nodes/review.py` itself (its own definition). If any other `.py` imports it, STOP — it is still wired; do not delete, report instead.

**Files:**
- Delete: `app/graph/nodes/review.py`
- Modify: `app/graph/README.md` (remove review-loop topology)
- Test: existing `tests/test_wrapup.py` + graph suite (no new test; this is a deletion)

- [ ] **Step 1: Delete the dead node**

```bash
git rm app/graph/nodes/review.py
```

- [ ] **Step 2: Fix the README topology**

In `app/graph/README.md`, the graph diagram (around line 26-31) and the section describing `ceo_review_node` / `route_after_review()` (around line 110-114, 153) describe a loop that no longer exists. Update the diagram so it reads `ceo_node → [workers fan-out] → ceo_wrapup_node → END`, and delete the `ceo_review_node` / `route_after_review` / "loops back to ceo_node" prose. Match the actual topology in `app/graph/nexus_graph.py` (linear, no review node). Leave the `ceo_verdict` / `revision_notes` state-table rows in place — those fields still exist in `NexusState` and are set by `wrapup.py`.

- [ ] **Step 3: Verify nothing broke**

Run: `docker exec -w /app virtual-company python -m pytest tests/graph/ tests/test_wrapup.py tests/test_delegation.py -q`
Expected: PASS (no import errors from the deletion).
Run: `docker exec -w /app virtual-company python -c "from app.graph.nexus_graph import build_nexus_graph; print('graph import OK')"`
Expected: `graph import OK`.
Live: `docker logs virtual-company --tail 6 2>&1 | grep -iE 'startup complete|Error'` → clean reload.

- [ ] **Step 4: Commit**

```bash
git add app/graph/nodes/review.py app/graph/README.md
git commit -m "chore(graph): remove dead ceo_review_node + stale review-loop docs (GAP-011 already resolved)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Done criteria

- `goals` + `goal_outcomes` tables created in `nexus_memory.db`; `goal_store.init_db()` runs in lifespan.
- `NexusState` carries `goal_id`, `parent_goal_id`, `deadline`, `success_criteria`; initial graph state seeds them.
- `memory.save_memory(..., goal_id=...)` works; `memory.get_memories_by_goal()` returns goal-threaded memories; existing memories DB migrated with a `goal_id` column.
- `GET /api/goals` returns active/all goals as JSON.
- CEO planning prompt lists active goals when any exist.
- `goal_outcomes` write/read API (`save_outcome` / `get_outcomes`) persists task results with scores + blockers.
- Dead `review.py` removed; README matches the real linear topology.
- All new + existing tests green for goals/memory/graph/health selectors.

## Out of scope (later phases)

- Auto-creating goals from CEO task decomposition and auto-scoring outcomes (Phase 2: F2.1–F2.4).
- Embedding/semantic memory and learned routing (Phase 4).
- These tasks lay the data layer Phase 2 builds on; no goal is auto-generated yet — goals are created via `goal_store.create_goal()` (programmatic) or future endpoints.
