# Phase 2 — Routines Engine, Claude Design Panel & Morning Standup

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the three features deferred from Phase 1: a race-condition-safe cron scheduler (Routines Engine), a live HTML design preview panel (Claude Design), and a morning standup briefing that emails Saurav daily at 09:00 IST.

**Architecture:** The scheduler is a pure Python asyncio loop (`scheduler.py`) that reads `nexus_routines.json`, fires each routine at most once per scheduled minute using a dedup key, and stores run logs. The design preview is a single `write_preview()` function that Emilia calls as a tool, writing HTML to `app/static/previews/index.html` which the floating island iframe already points to. The standup is a built-in routine that calls `run_agent("ceo", standup_prompt, ...)` and sends the result by email. A `broadcast_event()` function in `websocket.py` lets the scheduler push `routine_completed` and `design_preview_updated` events to all connected browser tabs.

**Tech Stack:** Python 3.12, FastAPI, asyncio, `croniter>=1.3.8` (already installed as pytz is), vanilla JS, SQLite (existing). All tests run inside Docker: `docker exec virtual-company python -m pytest /app/tests/test_*.py -v`.

**Base SHA (start of this plan):** `dcd4696`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `app/services/scheduler.py` | Asyncio cron loop, `_maybe_fire()`, `run_routine()`, run log |
| Create | `app/services/standup.py` | Compile state → standup prompt → run CEO agent → email |
| Create | `app/services/browser.py` | `write_preview(html)` — writes HTML to static/previews/ |
| Create | `nexus_routines.json` (at `/home/subaru/projects/`) | Routine definitions (seed data) |
| Create | `app/static/previews/.gitkeep` | Ensures previews dir exists in git |
| Create | `tests/test_scheduler.py` | Tests for `_tick()`, `_maybe_fire()`, `load_routines()` |
| Create | `tests/test_standup.py` | Tests for `generate_standup_prompt()` |
| Modify | `app/api/websocket.py` | Add `_sessions` global set + `broadcast_event()` |
| Modify | `app/api/router.py` | GET/POST/PUT/DELETE `/api/routines`, POST `/api/routines/{id}/run`, GET `/api/routines/{id}/logs`, POST `/api/design/preview` |
| Modify | `app/agents/executor.py` | Add `write_preview` case to `_execute_tool()` |
| Modify | `app/agents/definitions.py` | Add `write_preview` tool instruction to Emilia's persona |
| Modify | `app/main.py` | Start scheduler loop on startup |
| Modify | `requirements.txt` | Add `croniter>=1.3.8` |
| Modify | `app/static/app-v5.js` | Routines panel open/render, handle `routine_completed` + `design_preview_updated` WS events |
| Modify | `app/static/index.html` | Add routines panel HTML (mirrors skills panel structure) |
| Modify | `app/static/style-v5.css` | Routine card styles, status badge colours |

---

## Task 1: Add croniter + create nexus_routines.json seed

**Files:**
- Modify: `requirements.txt`
- Create: `/home/subaru/projects/nexus_routines.json`
- Create: `app/static/previews/.gitkeep`

- [ ] **Step 1: Add croniter to requirements.txt**

Open `requirements.txt` and add this line:
```
croniter>=1.3.8
```

- [ ] **Step 2: Rebuild the container to install croniter**

```bash
cd /home/subaru/projects/virtual-company
docker compose build --no-cache && docker compose up -d
sleep 8
docker exec virtual-company python -c "from croniter import croniter; print('croniter OK')"
```

Expected: `croniter OK`

- [ ] **Step 3: Create nexus_routines.json**

Create the file at `/home/subaru/projects/nexus_routines.json` (this is WORK_DIR inside the container):

```json
[
  {
    "id": "morning_standup",
    "name": "Morning Executive Briefing",
    "description": "CEO compiles overnight work and emails the daily standup to Saurav",
    "agent": "ceo",
    "schedule": "0 9 * * *",
    "timezone": "Asia/Kolkata",
    "prompt": "Generate today's morning executive briefing for Saurav. Summarize: active projects, pending queue items, and recent completions. Keep it 200-300 words. Write in first person as Subaru. Then immediately email it using [EMAIL_USER:Subaru Morning Briefing] followed by the briefing text.",
    "enabled": true,
    "last_run": null,
    "last_status": null,
    "run_count": 0
  },
  {
    "id": "nightly_code_review",
    "name": "Nightly Code Review",
    "description": "Backend scans the repo for TODOs and code quality issues",
    "agent": "backend",
    "schedule": "0 23 * * *",
    "timezone": "Asia/Kolkata",
    "prompt": "Scan /app for TODO comments and obvious code quality issues. Report a brief summary (under 200 words).",
    "enabled": false,
    "last_run": null,
    "last_status": null,
    "run_count": 0
  }
]
```

- [ ] **Step 4: Create previews directory**

```bash
mkdir -p /home/subaru/projects/virtual-company/app/static/previews
touch /home/subaru/projects/virtual-company/app/static/previews/.gitkeep
```

- [ ] **Step 5: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add requirements.txt app/static/previews/.gitkeep
git commit -m "feat: add croniter, create previews dir"
```

Note: `nexus_routines.json` lives outside the repo at `/home/subaru/projects/` and is gitignored by design.

---

## Task 2: Add broadcast_event to websocket.py

**Files:**
- Modify: `app/api/websocket.py`

The scheduler and standup services need to push events to all connected browser tabs. This task adds a global session registry and a `broadcast_event()` function.

- [ ] **Step 1: Add module-level session set to websocket.py**

At the top of `app/api/websocket.py`, after the imports, add:

```python
# Module-level registry of active WebSocket sessions for broadcasting
_sessions: set["Session"] = set()


async def broadcast_event(data: dict) -> None:
    """Send an event to all currently connected WebSocket sessions."""
    for session in list(_sessions):
        try:
            await session.send(data)
        except Exception:
            pass
```

- [ ] **Step 2: Register sessions in ws_endpoint**

In `ws_endpoint()`, add the session to `_sessions` right after `await ws.accept()`:

```python
async def ws_endpoint(ws: WebSocket, model: str = Query(default="claude")) -> None:
    session = Session(ws, model)
    await ws.accept()
    _sessions.add(session)          # ← add this line
    ...
```

And at the end of `ws_endpoint`, in the `finally` block, remove from `_sessions`:

```python
    finally:
        _sessions.discard(session)  # ← add this line
        session.cancel_all()
```

- [ ] **Step 3: Verify no import errors**

```bash
docker exec virtual-company curl -s http://localhost:3030/api/capabilities > /dev/null && echo OK
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/api/websocket.py
git commit -m "feat: add broadcast_event() for scheduler→browser notifications"
```

---

## Task 3: Scheduler service (TDD)

**Files:**
- Create: `app/services/scheduler.py`
- Create: `tests/test_scheduler.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_scheduler.py`:

```python
import json
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, AsyncMock


@pytest.fixture
def routines_file(tmp_path):
    f = tmp_path / "nexus_routines.json"
    f.write_text(json.dumps([
        {
            "id": "test_routine",
            "name": "Test",
            "agent": "ceo",
            "schedule": "* * * * *",   # every minute
            "timezone": "UTC",
            "prompt": "hello",
            "enabled": True,
            "last_run": None,
            "last_status": None,
            "run_count": 0,
        }
    ]))
    return f


def test_load_routines_returns_list(tmp_path, routines_file):
    from app.services.scheduler import load_routines
    with patch("app.services.scheduler.ROUTINES_FILE", routines_file):
        routines = load_routines()
        assert len(routines) == 1
        assert routines[0]["id"] == "test_routine"


def test_load_routines_missing_file(tmp_path):
    from app.services.scheduler import load_routines
    missing = tmp_path / "no_such_file.json"
    with patch("app.services.scheduler.ROUTINES_FILE", missing):
        assert load_routines() == []


def test_maybe_fire_triggers_within_window(routines_file):
    """A routine due within ±30 s should be added to fired dict."""
    from app.services.scheduler import _maybe_fire
    import asyncio

    routine = {
        "id": "r1", "schedule": "* * * * *",
        "timezone": "UTC", "enabled": True,
        "prompt": "x", "agent": "ceo",
    }
    fired = {}
    tasks_created = []

    def fake_create_task(coro):
        coro.close()
        tasks_created.append(True)

    with patch("asyncio.create_task", side_effect=fake_create_task):
        _maybe_fire(routine, fired)

    assert len(tasks_created) == 1
    assert len(fired) == 1


def test_maybe_fire_no_double_fire(routines_file):
    """Same routine must not fire twice for the same minute."""
    from app.services.scheduler import _maybe_fire

    routine = {
        "id": "r1", "schedule": "* * * * *",
        "timezone": "UTC", "enabled": True,
        "prompt": "x", "agent": "ceo",
    }
    fired = {}
    tasks_created = []

    def fake_create_task(coro):
        coro.close()
        tasks_created.append(True)

    with patch("asyncio.create_task", side_effect=fake_create_task):
        _maybe_fire(routine, fired)
        _maybe_fire(routine, fired)   # second call same minute

    assert len(tasks_created) == 1   # only fired once


def test_maybe_fire_disabled_routine_skipped():
    from app.services.scheduler import _maybe_fire
    routine = {
        "id": "r1", "schedule": "* * * * *",
        "timezone": "UTC", "enabled": False,
        "prompt": "x", "agent": "ceo",
    }
    fired = {}
    tasks_created = []

    with patch("asyncio.create_task", side_effect=lambda c: (c.close(), tasks_created.append(True))):
        _maybe_fire(routine, fired)

    assert len(tasks_created) == 0


def test_update_routine_run(tmp_path, routines_file):
    from app.services.scheduler import update_routine_run, load_routines
    logs_file = tmp_path / "nexus_routine_logs.json"

    with patch("app.services.scheduler.ROUTINES_FILE", routines_file), \
         patch("app.services.scheduler.ROUTINE_LOGS_FILE", logs_file):
        update_routine_run("test_routine", "success", "output text")
        routines = load_routines()
        assert routines[0]["last_status"] == "success"
        assert routines[0]["run_count"] == 1
        assert logs_file.exists()


def test_get_routine_logs(tmp_path):
    from app.services.scheduler import get_routine_logs, _append_run_log
    logs_file = tmp_path / "nexus_routine_logs.json"

    with patch("app.services.scheduler.ROUTINE_LOGS_FILE", logs_file):
        _append_run_log("r1", "success", "output1")
        _append_run_log("r2", "error",   "output2")
        _append_run_log("r1", "success", "output3")

        logs = get_routine_logs("r1")
        assert len(logs) == 2
        assert all(l["routine_id"] == "r1" for l in logs)
```

- [ ] **Step 2: Run — expect failure**

```bash
docker exec virtual-company python -m pytest /app/tests/test_scheduler.py -v 2>&1 | tail -5
```

Expected: `ImportError` — `app.services.scheduler` doesn't exist.

- [ ] **Step 3: Write app/services/scheduler.py**

```python
"""
Cron-based routine scheduler.

Race-condition-safe: uses a per-minute fire key so a routine fires
at most once per scheduled minute, even when the 30-second loop
interval is shorter than the minimum 1-minute cron granularity.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pytz
from croniter import croniter

from app import config

logger = logging.getLogger(__name__)

ROUTINES_FILE    = config.WORK_DIR / "nexus_routines.json"
ROUTINE_LOGS_FILE = config.WORK_DIR / "nexus_routine_logs.json"


# ── Persistence helpers ────────────────────────────────────────────────────────

def load_routines() -> list[dict]:
    if not ROUTINES_FILE.exists():
        return []
    try:
        return json.loads(ROUTINES_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("load_routines failed: %s", exc)
        return []


def save_routines(routines: list[dict]) -> None:
    ROUTINES_FILE.write_text(json.dumps(routines, indent=2), encoding="utf-8")


def update_routine_run(routine_id: str, status: str, output: str) -> None:
    """Persist last_run, last_status, run_count to nexus_routines.json."""
    routines = load_routines()
    for r in routines:
        if r["id"] == routine_id:
            r["last_run"]    = datetime.now().isoformat()
            r["last_status"] = status
            r["run_count"]   = r.get("run_count", 0) + 1
            break
    save_routines(routines)
    _append_run_log(routine_id, status, output)


def _append_run_log(routine_id: str, status: str, output: str) -> None:
    logs: list[dict] = []
    if ROUTINE_LOGS_FILE.exists():
        try:
            logs = json.loads(ROUTINE_LOGS_FILE.read_text())
        except Exception:
            pass
    logs.append({
        "routine_id": routine_id,
        "status":     status,
        "output":     output[:2000],
        "timestamp":  datetime.now().isoformat(),
    })
    ROUTINE_LOGS_FILE.write_text(
        json.dumps(logs[-200:], indent=2), encoding="utf-8"
    )


def get_routine_logs(routine_id: str, limit: int = 10) -> list[dict]:
    if not ROUTINE_LOGS_FILE.exists():
        return []
    try:
        logs = json.loads(ROUTINE_LOGS_FILE.read_text())
        return [l for l in reversed(logs) if l["routine_id"] == routine_id][:limit]
    except Exception:
        return []


# ── Routine execution ──────────────────────────────────────────────────────────

async def run_routine(routine: dict) -> str:
    """Execute a routine: run the agent, store logs, broadcast completion."""
    from app.agents.executor import run_agent
    from app.api.websocket import broadcast_event

    routine_id  = routine["id"]
    output_acc: list[str] = []

    async def _collect(data: dict) -> None:
        if data.get("type") == "assistant":
            for blk in data.get("message", {}).get("content", []):
                if blk.get("type") == "text" and blk["text"]:
                    output_acc.append(blk["text"])

    logger.info("Running routine '%s'", routine_id)
    try:
        await run_agent(routine["agent"], routine["prompt"], _collect, model="claude")
        output = "".join(output_acc)
        status = "success"
    except Exception as exc:
        output = f"[Error: {exc}]"
        status = "error"
        logger.error("Routine '%s' failed: %s", routine_id, exc)

    update_routine_run(routine_id, status, output)

    await broadcast_event({
        "type":       "routine_completed",
        "routine_id": routine_id,
        "status":     status,
        "output":     output[:500],
        "timestamp":  datetime.now().isoformat(),
    })

    return output


# ── Scheduler loop ─────────────────────────────────────────────────────────────

async def start_scheduler_loop() -> None:
    """Check routines every 30 s; fire each at most once per scheduled minute."""
    logger.info("Subaru Scheduler started.")
    fired: dict[str, str] = {}   # fire_key → fired_at (ISO)

    while True:
        try:
            _tick(fired)
        except Exception as exc:
            logger.error("Scheduler tick error: %s", exc)
        await asyncio.sleep(30)


def _tick(fired: dict) -> None:
    """Evaluate all routines and schedule tasks for those due now."""
    for routine in load_routines():
        if not routine.get("enabled", True):
            continue
        try:
            _maybe_fire(routine, fired)
        except Exception as exc:
            logger.warning("Routine '%s' check error: %s", routine.get("id"), exc)

    # Prune fire keys older than 2 minutes to keep the dict lean
    cutoff = (datetime.utcnow() - timedelta(minutes=2)).isoformat()
    for k in [k for k, v in list(fired.items()) if v < cutoff]:
        fired.pop(k, None)


def _maybe_fire(routine: dict, fired: dict) -> None:
    """Schedule routine if its next run falls within ±30 s of now."""
    tz_name = routine.get("timezone", "UTC")
    try:
        tz = pytz.timezone(tz_name)
    except Exception:
        tz = pytz.UTC

    now_local = datetime.now(tz)
    now_naive = now_local.replace(tzinfo=None)

    # Anchor one minute back so get_next() returns the most recent scheduled time
    cron       = croniter(routine["schedule"], now_naive - timedelta(seconds=61))
    next_naive = cron.get_next(datetime)
    diff       = (next_naive - now_naive).total_seconds()

    if not (-30 <= diff <= 30):
        return   # not in the firing window

    fire_key = f"{routine['id']}:{next_naive.strftime('%Y%m%d%H%M')}"
    if fire_key in fired:
        return   # already fired this minute

    fired[fire_key] = datetime.utcnow().isoformat()
    asyncio.create_task(run_routine(routine))
    logger.info("Fired routine '%s' (schedule=%s)", routine["id"], routine["schedule"])
```

- [ ] **Step 4: Run tests — expect pass**

```bash
docker exec virtual-company python -m pytest /app/tests/test_scheduler.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Run full suite to confirm no regressions**

```bash
docker exec virtual-command python -m pytest /app/tests/ -v 2>&1 | tail -5
```

Expected: 30 tests pass (23 existing + 7 new).

- [ ] **Step 6: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/services/scheduler.py tests/test_scheduler.py
git commit -m "feat: race-condition-safe cron scheduler with per-minute dedup"
```

---

## Task 4: Routines API endpoints

**Files:**
- Modify: `app/api/router.py`

- [ ] **Step 1: Add scheduler imports to router.py**

At the top of `app/api/router.py`, after existing imports, add:

```python
from app.services.scheduler import (
    load_routines, save_routines, run_routine, get_routine_logs
)
```

- [ ] **Step 2: Add the 6 routines endpoints**

Add these routes after the existing `/api/skills` endpoints in `app/api/router.py`:

```python
# ── Routines ───────────────────────────────────────────────────────────────────

@router.get("/api/routines")
async def api_routines_list():
    return load_routines()


@router.post("/api/routines")
async def api_routines_create(body: dict):
    required = {"id", "name", "agent", "schedule", "prompt"}
    missing  = required - set(body.keys())
    if missing:
        return JSONResponse({"ok": False, "error": f"Missing fields: {missing}"}, status_code=400)
    import re
    if not re.match(r'^[a-zA-Z0-9_-]+$', body["id"]):
        return JSONResponse({"ok": False, "error": "Invalid id format"}, status_code=400)
    routines = load_routines()
    if any(r["id"] == body["id"] for r in routines):
        return JSONResponse({"ok": False, "error": "Routine id already exists"}, status_code=409)
    routine = {
        "id":          body["id"],
        "name":        body["name"],
        "description": body.get("description", ""),
        "agent":       body["agent"],
        "schedule":    body["schedule"],
        "timezone":    body.get("timezone", "Asia/Kolkata"),
        "prompt":      body["prompt"],
        "enabled":     body.get("enabled", True),
        "last_run":    None,
        "last_status": None,
        "run_count":   0,
    }
    routines.append(routine)
    save_routines(routines)
    return {"ok": True, "routine": routine}


@router.put("/api/routines/{routine_id}")
async def api_routines_update(routine_id: str, body: dict):
    routines = load_routines()
    for r in routines:
        if r["id"] == routine_id:
            updatable = {"name", "description", "schedule", "timezone", "prompt", "enabled"}
            for k in updatable:
                if k in body:
                    r[k] = body[k]
            save_routines(routines)
            return {"ok": True, "routine": r}
    return JSONResponse({"ok": False, "error": "Routine not found"}, status_code=404)


@router.delete("/api/routines/{routine_id}")
async def api_routines_delete(routine_id: str):
    routines = load_routines()
    updated  = [r for r in routines if r["id"] != routine_id]
    if len(updated) == len(routines):
        return JSONResponse({"ok": False, "error": "Routine not found"}, status_code=404)
    save_routines(updated)
    return {"ok": True}


@router.post("/api/routines/{routine_id}/run")
async def api_routines_run(routine_id: str):
    routines = load_routines()
    routine  = next((r for r in routines if r["id"] == routine_id), None)
    if not routine:
        return JSONResponse({"ok": False, "error": "Routine not found"}, status_code=404)
    asyncio.create_task(run_routine(routine))
    return {"ok": True, "message": f"Routine '{routine_id}' triggered"}


@router.get("/api/routines/{routine_id}/logs")
async def api_routines_logs(routine_id: str, limit: int = 10):
    return get_routine_logs(routine_id, limit)
```

- [ ] **Step 3: Verify endpoints are reachable**

```bash
docker exec virtual-company curl -s http://localhost:3030/api/routines | python3 -m json.tool | head -5
```

Expected: JSON array with the two seed routines (morning_standup + nightly_code_review).

- [ ] **Step 4: Test create + delete**

```bash
docker exec virtual-company curl -s -X POST http://localhost:3030/api/routines \
  -H "Content-Type: application/json" \
  -d '{"id":"smoke_test","name":"Smoke","agent":"ceo","schedule":"* * * * *","prompt":"hello"}' && \
docker exec virtual-company curl -s -X DELETE http://localhost:3030/api/routines/smoke_test
```

Expected: `{"ok":true,...}` then `{"ok":true}`.

- [ ] **Step 5: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/api/router.py
git commit -m "feat: /api/routines CRUD + manual run + logs endpoints"
```

---

## Task 5: Wire scheduler into main.py startup

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: Update on_startup in main.py**

Replace the existing `on_startup` function:

```python
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

    # Start background services
    from app.services import email_poller, scheduler
    _poller_task = asyncio.create_task(email_poller.start())
    asyncio.create_task(scheduler.start_scheduler_loop())
```

- [ ] **Step 2: Restart and verify scheduler starts**

```bash
docker compose restart virtual-company
sleep 6
docker logs virtual-company --tail 20 | grep -E "Scheduler|ERROR"
```

Expected: `Subaru Scheduler started.` in the logs, no ERROR lines.

- [ ] **Step 3: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/main.py
git commit -m "feat: start scheduler loop on startup"
```

---

## Task 6: Standup compiler (TDD)

**Files:**
- Create: `app/services/standup.py`
- Create: `tests/test_standup.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_standup.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_generate_standup_prompt_contains_sections():
    """Standup prompt must include all three state sections."""
    from app.services.standup import generate_standup_prompt

    mock_state = MagicMock()
    mock_state.load_projects.return_value = [
        {"name": "TradingBot", "status": "active"}
    ]
    mock_state.work_queue = [
        {"agent": "backend", "task": "Fix auth bug", "status": "pending"}
    ]
    mock_state.task_history = [
        {"summary": "Deployed new UI", "status": "completed"}
    ]

    with patch("app.services.standup.state", mock_state):
        prompt = await generate_standup_prompt()

    assert "TradingBot" in prompt
    assert "Fix auth bug" in prompt
    assert "Deployed new UI" in prompt


@pytest.mark.asyncio
async def test_generate_standup_prompt_empty_state():
    """Prompt should still generate when no projects/queue/history."""
    from app.services.standup import generate_standup_prompt

    mock_state = MagicMock()
    mock_state.load_projects.return_value = []
    mock_state.work_queue = []
    mock_state.task_history = []

    with patch("app.services.standup.state", mock_state):
        prompt = await generate_standup_prompt()

    assert isinstance(prompt, str)
    assert len(prompt) > 50


@pytest.mark.asyncio
async def test_run_morning_standup_calls_agent():
    """run_morning_standup must invoke run_agent with the CEO."""
    from app.services.standup import run_morning_standup

    mock_state = MagicMock()
    mock_state.load_projects.return_value = []
    mock_state.work_queue = []
    mock_state.task_history = []

    with patch("app.services.standup.state", mock_state), \
         patch("app.services.standup.run_agent", new=AsyncMock(return_value="briefing text")) as mock_run:
        result = await run_morning_standup()
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0] == "ceo"   # first positional arg is agent_id
```

- [ ] **Step 2: Run — expect failure**

```bash
docker exec virtual-company python -m pytest /app/tests/test_standup.py -v 2>&1 | tail -5
```

Expected: `ImportError` — `app.services.standup` doesn't exist.

- [ ] **Step 3: Write app/services/standup.py**

```python
"""
Morning standup generator.

Compiles the current system state into a rich prompt, runs it through
the CEO agent, and broadcasts the result to all WS clients. The email
is sent by the CEO as part of its response (via [EMAIL_USER:...] tag).
"""
import logging
from datetime import datetime

from app.state import manager as state

logger = logging.getLogger(__name__)


async def generate_standup_prompt() -> str:
    """Build the CEO prompt for the morning briefing from live system state."""
    projects   = state.load_projects()
    queue      = [i for i in state.work_queue if i.get("status") != "completed"]
    history    = state.task_history[-5:]
    now_str    = datetime.now().strftime("%A, %d %B %Y")

    proj_lines  = "\n".join(
        f"  - {p.get('name', '?')}: {p.get('status', '?')}" for p in projects
    ) or "  (none active)"
    queue_lines = "\n".join(
        f"  - [{i['agent']}] {i['task']} ({i['status']})" for i in queue
    ) or "  (queue empty)"
    done_lines  = "\n".join(
        f"  - {h.get('summary', '')}" for h in reversed(history)
    ) or "  (no recent completions)"

    return f"""You are Subaru, the AI command center for Shadow Garden.
Today is {now_str}.

Compose a morning executive briefing for Saurav (your operator).
Open with one sentence of creative inspiration.
Then cover:

ACTIVE PROJECTS:
{proj_lines}

PENDING QUEUE:
{queue_lines}

RECENT COMPLETIONS:
{done_lines}

Close with today's top priority and one energizing line.
Keep it 200-300 words total. Write in first person as Subaru.

After the briefing, send it via email:
[EMAIL_USER:Subaru Morning Briefing — {now_str}]
<the briefing text here>
"""


async def run_morning_standup(broadcast_fn=None) -> str:
    """Generate the standup, run CEO agent, and broadcast to WS clients."""
    from app.agents.executor import run_agent
    from app.api.websocket import broadcast_event

    prompt      = await generate_standup_prompt()
    output_acc: list[str] = []

    async def _send(data: dict) -> None:
        if data.get("type") == "assistant":
            for blk in data.get("message", {}).get("content", []):
                if blk.get("type") == "text" and blk["text"]:
                    output_acc.append(blk["text"])
        _fn = broadcast_fn or broadcast_event
        try:
            await _fn(data)
        except Exception:
            pass

    await run_agent("ceo", prompt, _send, model="claude")
    text = "".join(output_acc)

    # Push a dedicated standup event so the UI can display it prominently
    await broadcast_event({
        "type":    "standup",
        "content": text,
        "date":    datetime.now().isoformat(),
    })

    logger.info("Morning standup completed (%d chars)", len(text))
    return text
```

- [ ] **Step 4: Run tests — expect pass**

```bash
docker exec virtual-company python -m pytest /app/tests/test_standup.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Run full suite**

```bash
docker exec virtual-company python -m pytest /app/tests/ -v 2>&1 | tail -5
```

Expected: 33 tests pass.

- [ ] **Step 6: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/services/standup.py tests/test_standup.py
git commit -m "feat: morning standup compiler — compiles state → CEO prompt → email"
```

---

## Task 7: Design preview service + Emilia tool

**Files:**
- Create: `app/services/browser.py`
- Modify: `app/agents/executor.py` (add write_preview case to `_execute_tool`)
- Modify: `app/agents/definitions.py` (update Emilia's persona)
- Modify: `app/api/router.py` (add `/api/design/preview` endpoint)

- [ ] **Step 1: Create app/services/browser.py**

```python
"""
Design preview writer.

Provides write_preview() — called by Emilia via the [WRITE_PREVIEW:] tool
tag. Writes agent-generated HTML to the live preview iframe target file.
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Inside the container: /app = project root
PREVIEW_FILE = Path("/app/app/static/previews/index.html")


def write_preview(html_content: str) -> str:
    """Write agent-generated HTML to the live design preview file."""
    try:
        PREVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
        PREVIEW_FILE.write_text(html_content, encoding="utf-8")
        logger.info("Design preview updated (%d chars)", len(html_content))
        return f"Preview written ({len(html_content)} chars). Visible at /static/previews/index.html"
    except Exception as exc:
        logger.error("write_preview failed: %s", exc)
        return f"[write_preview error: {exc}]"
```

- [ ] **Step 2: Add write_preview to _execute_tool in executor.py**

In `app/agents/executor.py`, find the `_execute_tool()` function. Add to the `icon_map` and `label_map` dicts:

```python
    icon_map = {
        "bash":          "⚙",
        "read":          "📖",
        "write":         "✍",
        "edit":          "✏",
        "read_inbox":    "📬",
        "write_preview": "🎨",    # ← add this
    }
    label_map = {
        "bash":          "Executing Bash",
        "read":          "Reading File",
        "write":         "Writing File",
        "edit":          "Editing File",
        "read_inbox":    "Reading Inbox",
        "write_preview": "Writing Design Preview",   # ← add this
    }
```

Then in the `try` block of `_execute_tool()`, add the `write_preview` case before the `else` branch. Find:

```python
        elif tool_type == "read_inbox":
            data   = await email_svc.read_emails(max_emails=5, unread_only=True)
            result = json.dumps(data, indent=2)
        else:
```

Replace with:

```python
        elif tool_type == "read_inbox":
            data   = await email_svc.read_emails(max_emails=5, unread_only=True)
            result = json.dumps(data, indent=2)
        elif tool_type == "write_preview":
            from app.services.browser import write_preview as _wp
            from app.api.websocket import broadcast_event
            html = tool_args.get("html_content", tool_args.get("content", ""))
            result = _wp(html)
            asyncio.create_task(broadcast_event({
                "type":    "design_preview_updated",
                "message": result,
            }))
        else:
```

- [ ] **Step 3: Update Emilia's persona in definitions.py**

Find the Emilia entry in `app/agents/definitions.py`:

```python
    "frontend": {
        ...
        "persona":     _worker_persona(
            "Emilia", "Senior Frontend Engineer",
            "React 18, Next.js 14, TypeScript, Tailwind CSS, Framer Motion",
            "Write clean typed components. Use Tailwind for all styling.",
        ),
    },
```

Replace the `_worker_persona` call with:

```python
    "frontend": {
        "name":        "Emilia",
        "title":       "Frontend Engineer",
        "color":       "#ff6b9d",
        "avatar":      "EM",
        "description": "React, Next.js, TypeScript, CSS, live design preview.",
        "persona":     _worker_persona(
            "Emilia", "Senior Frontend Engineer",
            "React 18, Next.js 14, TypeScript, Tailwind CSS, Framer Motion, vanilla HTML/CSS/JS",
            """Write clean typed components. Use Tailwind for all styling.

DESIGN PREVIEW TOOL:
When asked to design or build a UI component, generate a complete self-contained
HTML file (inline CSS + JS, no external imports except CDN fonts/icons) and
output it using the write_preview tool tag:

[WRITE_PREVIEW:]
```html
<!DOCTYPE html>
<html>
...full HTML...
</html>
```

This renders the component instantly in the user's live preview panel.
Always use this tool for any visual design or UI component request.""",
        ),
    },
```

- [ ] **Step 4: Add /api/design/preview endpoint to router.py**

Add after the routines endpoints in `app/api/router.py`:

```python
# ── Design Preview ─────────────────────────────────────────────────────────────

@router.post("/api/design/preview")
async def api_design_preview(request: Request, body: dict):
    """Write HTML directly to the design preview (e.g. from frontend form)."""
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        return JSONResponse({"ok": False, "error": "Restricted to localhost"}, status_code=403)
    html = body.get("html", "")
    if not html.strip():
        return JSONResponse({"ok": False, "error": "html field is required"}, status_code=400)
    from app.services.browser import write_preview
    from app.api.websocket import broadcast_event
    result = write_preview(html)
    asyncio.create_task(broadcast_event({"type": "design_preview_updated", "message": result}))
    return {"ok": True, "message": result}
```

- [ ] **Step 5: Add WRITE_PREVIEW parser to tools.py**

In `app/agents/tools.py`, find the `parse_tool_call` function. Add this block after the existing `[WRITE:]` parser (before `return None, None`):

```python
    m = re.search(r'\[WRITE_PREVIEW:\s*\]', text, re.DOTALL)
    if m:
        # HTML follows in a code block after the tag
        code_m = re.search(r'```(?:html)?\n(.*?)```', text[m.end():], re.DOTALL)
        content = code_m.group(1) if code_m else text[m.end():].strip()
        return "write_preview", {"html_content": content}
```

- [ ] **Step 6: Verify Emilia can use write_preview**

```bash
docker exec virtual-company curl -s http://localhost:3030/api/capabilities > /dev/null && echo OK
```

Expected: `OK` — app reloaded without errors.

- [ ] **Step 7: Test write_preview directly**

```bash
docker exec virtual-company curl -s -X POST http://localhost:3030/api/design/preview \
  -H "Content-Type: application/json" \
  -d '{"html": "<html><body style=\"background:#0f0;color:#fff\">Design Preview Test</body></html>"}' 
```

Expected: `{"ok": true, "message": "Preview written (...)"}`.

Then verify the file was written:
```bash
docker exec virtual-company ls -la /app/app/static/previews/
```

Expected: `index.html` exists.

- [ ] **Step 8: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/services/browser.py app/agents/executor.py app/agents/definitions.py app/api/router.py app/agents/tools.py
git commit -m "feat: design preview service + write_preview tool for Emilia"
```

---

## Task 8: Frontend — Routines panel

**Files:**
- Modify: `app/static/index.html` (add routines panel HTML)
- Modify: `app/static/style-v5.css` (routine card styles)
- Modify: `app/static/app-v5.js` (routines fetch, render, WS handler)

- [ ] **Step 1: Add routines panel HTML to index.html**

After the skills panel closing `</div>` in `app/static/index.html`, add:

```html
<!-- ── Routines Panel ───────────────────────────────────────────────── -->
<div class="routines-panel" id="routines-panel" style="display:none">
  <div class="routines-panel-header">
    <span>ROUTINES</span>
    <div style="display:flex;gap:8px;align-items:center">
      <button class="skill-chip install" onclick="showCreateRoutine()" style="font-size:11px">➕ New</button>
      <button onclick="toggleRoutinesPanel()">✕</button>
    </div>
  </div>
  <div id="routines-list"></div>
</div>
```

Also update the command palette button in the header (find `"Show Routines"` in the HTML's inline script — there isn't one, this is handled in JS) and add a routines pill to the header `hdr-pills` div:

```html
    <button class="pill pill-skills" id="routines-pill" title="Routines panel" onclick="toggleRoutinesPanel()" style="display:none">
      <span id="routines-active-count">0</span> Routines
    </button>
```

Add this pill right after the `queue-pill` div.

- [ ] **Step 2: Add routine card styles to style-v5.css**

Append to `app/static/style-v5.css`:

```css
/* ── Routines Panel ──────────────────────────────────────────────────── */
.routines-panel {
  position: fixed; top: 52px; right: 0; bottom: 0; width: 340px;
  background: var(--bg-card); border-left: 1px solid var(--border);
  padding: 16px; overflow-y: auto; z-index: 80;
  animation: slide-in-right .2s ease;
}
.routines-panel-header {
  display: flex; justify-content: space-between; align-items: center;
  font-family: var(--font-brand); font-size: 12px; letter-spacing: .1em;
  color: var(--gold); margin-bottom: 16px;
}
.routines-panel-header button { background: none; border: none; color: var(--muted); cursor: pointer; font-size: 14px; }
.routine-card {
  background: var(--bg-elevated); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 12px; margin-bottom: 10px;
}
.routine-card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.routine-name { font-weight: 600; font-size: 13px; color: var(--text); }
.routine-meta { font-size: 11px; color: var(--muted); margin-bottom: 8px; }
.routine-actions { display: flex; gap: 6px; align-items: center; }
.routine-status {
  display: inline-block; padding: 2px 8px; border-radius: 10px;
  font-size: 10px; font-weight: 600;
}
.routine-status.success { background: hsla(140,70%,50%,.15); color: var(--green); }
.routine-status.error   { background: hsla(0,80%,60%,.15);   color: var(--red); }
.routine-status.pending { background: hsla(38,100%,55%,.15);  color: var(--warn); }
.routine-toggle {
  position: relative; width: 36px; height: 20px;
  background: var(--border); border: none; border-radius: 10px; cursor: pointer;
  transition: background .2s;
}
.routine-toggle.on { background: var(--green); }
.routine-toggle::after {
  content: ''; position: absolute; width: 14px; height: 14px;
  background: white; border-radius: 50%; top: 3px; left: 3px;
  transition: transform .2s;
}
.routine-toggle.on::after { transform: translateX(16px); }
.btn-run {
  background: hsla(185,100%,50%,.1); border: 1px solid hsla(185,100%,50%,.3);
  color: var(--cyan); border-radius: 6px; padding: 3px 10px;
  font-size: 11px; cursor: pointer;
}
.btn-run:hover { background: hsla(185,100%,50%,.2); }
```

- [ ] **Step 3: Add routines JS logic to app-v5.js**

Append these functions to `app/static/app-v5.js` before the final `document.addEventListener("DOMContentLoaded", ...)` block:

```javascript
// ── Routines Panel ──────────────────────────────────────────────────────────
let _routines = [];

async function loadRoutines() {
  try {
    _routines = await fetch("/api/routines").then(r => r.json());
    renderRoutines();
    const pill = $id("routines-pill");
    if (pill) {
      pill.style.display = "inline-flex";
      const enabled = _routines.filter(r => r.enabled).length;
      $id("routines-active-count").textContent = enabled;
    }
  } catch(e) { console.error("loadRoutines:", e); }
}

function renderRoutines() {
  const list = $id("routines-list");
  if (!list) return;
  list.innerHTML = "";
  if (_routines.length === 0) {
    list.innerHTML = '<div style="color:var(--muted);font-size:12px;text-align:center;padding:20px">No routines yet. Click ➕ New to create one.</div>';
    return;
  }
  _routines.forEach(r => {
    const statusLabel = r.last_status || "never run";
    const statusClass = r.last_status === "success" ? "success" : r.last_status === "error" ? "error" : "pending";
    const lastRun     = r.last_run ? new Date(r.last_run).toLocaleString("en-IN", {timeZone:"Asia/Kolkata", hour12:false}).slice(0,16) : "—";
    const card        = document.createElement("div");
    card.className    = "routine-card";
    card.innerHTML    = `
      <div class="routine-card-header">
        <span class="routine-name">${escHtml(r.name)}</span>
        <span class="routine-status ${statusClass}">${statusLabel}</span>
      </div>
      <div class="routine-meta">
        ${escHtml(r.agent)} · ${escHtml(r.schedule)} · ${escHtml(r.timezone || "IST")} · Last: ${lastRun}
      </div>
      <div class="routine-actions">
        <button class="routine-toggle ${r.enabled ? 'on' : ''}" onclick="toggleRoutine('${r.id}', this)" title="${r.enabled ? 'Enabled' : 'Disabled'}"></button>
        <button class="btn-run" onclick="runRoutineNow('${r.id}')">▶ Run</button>
        <span style="flex:1"></span>
        <button class="cmdbar-btn" onclick="deleteRoutine('${r.id}')" style="font-size:12px" title="Delete">🗑</button>
      </div>`;
    list.appendChild(card);
  });
}

function toggleRoutinesPanel() {
  const p = $id("routines-panel");
  const skills = $id("skills-panel");
  if (skills) skills.style.display = "none";
  const showing = p.style.display !== "none";
  p.style.display = showing ? "none" : "block";
  if (!showing) loadRoutines();
}

async function toggleRoutine(id, btn) {
  const routine = _routines.find(r => r.id === id);
  if (!routine) return;
  const newEnabled = !routine.enabled;
  await fetch(`/api/routines/${id}`, {
    method: "PUT",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ enabled: newEnabled }),
  });
  routine.enabled = newEnabled;
  renderRoutines();
}

async function runRoutineNow(id) {
  pushNotif(`Running routine '${id}'...`);
  const r = await fetch(`/api/routines/${id}/run`, {method:"POST"}).then(r=>r.json());
  if (!r.ok) pushNotif(`Failed: ${r.error}`, "error");
}

async function deleteRoutine(id) {
  if (!confirm(`Delete routine '${id}'?`)) return;
  await fetch(`/api/routines/${id}`, {method:"DELETE"});
  await loadRoutines();
}

function showCreateRoutine() {
  const id       = prompt("Routine ID (letters/numbers/underscore):");
  if (!id) return;
  const name     = prompt("Display name:");
  if (!name) return;
  const schedule = prompt("Cron schedule (e.g. '0 9 * * *' for 9 AM daily):", "0 9 * * *");
  if (!schedule) return;
  const prompt_  = prompt("Agent prompt:");
  if (!prompt_) return;
  const agent    = prompt("Agent (ceo/backend/frontend/qa):", "ceo");

  fetch("/api/routines", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ id, name, schedule, prompt: prompt_, agent }),
  }).then(r => r.json()).then(d => {
    if (d.ok) { loadRoutines(); pushNotif(`Routine '${name}' created`, "success"); }
    else pushNotif(`Error: ${d.error}`, "error");
  });
}
```

- [ ] **Step 4: Handle routine_completed WS event in dispatch()**

In the `dispatch()` function in `app-v5.js`, add a case inside the `switch(type)` block:

```javascript
    case "routine_completed":
      pushNotif(
        `Routine '${obj.routine_id}' ${obj.status === "success" ? "✓" : "✗"}: ${(obj.output||"").slice(0,60)}…`,
        obj.status === "success" ? "success" : "error"
      );
      // Refresh routines panel if open
      if ($id("routines-panel").style.display !== "none") loadRoutines();
      break;

    case "standup":
      appendMsg("ceo", "assistant", `📋 **Morning Briefing**\n\n${obj.content || ""}`);
      pushNotif("Morning standup delivered", "success");
      break;
```

- [ ] **Step 5: Add Routines command to palette**

In `app-v5.js`, find the `PALETTE_CMDS` array and add:

```javascript
  { icon:"🔄", label:"Show Routines",        action: toggleRoutinesPanel },
  { icon:"▶",  label:"Run Morning Standup",  action: () => fetch("/api/routines/morning_standup/run", {method:"POST"}).then(()=>pushNotif("Standup triggered")) },
```

Add these before the existing `{ icon:"🧠", label:"Show Skills Panel"...}` entry.

- [ ] **Step 6: Verify routines panel opens**

Open `http://localhost:3030` in a browser. Click the `N Routines` pill in the header (or press ⌘K → "Show Routines"). Verify:
- Routines panel slides in from the right
- Two routines shown: Morning Briefing (enabled) + Nightly Review (disabled)
- Toggle button shows green for enabled routines

- [ ] **Step 7: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/static/index.html app/static/style-v5.css app/static/app-v5.js
git commit -m "feat: routines panel UI — toggle, run, create, delete, WS live updates"
```

---

## Task 9: Frontend — Design preview panel refresh

**Files:**
- Modify: `app/static/app-v5.js`

The design floating island already exists in the HTML. This task wires up the `design_preview_updated` WS event to reload the iframe.

- [ ] **Step 1: Add design_preview_updated handler to dispatch()**

In the `switch(type)` block in `app-v5.js`, add:

```javascript
    case "design_preview_updated":
      // Refresh the design preview iframe if it's loaded
      const iframe = $id("design-iframe");
      if (iframe && iframe.src) {
        iframe.src = iframe.src;   // force reload
      }
      pushNotif("Design preview updated", "success");
      break;
```

- [ ] **Step 2: Add design commands to palette**

In the `PALETTE_CMDS` array in `app-v5.js`, the existing `"Open Design Preview"` entry calls `showIsland("design")`. Update it to also load the preview:

Find:
```javascript
  { icon:"🎨", label:"Open Design Preview", action: () => showIsland("design") },
```

Replace with:
```javascript
  { icon:"🎨", label:"Open Design Preview", action: () => { showIsland("design"); } },
  { icon:"✏",  label:"Ask Emilia to Design", action: () => {
    const what = prompt("What should Emilia design?");
    if (what) { switchAgent("frontend"); sendMsgText(`Design: ${what}`); showIsland("design"); }
  }},
```

- [ ] **Step 3: Verify design preview flow**

```bash
# Write a test design via the API (localhost-only)
docker exec virtual-company curl -s -X POST http://localhost:3030/api/design/preview \
  -H "Content-Type: application/json" \
  -d '{"html":"<html><body style=\"background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;font-family:Orbitron\"><h1 style=\"color:#00f5ff\">SUBARU</h1></body></html>"}'
```

Open `http://localhost:3030`, press ⌘K → "Open Design Preview". The floating island should show the gradient page. Then ask Emilia in chat to design a dark card component — the iframe should update automatically via the WS event.

- [ ] **Step 4: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/static/app-v5.js
git commit -m "feat: design preview panel auto-refresh on WS design_preview_updated event"
```

---

## Task 10: End-to-end smoke test

- [ ] **Step 1: Full test suite**

```bash
docker exec virtual-company python -m pytest /app/tests/ -v
```

Expected: **36 tests PASS** (23 foundation + 7 scheduler + 3 standup + 3 executor_gemini).

- [ ] **Step 2: Routines API smoke test**

```bash
# List
docker exec virtual-company curl -s http://localhost:3030/api/routines | python3 -c "import sys,json;d=json.load(sys.stdin);print(len(d),'routines')"

# Manually trigger standup
docker exec virtual-company curl -s -X POST http://localhost:3030/api/routines/morning_standup/run | python3 -m json.tool

# Check logs after ~5s
sleep 5
docker exec virtual-company curl -s "http://localhost:3030/api/routines/morning_standup/logs?limit=3" | python3 -m json.tool
```

Expected:
- `2 routines`
- `{"ok": true, "message": "..."}`
- Log entry with `"status": "success"` or `"status": "error"` (depends on Claude availability)

- [ ] **Step 3: Design preview smoke test**

```bash
docker exec virtual-company curl -s -X POST http://localhost:3030/api/design/preview \
  -H "Content-Type: application/json" \
  -d '{"html":"<html><body style=\"background:#111;color:#0ff;padding:20px\"><h2>Smoke Test Preview</h2></body></html>"}' | python3 -m json.tool

docker exec virtual-company cat /app/app/static/previews/index.html | head -3
```

Expected: `{"ok": true, ...}` and HTML content visible.

- [ ] **Step 4: Verify docker logs are clean**

```bash
docker logs virtual-company --tail 30 | grep -E "ERROR|Traceback" || echo "No errors"
```

Expected: `No errors`

- [ ] **Step 5: Final commit**

```bash
cd /home/subaru/projects/virtual-company
git add -A
git status
git commit -m "feat: Phase 2 complete — Routines Engine, Claude Design Panel, Morning Standup"
```

---

## Self-Review

**Spec coverage check:**

| Spec Requirement | Task |
|---|---|
| Routines Engine — cron scheduler | Task 3 (scheduler.py) |
| Scheduler race condition fix | Task 3 (`_maybe_fire` with `get_next` + dedup key) |
| Routines JSON persistence | Task 1 (nexus_routines.json seed) + Task 3 (load/save) |
| CRUD + manual trigger API | Task 4 |
| Routine output stored + retrievable | Task 3 (run_log) + Task 4 (/logs endpoint) |
| Routine_completed WS broadcast | Task 2 (broadcast_event) + Task 3 (run_routine) |
| Scheduler started on app boot | Task 5 |
| Morning standup (email + WS) | Task 6 (standup.py) + default routine in nexus_routines.json |
| Claude Design Panel — write_preview | Task 7 (browser.py + tool) |
| Emilia uses write_preview | Task 7 (definitions.py persona update + tools.py parser) |
| design_preview_updated WS event | Task 7 (executor _execute_tool) + Task 9 (JS handler) |
| Routines panel in UI | Task 8 |
| Design preview auto-refresh | Task 9 |
| Command palette entries for routines | Task 8 |

**No placeholders found. All code blocks are complete.**

**Type consistency:**
- `run_routine(routine: dict)` defined in Task 3, called from Task 4 router — consistent.
- `broadcast_event(data: dict)` defined in Task 2, called in Tasks 3, 7, 6 — consistent.
- `load_routines()` / `save_routines()` defined in Task 3, used in Task 4 — consistent.
- `write_preview(html_content: str)` defined in Task 7, called from `_execute_tool` with key `"html_content"` — consistent.
