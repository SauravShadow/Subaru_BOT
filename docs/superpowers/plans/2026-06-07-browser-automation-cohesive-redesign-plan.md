# Browser Automation Cohesive Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Maya's `BROWSER_*` tags actually reach `browser-svc` through the universal output pipeline (the same path `SPEAK`/`EMAIL_USER` already use), give the live dashboard an accurate 4-slot view, add an automation↔manual handoff with a learning loop, and establish a clean, reusable pattern for wiring up future browser-driven workers.

**Architecture:** `BROWSER_APPLY`/`BROWSER_DISCOVER`/`BROWSER_COMPANY`/`BROWSER_PROFILE_MATCH` become first-class output-pipeline handlers (mirroring `app/output/handlers/speak.py`/`image.py`), registered in `app/output/registry.py` and dispatched fire-and-forget via `asyncio.create_task(call_browser_svc(...))`. Slot assignment moves server-side: clients omit `slot_id` and `browser-svc` resolves a free slot via the existing-but-unused `find_free_slot()`, returning `409 "No free slot available"` when the pool is full. Results flow back to Maya over the existing `/ws/browser-relay` WebSocket channel as a new `browser_result` message type, handled by `handle_browser_result()` in `app/api/websocket.py` — mirroring `_run_worker_bg`'s `state.record` → `run_agent` → `state.record` sequence so Maya finally gets real `[Tool Output]` feedback instead of narrating fabricated summaries. The work starts with an architectural cleanup phase (slot pool 5→4, consistent `0 ≤ slot_id < 4` validation, FTS5 escaping fix, relay logger fix) because every later phase depends on the renumbered, consistently-validated slot pool.

**Tech Stack:** Python (FastAPI, Playwright, pytest, pytest-asyncio, unittest.mock), vanilla JS (`app-v5.js`), SQLite FTS5, WebSockets (`websockets` client / FastAPI `WebSocket` server)

---

## File Structure

**NEXUS side (`app/`)**
- `app/output/handlers/browser_apply.py`, `browser_discover.py`, `browser_company.py`, `browser_profile_match.py` *(new)* — output-pipeline handlers for the four `BROWSER_*` tags, one file per tag, following the `speak.py`/`image.py` pattern (`TAG`, `PATTERN`, `async def handle(args, agent_id, send) -> tuple[str, bool]`)
- `app/output/registry.py` *(modify)* — register the four new handlers in `get_registry()`
- `app/agents/tools.py` *(modify)* — extract `parse_browser_discover_args(raw: str) -> dict` so both `parse_tool_call` and the new `browser_discover` handler share the platform-splitting logic
- `app/services/browser_svc.py` *(modify)* — `_PAYLOAD_MAP` lambdas stop hardcoding `"slot_id": 1` so the server can auto-pick a slot
- `app/api/websocket.py` *(modify)* — add `handle_browser_result(data)`, the feedback-loop counterpart to `_run_worker_bg`
- `app/main.py` *(modify)* — branch on `browser_result` inside `browser_relay_endpoint`
- `app/services/memory.py` *(modify)* — fix FTS5 query escaping in `get_relevant_memories`
- `app/agents/definitions.py` *(modify)* — update Maya's persona text from "5 browser instances (slots 0–4)" to "4 browser instances (slots 0–3)"
- `app/static/index.html` *(modify)* — `island-board` markup: drop the special-cased "Overleaf (CV)" slot-0 option, 4 slots total
- `app/static/app-v5.js` *(modify)* — `_SLOT_LABELS`, `selectBoardSlot`, `getSelectedBoardSlot`, `initBrowserBoard` updated for a 4-tile grid

**browser-svc side (`browser-svc/`)**
- `browser-svc/session_manager.py` *(modify)* — `NUM_SLOTS` 5 → 4
- `browser-svc/main.py` *(modify)* — `/health` slot count, unified `0 ≤ slot_id < NUM_SLOTS` validation, new `_resolve_slot()` helper wiring `find_free_slot()` into all four apply-style endpoints
- `browser-svc/relay_client.py` *(modify)* — fix logger visibility (`logging.basicConfig`) and push `browser_result` messages back to NEXUS
- `browser-svc/job_workflow.py` *(modify)* — new `detect_blocker(page) -> Optional[dict]` proactive check, used by the handoff/escalation flow

**Tests** (mirror each modified/created module 1:1, following each directory's existing fixture conventions)
- `tests/test_handlers.py`, `tests/test_pipeline.py` — new handler dispatch tests
- `browser-svc/tests/test_session_manager.py`, `browser-svc/tests/test_main.py` — updated slot-count/validation/`find_free_slot` tests
- `browser-svc/tests/test_relay_client.py` — logger + `browser_result` push tests
- `browser-svc/tests/test_job_workflow.py` — `detect_blocker` tests
- `tests/test_memory.py`, `tests/test_websocket.py` — FTS5 escaping and `handle_browser_result` tests

---

## Phase 1 — Architectural Cleanup (spec Section 4)

This phase comes first deliberately: it renumbers the slot pool to 0–3 and makes slot-id validation consistent everywhere, which Phase 2 (dashboard redesign) and Phase 3 (tag dispatch) both build directly on top of. It also fixes two standing bugs (FTS5 escaping, relay logger silence) that Phase 4 (handoff/learning loop) needs working.

### Task 1: Reduce the browser session pool from 5 slots to 4

**Files:**
- Modify: `browser-svc/session_manager.py:27`
- Test: `browser-svc/tests/test_session_manager.py:21,58,64-66`

- [ ] **Step 1: Update the slot-count assertions to expect 4 slots**

In `browser-svc/tests/test_session_manager.py`, change `test_initial_state_all_idle`:

```python
@pytest.mark.asyncio
async def test_initial_state_all_idle(sm):
    assert len(sm._slots) == 4
    assert all(s.state == SlotState.IDLE for s in sm._slots)
```

Change `test_find_free_slot_returns_none_when_all_busy`:

```python
@pytest.mark.asyncio
async def test_find_free_slot_returns_none_when_all_busy(sm):
    for i in range(4):
        await sm.acquire(i)
    assert sm.find_free_slot() is None
```

Rename `test_status_returns_five_dicts` to `test_status_returns_four_dicts` and update its body:

```python
@pytest.mark.asyncio
async def test_status_returns_four_dicts(sm):
    statuses = sm.status()
    assert len(statuses) == 4
    for s in statuses:
        assert "slot_id" in s and "state" in s and "url" in s and "action" in s
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd browser-svc && python -m pytest tests/test_session_manager.py -v`

Expected: `test_initial_state_all_idle`, `test_find_free_slot_returns_none_when_all_busy`, and `test_status_returns_four_dicts` FAIL — `SessionManager()` still creates 5 slots because `NUM_SLOTS = 5`.

- [ ] **Step 3: Change the slot count**

In `browser-svc/session_manager.py:27`, change:

```python
    NUM_SLOTS = 4
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd browser-svc && python -m pytest tests/test_session_manager.py -v`

Expected: PASS — every test in the file is green.

- [ ] **Step 5: Commit**

```bash
git add browser-svc/session_manager.py browser-svc/tests/test_session_manager.py
git commit -m "fix: reduce browser session pool from 5 slots to 4"
```

### Task 2: Update `/health` and `/slots` to report 4 slots

**Files:**
- Modify: `browser-svc/main.py:32`
- Test: `browser-svc/tests/test_main.py:51-62`

- [ ] **Step 1: Update the health/slots assertions**

In `browser-svc/tests/test_main.py`, change:

```python
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "slots": 4}


def test_get_slots(client):
    r = client.get("/slots")
    assert r.status_code == 200
    slots = r.json()
    assert len(slots) == 4
    assert all(s["state"] == "idle" for s in slots)
```

- [ ] **Step 2: Run the tests and confirm `test_health` fails**

Run: `cd browser-svc && python -m pytest tests/test_main.py::test_health tests/test_main.py::test_get_slots -v`

Expected: `test_health` FAILS — the handler still returns `{"status": "ok", "slots": 5}`. `test_get_slots` PASSES already (it reads `len(slots)` from `session_manager.status()`, which Task 1 already made return 4 entries).

- [ ] **Step 3: Update the health response**

In `browser-svc/main.py:32`, change:

```python
    return {"status": "ok", "slots": 4}
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd browser-svc && python -m pytest tests/test_main.py::test_health tests/test_main.py::test_get_slots -v`

Expected: PASS — both tests green.

- [ ] **Step 5: Commit**

```bash
git add browser-svc/main.py browser-svc/tests/test_main.py
git commit -m "fix: report 4 slots from /health endpoint"
```

### Task 3: Unify slot-id validation and auto-pick free slots on all four apply-style endpoints

This single task covers spec items (a) and (b) together because they land on the exact same lines: today `/apply` validates `1 ≤ slot_id ≤ 4` while the interactive endpoints validate `0 ≤ slot_id < NUM_SLOTS`, and `ApplyRequest`/`DiscoverRequest`/`CompanyRequest`/`ProfileMatchRequest` all hardcode `slot_id: int = 1` (so two concurrent calls collide on slot 1 with `409 Slot 1 is busy`). Fixing the range and wiring up the existing-but-unused `find_free_slot()` are the same change to the same request-handling code, so splitting them into separate tasks would mean rewriting these endpoints twice.

**Files:**
- Modify: `browser-svc/main.py:74-75` (add `_resolve_slot` helper), `:111-124` (`ApplyRequest`/`apply_endpoint`), `:127-138` (`DiscoverRequest`/`discover_endpoint`), `:169-178` (`CompanyRequest`/`company_apply_endpoint`), `:207-242` (`ProfileMatchRequest`/`profile_match_endpoint`)
- Test: `browser-svc/tests/test_main.py:92-99` (replace), plus new tests added after `test_apply_queues_job`

- [ ] **Step 1: Replace the stale invalid-slot tests and add tests for the new behavior**

In `browser-svc/tests/test_main.py`, replace `test_apply_invalid_slot_zero` and `test_apply_invalid_slot_five` (lines 92-99) — slot 0 becomes *valid* under the new 0–3 range, so "slot 0 is invalid" is no longer a meaningful test:

```python
def test_apply_invalid_slot_negative(client):
    r = client.post("/apply", json={"url": "https://linkedin.com/jobs/123", "slot_id": -1})
    assert r.status_code == 400


def test_apply_invalid_slot_four(client):
    r = client.post("/apply", json={"url": "https://linkedin.com/jobs/123", "slot_id": 4})
    assert r.status_code == 400
```

Then add these two tests directly after `test_apply_queues_job`:

```python
def test_apply_without_slot_id_picks_free_slot(client):
    r = client.post("/apply", json={"url": "https://linkedin.com/jobs/123"})
    assert r.status_code == 200
    data = r.json()
    assert data["queued"] is True
    assert data["slot_id"] == 0


def test_apply_returns_409_when_no_free_slot(client):
    import main as m
    with patch.object(m.session_manager, "find_free_slot", return_value=None):
        r = client.post("/apply", json={"url": "https://linkedin.com/jobs/123"})
    assert r.status_code == 409
    assert r.json()["detail"] == "No free slot available"
```

- [ ] **Step 2: Run the tests and confirm the new-behavior ones fail**

Run: `cd browser-svc && python -m pytest tests/test_main.py -k apply -v`

Expected:
- `test_apply_invalid_slot_four` FAILS — the current check is `slot_id > 4`, so `slot_id=4` is accepted (200) instead of rejected (400)
- `test_apply_without_slot_id_picks_free_slot` FAILS — omitting `slot_id` falls back to the Pydantic default `1`, not an auto-picked `0`
- `test_apply_returns_409_when_no_free_slot` FAILS — `find_free_slot` is never called today, so patching it has no effect and the request queues with `slot_id=1`
- `test_apply_invalid_slot_negative` and `test_apply_queues_job` already PASS (they don't exercise new behavior — `-1` was rejected by the old range check too, and explicit `slot_id=1` was always valid)

- [ ] **Step 3: Add `_resolve_slot` and rewrite the four endpoints to use it**

In `browser-svc/main.py`, add this helper directly after `_slot_is_busy` (after line 75):

```python
def _resolve_slot(slot_id: int | None) -> int:
    if slot_id is not None:
        if slot_id < 0 or slot_id >= session_manager.NUM_SLOTS:
            raise HTTPException(400, f"slot_id must be 0–{session_manager.NUM_SLOTS - 1}")
        if _slot_is_busy(slot_id):
            raise HTTPException(409, f"Slot {slot_id} is busy")
        return slot_id
    free = session_manager.find_free_slot()
    if free is None:
        raise HTTPException(409, "No free slot available")
    return free
```

Change all four request models' `slot_id: int = 1` to `slot_id: int | None = None` (`ApplyRequest:113`, `DiscoverRequest:131`, `CompanyRequest:171`, `ProfileMatchRequest:208`).

Replace `apply_endpoint` (lines 117-124):

```python
@app.post("/apply")
async def apply_endpoint(req: ApplyRequest, bg: BackgroundTasks):
    slot_id = _resolve_slot(req.slot_id)
    bg.add_task(_run_apply, req.url, slot_id, req.tailor_cv)
    return {"queued": True, "slot_id": slot_id, "url": req.url}
```

Replace `discover_endpoint` (lines 135-166):

```python
@app.post("/discover")
async def discover_endpoint(req: DiscoverRequest, bg: BackgroundTasks):
    slot_id = _resolve_slot(req.slot_id)

    async def run():
        from job_workflow import discover_jobs_linkedin, discover_jobs_indeed, discover_jobs_naukri
        slot = await session_manager.acquire(slot_id)
        screencast_started = False
        try:
            await session_manager.start_screencast(slot_id, relay)
            screencast_started = True
            if req.platform == "indeed":
                urls = await discover_jobs_indeed(slot.page, req.keywords, req.location)
            elif req.platform == "naukri":
                urls = await discover_jobs_naukri(slot.page, req.keywords, req.location)
            else:
                urls = await discover_jobs_linkedin(slot.page, req.keywords, req.location)
            for url in urls:
                await _apply_on_slot(slot, url, req.tailor_cv)
        except Exception:
            logger.exception("discover run() failed for keywords=%s", req.keywords)
        finally:
            if screencast_started:
                try:
                    await session_manager.stop_screencast(slot_id)
                except Exception:
                    pass
            await session_manager.release(slot_id)

    bg.add_task(run)
    return {"queued": True, "platform": req.platform, "keywords": req.keywords}
```

Replace `company_apply_endpoint` (lines 175-204):

```python
@app.post("/company-apply")
async def company_apply_endpoint(req: CompanyRequest, bg: BackgroundTasks):
    slot_id = _resolve_slot(req.slot_id)

    async def run():
        from job_workflow import discover_company_roles, load_profile
        slot = await session_manager.acquire(slot_id)
        screencast_started = False
        try:
            await session_manager.start_screencast(slot_id, relay)
            screencast_started = True
            profile = load_profile()
            urls = await discover_company_roles(
                slot.page, req.company, profile.get("target_roles", [])
            )
            for url in urls:
                await _apply_on_slot(slot, url, req.tailor_cv)
        except Exception:
            logger.exception("company_apply run() failed for company=%s", req.company)
        finally:
            if screencast_started:
                try:
                    await session_manager.stop_screencast(slot_id)
                except Exception:
                    pass
            await session_manager.release(slot_id)

    bg.add_task(run)
    return {"queued": True, "company": req.company}
```

Replace `profile_match_endpoint` (lines 212-242):

```python
@app.post("/profile-match")
async def profile_match_endpoint(req: ProfileMatchRequest, bg: BackgroundTasks):
    slot_id = _resolve_slot(req.slot_id)

    async def run():
        from job_workflow import discover_company_roles, load_profile
        profile = load_profile()
        companies = profile.get("target_companies", [])
        roles = profile.get("target_roles", [])
        slot = await session_manager.acquire(slot_id)
        screencast_started = False
        try:
            await session_manager.start_screencast(slot_id, relay)
            screencast_started = True
            for company in companies:
                urls = await discover_company_roles(slot.page, company, roles)
                for url in urls:
                    await _apply_on_slot(slot, url, req.tailor_cv)
        except Exception:
            logger.exception("profile_match run() failed")
        finally:
            if screencast_started:
                try:
                    await session_manager.stop_screencast(slot_id)
                except Exception:
                    pass
            await session_manager.release(slot_id)

    bg.add_task(run)
    return {"queued": True, "mode": "profile_match"}
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd browser-svc && python -m pytest tests/test_main.py -v`

Expected: PASS — every test in the file is green, including the rewritten and new ones.

- [ ] **Step 5: Commit**

```bash
git add browser-svc/main.py browser-svc/tests/test_main.py
git commit -m "fix: unify slot-id validation to 0-3 and auto-pick free slots via find_free_slot()"
```

### Task 4: Fix the FTS5 query-escaping bug in `get_relevant_memories`

**Files:**
- Modify: `app/services/memory.py:76`
- Test: `tests/test_memory.py` (uses the existing `mem` fixture defined at the top of the file)

- [ ] **Step 1: Write a failing test for a punctuated, multi-word query**

Add this test to `tests/test_memory.py`, following the same style as `test_save_and_retrieve_memory`:

```python
def test_get_relevant_memories_handles_punctuated_query(mem):
    mem.save_memory("maya", "Applied to Stripe's backend role")
    results = mem.get_relevant_memories("maya", "Stripe's backend role?")
    assert any("Stripe" in r for r in results)
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `cd /mnt/HC_Volume_105874680/virtual-company && python -m pytest tests/test_memory.py::test_get_relevant_memories_handles_punctuated_query -v`

Expected: FAIL — `"Stripe's backend role?"` is passed straight into `MATCH ?`, SQLite's FTS5 parser throws `sqlite3.OperationalError: fts5: syntax error near "'"`, the `except sqlite3.OperationalError` block in `get_relevant_memories` logs a warning and returns `[]`, and `any(...)` over an empty list is `False`.

- [ ] **Step 3: Quote the query before binding it to `MATCH`**

In `app/services/memory.py:76`, change:

```python
            """, (query, agent_id, limit)).fetchall()
```

to:

```python
            """, ('"' + query.replace('"', '""') + '"', agent_id, limit)).fetchall()
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `cd /mnt/HC_Volume_105874680/virtual-company && python -m pytest tests/test_memory.py::test_get_relevant_memories_handles_punctuated_query -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/memory.py tests/test_memory.py
git commit -m "fix: escape FTS5 MATCH queries so punctuated free-text doesn't throw"
```

### Task 5: Fix `relay_client.py` so its log messages actually appear in `docker logs`

**Files:**
- Modify: `browser-svc/relay_client.py:1-8`
- Test: `browser-svc/tests/test_relay_client.py`

- [ ] **Step 1: Write a failing test asserting the module configures root logging on import**

```python
def test_relay_client_configures_logging_handler():
    import logging
    import importlib
    import relay_client
    importlib.reload(relay_client)

    assert logging.getLogger().handlers, (
        "relay_client must call logging.basicConfig so its logger.info/warning "
        "calls are emitted to docker logs"
    )
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `cd browser-svc && python -m pytest tests/test_relay_client.py::test_relay_client_configures_logging_handler -v`

Expected: FAIL — `relay_client.py` only does `logger = logging.getLogger(__name__)` (line 8), never calls `logging.basicConfig`, so the root logger has no handlers and `logger.info`/`logger.warning` calls are silently dropped.

- [ ] **Step 3: Add `logging.basicConfig` matching `app/main.py`'s format**

In `browser-svc/relay_client.py`, change lines 1-8 from:

```python
import asyncio
import json
import logging
import os

import websockets

logger = logging.getLogger(__name__)
```

to:

```python
import asyncio
import json
import logging
import os

import websockets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `cd browser-svc && python -m pytest tests/test_relay_client.py::test_relay_client_configures_logging_handler -v`

Expected: PASS — `logging.getLogger().handlers` is non-empty.

- [ ] **Step 5: Commit**

```bash
git add browser-svc/relay_client.py browser-svc/tests/test_relay_client.py
git commit -m "fix: configure logging in relay_client so connection status is visible in docker logs"
```

### Task 6: Update Maya's persona text to describe 4 slots instead of 5

**Files:**
- Modify: `app/agents/definitions.py:314`
- Test: none — this is an LLM-facing string literal, not unit-testable; verified by grep below and later by manual checks in Phase 3

- [ ] **Step 1: Update the persona string**

In `app/agents/definitions.py:314`, change:

```python
            """You control up to 5 browser instances (slots 0–4) for job applications.
```

to:

```python
            """You control up to 4 browser instances (slots 0–3) for job applications.
```

- [ ] **Step 2: Grep for any other stale slot-count references in Maya's persona**

Run: `cd /mnt/HC_Volume_105874680/virtual-company && grep -n "5 browser\|slots 0–4\|slot 1\b" app/agents/definitions.py`

Expected: no matches inside Maya's persona body (lines 310-356) other than the line just changed. If any other line references "5" slots, "slots 0–4", or singles out "slot 1" as a default, update it the same way so the persona stays internally consistent.

- [ ] **Step 3: Commit**

```bash
git add app/agents/definitions.py
git commit -m "docs: update Maya's persona to describe 4 browser slots (0-3)"
```

### Task 7: Run the full cleanup test suite together as a final checkpoint

**Files:** none — verification-only step, no commit

- [ ] **Step 1: Run every test touched by this phase in one pass**

Run:
```bash
cd /mnt/HC_Volume_105874680/virtual-company && python -m pytest tests/test_memory.py -v
cd /mnt/HC_Volume_105874680/virtual-company/browser-svc && python -m pytest tests/test_session_manager.py tests/test_main.py tests/test_relay_client.py -v
```

Expected: PASS — every test green. This confirms the slot pool is consistently 4 slots end-to-end, validation is `0 ≤ slot_id < 4` everywhere, `find_free_slot()` is wired up and collision-free, FTS5 queries are escaped, and `relay_client` logs are visible — the foundation Phase 2 (dashboard) and Phase 3 (tag dispatch) build directly on top of.

---

## Phase 2 — Universal Tag Dispatch (spec Section 1)

**This is the foundational fix.** Today `BROWSER_*` tags only get executed inside the rarely-used `run_tgpt_agent` fallback loop; on the `run_claude_agent`/`run_gemini_agent` paths Maya runs on ~99% of the time, the tags pass straight through `pipeline.process()` as inert text because `app/output/registry.py` doesn't recognize them. This phase registers all four tags as output-pipeline handlers — exactly like `SPEAK`/`EMAIL_USER`/`GENERATE_IMAGE` — so they fire identically no matter which backend produced the text, and adds the async result-feedback loop that finally gives Maya ground truth about what actually happened.

**Design decision on the status line and "(slot N)":** The spec's example status line ("🔎 Searching LinkedIn for Python backend roles in Bangalore (slot 2)...") shows a slot number, but `call_browser_svc()` is dispatched fire-and-forget via `asyncio.create_task` (per the spec — browser actions take 30s to several minutes and must not block the chat turn), so the handler genuinely cannot know which slot `browser-svc` will resolve via `find_free_slot()` at the moment it builds the status line. Guessing would risk showing the wrong slot. So: the **immediate** status line omits the slot number (e.g. "🔎 Searching LinkedIn for Python backend roles in Bangalore..."), and the **authoritative** slot number appears later in the `browser_result` feedback message (Task 8/9), which reports what `browser-svc` actually did — a more accurate place for it anyway, since that's ground truth rather than a guess.

### Task 1: Extract `parse_browser_discover_args` so the new handler can reuse the existing parsing logic

The spec requires each handler to reuse `parse_tool_call`'s parsing rather than duplicating regexes. `BROWSER_APPLY`/`BROWSER_COMPANY`/`BROWSER_PROFILE_MATCH` parsing is a one-line `.strip()` — trivial enough to inline in their handlers. `BROWSER_DISCOVER`'s platform/location-splitting logic (`tools.py:277-291`) is the one case non-trivial enough to extract.

**Files:**
- Modify: `app/agents/tools.py:162` (add `parse_browser_discover_args` after `_KNOWN_PLATFORMS`), `:277-291` (simplify the `BROWSER_DISCOVER` branch to delegate to it)
- Test: `tests/test_maya_agent.py:1-6` (add import), add new tests near the existing `test_parse_browser_discover_*` tests (lines 17-38)

- [ ] **Step 1: Write failing unit tests for the standalone function**

In `tests/test_maya_agent.py`, change the import on line 5 from:

```python
from app.agents.tools import parse_tool_call
```

to:

```python
from app.agents.tools import parse_tool_call, parse_browser_discover_args
```

Then add these tests directly after `test_parse_browser_discover_non_platform_second_part` (after line 38):

```python
def test_parse_browser_discover_args_with_platform_and_location():
    parsed = parse_browser_discover_args("Python backend | linkedin | Bangalore")
    assert parsed == {"keywords": "Python backend", "platform": "linkedin", "location": "Bangalore"}


def test_parse_browser_discover_args_defaults():
    parsed = parse_browser_discover_args("FastAPI jobs")
    assert parsed == {"keywords": "FastAPI jobs", "platform": "linkedin", "location": "Bangalore"}


def test_parse_browser_discover_args_non_platform_second_part():
    parsed = parse_browser_discover_args("React developer | remote")
    assert parsed == {"keywords": "React developer", "platform": "linkedin", "location": "Bangalore"}
```

- [ ] **Step 2: Run the tests and confirm the new ones fail**

Run: `cd /mnt/HC_Volume_105874680/virtual-company && python -m pytest tests/test_maya_agent.py -v`

Expected: the three new `test_parse_browser_discover_args_*` tests FAIL with `ImportError: cannot import name 'parse_browser_discover_args'` (collection error) — the function doesn't exist yet. The existing `test_parse_browser_discover_*` tests (which exercise `parse_tool_call`) still pass.

- [ ] **Step 3: Add the function and delegate to it from `parse_tool_call`**

In `app/agents/tools.py`, add this function directly after `_KNOWN_PLATFORMS = {...}` (after line 162):

```python
def parse_browser_discover_args(raw: str) -> dict:
    """Split 'keywords | platform | location' into a dict, defaulting platform/location
    when the second segment isn't a recognised job board (so 'keywords | a city name'
    isn't mistaken for 'keywords | platform')."""
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) >= 2 and parts[1].lower() not in _KNOWN_PLATFORMS:
        return {
            "keywords": parts[0],
            "platform": "linkedin",
            "location": "Bangalore",
        }
    return {
        "keywords": parts[0] if parts else "",
        "platform": parts[1] if len(parts) > 1 else "linkedin",
        "location": parts[2] if len(parts) > 2 else "Bangalore",
    }
```

Then replace the `BROWSER_DISCOVER` branch of `parse_tool_call` (lines 277-291):

```python
    m = re.search(r'\[BROWSER_DISCOVER:\s*([^\]]+)\]', text)
    if m:
        raw = m.group(1)
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) >= 2 and parts[1].lower() not in _KNOWN_PLATFORMS:
            return "browser_discover", {
                "keywords": parts[0],
                "platform": "linkedin",
                "location": "Bangalore",
            }
        return "browser_discover", {
            "keywords": parts[0] if parts else "",
            "platform": parts[1] if len(parts) > 1 else "linkedin",
            "location": parts[2] if len(parts) > 2 else "Bangalore",
        }
```

with:

```python
    m = re.search(r'\[BROWSER_DISCOVER:\s*([^\]]+)\]', text)
    if m:
        return "browser_discover", parse_browser_discover_args(m.group(1))
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd /mnt/HC_Volume_105874680/virtual-company && python -m pytest tests/test_maya_agent.py -v`

Expected: PASS — all `test_parse_browser_discover_*` and `test_parse_browser_discover_args_*` tests green (the existing `parse_tool_call` tests continue to pass because it now produces identical dicts via the extracted function).

- [ ] **Step 5: Commit**

```bash
git add app/agents/tools.py tests/test_maya_agent.py
git commit -m "refactor: extract parse_browser_discover_args so output handler can reuse it"
```

### Task 2: Create the `BROWSER_APPLY` output-pipeline handler

**Files:**
- Create: `app/output/handlers/browser_apply.py`
- Test: `tests/test_handlers.py` (append after the `sing` tests, following the `speak`/`sing` pattern)

- [ ] **Step 1: Write the failing handler tests**

Append to `tests/test_handlers.py` (it already imports `pytest`, `AsyncMock`, `patch`):

```python
@pytest.mark.asyncio
async def test_browser_apply_handler_dispatches_and_returns_status(monkeypatch):
    import asyncio
    from app.output.handlers import browser_apply
    send = AsyncMock()
    dispatched = {}

    async def fake_call_browser_svc(tool_type, tool_args):
        dispatched["tool_type"] = tool_type
        dispatched["tool_args"] = tool_args
        return "[browser-svc: queued]"

    monkeypatch.setattr(browser_apply, "call_browser_svc", fake_call_browser_svc)
    text, bark_ok = await browser_apply.handle("https://linkedin.com/jobs/123", "maya", send)
    await asyncio.sleep(0)

    assert bark_ok is False
    assert "https://linkedin.com/jobs/123" in text
    assert dispatched == {"tool_type": "browser_apply", "tool_args": {"url": "https://linkedin.com/jobs/123"}}
    send.assert_called_once()
    assert send.call_args[0][0] == {
        "type": "tool_call", "agent": "maya", "tool": "browser_apply",
        "label": "Applying to job", "path": "https://linkedin.com/jobs/123",
    }


def test_browser_apply_pattern_matches_full_tag():
    from app.output.handlers import browser_apply
    sample = "[BROWSER_APPLY: https://linkedin.com/jobs/123]"
    m = browser_apply.PATTERN.search(sample)
    assert m is not None
    assert m.group(1).strip() == "https://linkedin.com/jobs/123"
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd /mnt/HC_Volume_105874680/virtual-company && python -m pytest tests/test_handlers.py -k browser_apply -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'app.output.handlers.browser_apply'`.

- [ ] **Step 3: Create the handler**

Create `app/output/handlers/browser_apply.py`:

```python
"""BROWSER_APPLY handler — dispatches [BROWSER_APPLY: url] to browser-svc."""
import asyncio
import logging
import re
from typing import Callable, Awaitable

from app.services.browser_svc import call_browser_svc

logger  = logging.getLogger(__name__)
TAG     = "BROWSER_APPLY"
PATTERN = re.compile(r'\[BROWSER_APPLY:\s*([^\]]+)\]')

Sender = Callable[[dict], Awaitable[None]]


async def handle(args: str, agent_id: str, send: Sender) -> tuple[str, bool]:
    url = args.strip()
    await send({"type": "tool_call", "agent": agent_id,
                "tool": "browser_apply", "label": "Applying to job",
                "path": url[:60]})
    asyncio.create_task(call_browser_svc("browser_apply", {"url": url}))
    return f"🚀 Applying to {url}...", False
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd /mnt/HC_Volume_105874680/virtual-company && python -m pytest tests/test_handlers.py -k browser_apply -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/output/handlers/browser_apply.py tests/test_handlers.py
git commit -m "feat: dispatch BROWSER_APPLY tags through the output pipeline"
```

### Task 3: Create the `BROWSER_DISCOVER` output-pipeline handler

**Files:**
- Create: `app/output/handlers/browser_discover.py`
- Test: `tests/test_handlers.py` (append after the Task 2 tests)

- [ ] **Step 1: Write the failing handler tests**

```python
@pytest.mark.asyncio
async def test_browser_discover_handler_dispatches_parsed_args(monkeypatch):
    import asyncio
    from app.output.handlers import browser_discover
    send = AsyncMock()
    dispatched = {}

    async def fake_call_browser_svc(tool_type, tool_args):
        dispatched["tool_type"] = tool_type
        dispatched["tool_args"] = tool_args
        return "[browser-svc: queued]"

    monkeypatch.setattr(browser_discover, "call_browser_svc", fake_call_browser_svc)
    text, bark_ok = await browser_discover.handle("Python backend | linkedin | Bangalore", "maya", send)
    await asyncio.sleep(0)

    assert bark_ok is False
    assert "Python backend" in text and "linkedin" in text and "Bangalore" in text
    assert dispatched["tool_type"] == "browser_discover"
    assert dispatched["tool_args"] == {
        "keywords": "Python backend", "platform": "linkedin", "location": "Bangalore",
    }
    send.assert_called_once()
    assert send.call_args[0][0]["tool"] == "browser_discover"


def test_browser_discover_pattern_matches_full_tag():
    from app.output.handlers import browser_discover
    sample = "[BROWSER_DISCOVER: Python backend | linkedin | Bangalore]"
    m = browser_discover.PATTERN.search(sample)
    assert m is not None
    assert "Python backend" in m.group(1)
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd /mnt/HC_Volume_105874680/virtual-company && python -m pytest tests/test_handlers.py -k browser_discover -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'app.output.handlers.browser_discover'`.

- [ ] **Step 3: Create the handler**

Create `app/output/handlers/browser_discover.py`:

```python
"""BROWSER_DISCOVER handler — dispatches [BROWSER_DISCOVER: keywords | platform | location]."""
import asyncio
import logging
import re
from typing import Callable, Awaitable

from app.agents.tools import parse_browser_discover_args
from app.services.browser_svc import call_browser_svc

logger  = logging.getLogger(__name__)
TAG     = "BROWSER_DISCOVER"
PATTERN = re.compile(r'\[BROWSER_DISCOVER:\s*([^\]]+)\]')

Sender = Callable[[dict], Awaitable[None]]


async def handle(args: str, agent_id: str, send: Sender) -> tuple[str, bool]:
    parsed = parse_browser_discover_args(args)
    await send({"type": "tool_call", "agent": agent_id,
                "tool": "browser_discover", "label": "Searching for jobs",
                "path": f"{parsed['keywords']} ({parsed['platform']})"[:60]})
    asyncio.create_task(call_browser_svc("browser_discover", parsed))
    return (
        f"🔎 Searching {parsed['platform']} for {parsed['keywords']} "
        f"in {parsed['location']}..."
    ), False
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd /mnt/HC_Volume_105874680/virtual-company && python -m pytest tests/test_handlers.py -k browser_discover -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/output/handlers/browser_discover.py tests/test_handlers.py
git commit -m "feat: dispatch BROWSER_DISCOVER tags through the output pipeline"
```

### Task 4: Create the `BROWSER_COMPANY` output-pipeline handler

**Files:**
- Create: `app/output/handlers/browser_company.py`
- Test: `tests/test_handlers.py` (append after the Task 3 tests)

- [ ] **Step 1: Write the failing handler tests**

```python
@pytest.mark.asyncio
async def test_browser_company_handler_dispatches_and_returns_status(monkeypatch):
    import asyncio
    from app.output.handlers import browser_company
    send = AsyncMock()
    dispatched = {}

    async def fake_call_browser_svc(tool_type, tool_args):
        dispatched["tool_type"] = tool_type
        dispatched["tool_args"] = tool_args
        return "[browser-svc: queued]"

    monkeypatch.setattr(browser_company, "call_browser_svc", fake_call_browser_svc)
    text, bark_ok = await browser_company.handle("Stripe", "maya", send)
    await asyncio.sleep(0)

    assert bark_ok is False
    assert "Stripe" in text
    assert dispatched == {"tool_type": "browser_company", "tool_args": {"company": "Stripe"}}
    send.assert_called_once()
    assert send.call_args[0][0]["tool"] == "browser_company"


def test_browser_company_pattern_matches_full_tag():
    from app.output.handlers import browser_company
    sample = "[BROWSER_COMPANY: Stripe]"
    m = browser_company.PATTERN.search(sample)
    assert m is not None
    assert m.group(1).strip() == "Stripe"
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd /mnt/HC_Volume_105874680/virtual-company && python -m pytest tests/test_handlers.py -k browser_company -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'app.output.handlers.browser_company'`.

- [ ] **Step 3: Create the handler**

Create `app/output/handlers/browser_company.py`:

```python
"""BROWSER_COMPANY handler — dispatches [BROWSER_COMPANY: Company Name] to browser-svc."""
import asyncio
import logging
import re
from typing import Callable, Awaitable

from app.services.browser_svc import call_browser_svc

logger  = logging.getLogger(__name__)
TAG     = "BROWSER_COMPANY"
PATTERN = re.compile(r'\[BROWSER_COMPANY:\s*([^\]]+)\]')

Sender = Callable[[dict], Awaitable[None]]


async def handle(args: str, agent_id: str, send: Sender) -> tuple[str, bool]:
    company = args.strip()
    await send({"type": "tool_call", "agent": agent_id,
                "tool": "browser_company", "label": "Searching company careers page",
                "path": company[:60]})
    asyncio.create_task(call_browser_svc("browser_company", {"company": company}))
    return f"🏢 Looking for roles at {company}...", False
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd /mnt/HC_Volume_105874680/virtual-company && python -m pytest tests/test_handlers.py -k browser_company -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/output/handlers/browser_company.py tests/test_handlers.py
git commit -m "feat: dispatch BROWSER_COMPANY tags through the output pipeline"
```

### Task 5: Create the `BROWSER_PROFILE_MATCH` output-pipeline handler

This tag has no arguments — `[BROWSER_PROFILE_MATCH]` — so its `PATTERN` needs a dummy capture group. `pipeline.process()` always extracts `match.group(1)` as `handler_args` (`pipeline.py:41-44`); a pattern with no capture group would make `match.group(1)` raise `IndexError`.

**Files:**
- Create: `app/output/handlers/browser_profile_match.py`
- Test: `tests/test_handlers.py` (append after the Task 4 tests)

- [ ] **Step 1: Write the failing handler tests**

```python
@pytest.mark.asyncio
async def test_browser_profile_match_handler_dispatches_and_returns_status(monkeypatch):
    import asyncio
    from app.output.handlers import browser_profile_match
    send = AsyncMock()
    dispatched = {}

    async def fake_call_browser_svc(tool_type, tool_args):
        dispatched["tool_type"] = tool_type
        dispatched["tool_args"] = tool_args
        return "[browser-svc: queued]"

    monkeypatch.setattr(browser_profile_match, "call_browser_svc", fake_call_browser_svc)
    text, bark_ok = await browser_profile_match.handle("BROWSER_PROFILE_MATCH", "maya", send)
    await asyncio.sleep(0)

    assert bark_ok is False
    assert "profile" in text.lower()
    assert dispatched == {"tool_type": "browser_profile_match", "tool_args": {}}
    send.assert_called_once()
    assert send.call_args[0][0]["tool"] == "browser_profile_match"


def test_browser_profile_match_pattern_matches_full_tag():
    from app.output.handlers import browser_profile_match
    sample = "[BROWSER_PROFILE_MATCH]"
    m = browser_profile_match.PATTERN.search(sample)
    assert m is not None
    assert m.group(1) == "BROWSER_PROFILE_MATCH"
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd /mnt/HC_Volume_105874680/virtual-company && python -m pytest tests/test_handlers.py -k browser_profile_match -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'app.output.handlers.browser_profile_match'`.

- [ ] **Step 3: Create the handler**

Create `app/output/handlers/browser_profile_match.py`:

```python
"""BROWSER_PROFILE_MATCH handler — dispatches [BROWSER_PROFILE_MATCH] to browser-svc."""
import asyncio
import logging
import re
from typing import Callable, Awaitable

from app.services.browser_svc import call_browser_svc

logger  = logging.getLogger(__name__)
TAG     = "BROWSER_PROFILE_MATCH"
PATTERN = re.compile(r'\[(BROWSER_PROFILE_MATCH)\]')

Sender = Callable[[dict], Awaitable[None]]


async def handle(args: str, agent_id: str, send: Sender) -> tuple[str, bool]:
    await send({"type": "tool_call", "agent": agent_id,
                "tool": "browser_profile_match",
                "label": "Matching profile to target companies",
                "path": "target_companies"})
    asyncio.create_task(call_browser_svc("browser_profile_match", {}))
    return "🎯 Matching your profile against target companies...", False
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd /mnt/HC_Volume_105874680/virtual-company && python -m pytest tests/test_handlers.py -k browser_profile_match -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/output/handlers/browser_profile_match.py tests/test_handlers.py
git commit -m "feat: dispatch BROWSER_PROFILE_MATCH tags through the output pipeline"
```

### Task 6: Register the four browser handlers in the output-tag registry

**Files:**
- Modify: `app/output/registry.py:11-17`
- Test: `tests/test_pipeline.py` (append a registry test)

- [ ] **Step 1: Write the failing registry test**

Append to `tests/test_pipeline.py`:

```python
def test_registry_includes_browser_tags():
    from app.output import registry
    registry._registry = None  # force a rebuild so the new imports are exercised
    reg = registry.get_registry()
    assert {"BROWSER_APPLY", "BROWSER_DISCOVER", "BROWSER_COMPANY", "BROWSER_PROFILE_MATCH"} <= reg.keys()
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `cd /mnt/HC_Volume_105874680/virtual-company && python -m pytest tests/test_pipeline.py::test_registry_includes_browser_tags -v`

Expected: FAIL — `get_registry()` returns only `{"SPEAK", "SING", "GENERATE_IMAGE", "EMAIL_USER"}`, so the subset assertion fails.

- [ ] **Step 3: Register the four handlers**

In `app/output/registry.py`, replace lines 11-17:

```python
        from app.output.handlers import speak, sing, image, email as email_handler
        _registry = {
            "SPEAK":          speak,
            "SING":           sing,
            "GENERATE_IMAGE": image,
            "EMAIL_USER":     email_handler,
        }
```

with:

```python
        from app.output.handlers import (
            speak, sing, image, email as email_handler,
            browser_apply, browser_discover, browser_company, browser_profile_match,
        )
        _registry = {
            "SPEAK":                 speak,
            "SING":                  sing,
            "GENERATE_IMAGE":        image,
            "EMAIL_USER":            email_handler,
            "BROWSER_APPLY":         browser_apply,
            "BROWSER_DISCOVER":      browser_discover,
            "BROWSER_COMPANY":       browser_company,
            "BROWSER_PROFILE_MATCH": browser_profile_match,
        }
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `cd /mnt/HC_Volume_105874680/virtual-company && python -m pytest tests/test_pipeline.py -v`

Expected: PASS — `test_registry_includes_browser_tags` and every other pipeline test green (the registry rebuild doesn't disturb the patched-`get_registry` tests, since each of those replaces the registry wholesale via `patch`).

- [ ] **Step 5: Commit**

```bash
git add app/output/registry.py tests/test_pipeline.py
git commit -m "feat: register BROWSER_* tags in the output-tag registry"
```

### Task 7: Stop hardcoding `slot_id: 1` in `_PAYLOAD_MAP` so browser-svc can auto-pick a free slot

Phase 1 Task 3 made `browser-svc` resolve `slot_id` server-side via `find_free_slot()` whenever the client omits it. The NEXUS-side payload builders must stop sending `"slot_id": 1` — otherwise every concurrent dispatch still collides on slot 1 with `409 Slot 1 is busy`, and the new auto-pick logic never engages.

**Files:**
- Modify: `app/services/browser_svc.py:14,16-21,22,23`
- Test: `tests/test_maya_agent.py` (add a payload-shape test near the existing `call_browser_svc` tests)

- [ ] **Step 1: Write a failing test asserting the payload omits `slot_id`**

Append to `tests/test_maya_agent.py`, after `test_call_browser_svc_slot_busy_409`:

```python
@pytest.mark.asyncio
async def test_call_browser_svc_omits_slot_id_so_server_can_autopick():
    from app.services.browser_svc import _PAYLOAD_MAP

    assert "slot_id" not in _PAYLOAD_MAP["browser_apply"]({"url": "https://test.com"})
    assert "slot_id" not in _PAYLOAD_MAP["browser_discover"]({"keywords": "Python"})
    assert "slot_id" not in _PAYLOAD_MAP["browser_company"]({"company": "Stripe"})
    assert "slot_id" not in _PAYLOAD_MAP["browser_profile_match"]({})
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `cd /mnt/HC_Volume_105874680/virtual-company && python -m pytest tests/test_maya_agent.py::test_call_browser_svc_omits_slot_id_so_server_can_autopick -v`

Expected: FAIL — all four lambdas currently include `"slot_id": 1`.

- [ ] **Step 3: Remove `slot_id` from every payload lambda**

In `app/services/browser_svc.py`, replace lines 13-24:

```python
_PAYLOAD_MAP = {
    "browser_apply":         lambda a: {"url": a.get("url", ""), "slot_id": 1, "tailor_cv": True},
    "browser_discover":      lambda a: {
        "keywords": a.get("keywords", ""),
        "platform": a.get("platform", "linkedin"),
        "location": a.get("location", "Bangalore"),
        "slot_id": 1,
        "tailor_cv": True,
    },
    "browser_company":       lambda a: {"company": a.get("company", ""), "slot_id": 1, "tailor_cv": True},
    "browser_profile_match": lambda a: {"slot_id": 1, "tailor_cv": True},
}
```

with:

```python
_PAYLOAD_MAP = {
    "browser_apply":         lambda a: {"url": a.get("url", ""), "tailor_cv": True},
    "browser_discover":      lambda a: {
        "keywords": a.get("keywords", ""),
        "platform": a.get("platform", "linkedin"),
        "location": a.get("location", "Bangalore"),
        "tailor_cv": True,
    },
    "browser_company":       lambda a: {"company": a.get("company", ""), "tailor_cv": True},
    "browser_profile_match": lambda a: {"tailor_cv": True},
}
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `cd /mnt/HC_Volume_105874680/virtual-company && python -m pytest tests/test_maya_agent.py -v`

Expected: PASS — `test_call_browser_svc_omits_slot_id_so_server_can_autopick` and every other test in the file green (the `Pydantic` models on the receiving end already default `slot_id` to `None` per Phase 1 Task 3, so omitting the key is valid).

- [ ] **Step 5: Commit**

```bash
git add app/services/browser_svc.py tests/test_maya_agent.py
git commit -m "fix: stop hardcoding slot_id=1 in browser-svc payloads so the server can auto-pick a free slot"
```

### Task 8: Add the `browser_result` feedback loop to the relay WebSocket

This closes the hallucination loop described in the spec's root-cause analysis: Maya currently has no `[Tool Output]` feedback on the `run_claude_agent`/`run_gemini_agent` paths, so she narrates plausible-sounding continuations of her own unconfirmed prior claims. `handle_browser_result` mirrors `_run_worker_bg`'s `record → run_agent → record` sequence (`websocket.py:127-129`) so a completed browser-svc task gets fed back into Maya's conversation as a real, grounded turn.

**Files:**
- Modify: `app/api/websocket.py` (add `handle_browser_result` after `_run_worker_bg`, i.e. after line 181)
- Modify: `app/main.py:99` (branch on `browser_result` inside `browser_relay_endpoint`)
- Test: `tests/test_websocket.py` (create if it doesn't exist — check first with `ls tests/test_websocket.py`)

- [ ] **Step 1: Write the failing test for `handle_browser_result`**

If `tests/test_websocket.py` doesn't exist, create it with this content; if it does, append the test (and the needed imports) to it:

```python
"""Tests for the browser-result feedback loop in app.api.websocket."""
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_handle_browser_result_records_and_reinvokes_agent():
    from app.api import websocket as ws_module

    with patch.object(ws_module, "broadcast_event", new_callable=AsyncMock) as mock_broadcast, \
         patch.object(ws_module.state, "record") as mock_record, \
         patch.object(ws_module, "run_agent", new_callable=AsyncMock,
                      return_value="[DONE: 1 applied — Stripe backend role]") as mock_run_agent, \
         patch.object(ws_module.deleg_svc, "clean_response", side_effect=lambda x: x):

        await ws_module.handle_browser_result({
            "type": "browser_result", "agent_id": "maya", "slot_id": 2,
            "tool": "browser_apply",
            "result": "Stripe — Backend Engineer: applied (https://linkedin.com/jobs/123)",
        })

    # state.record called once for the synthetic user turn, once for Maya's reply
    assert mock_record.call_count == 2
    user_call, assistant_call = mock_record.call_args_list
    assert user_call.args[0] == "maya"
    assert user_call.args[1] == "user"
    assert "(slot 2)" in user_call.args[2]
    assert "Stripe — Backend Engineer: applied" in user_call.args[2]
    assert assistant_call.args == ("maya", "assistant", "[DONE: 1 applied — Stripe backend role]")

    mock_run_agent.assert_called_once()
    assert mock_run_agent.call_args[0][0] == "maya"
    assert "(slot 2)" in mock_run_agent.call_args[0][1]

    # broadcast_event used for thinking/done so the dashboard reflects the re-invocation
    broadcast_types = [c.args[0]["type"] for c in mock_broadcast.call_args_list]
    assert "thinking" in broadcast_types
    assert "done" in broadcast_types
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `cd /mnt/HC_Volume_105874680/virtual-company && python -m pytest tests/test_websocket.py::test_handle_browser_result_records_and_reinvokes_agent -v`

Expected: FAIL — `AttributeError: <module 'app.api.websocket' ...> does not have the attribute 'handle_browser_result'`.

- [ ] **Step 3: Add `handle_browser_result`**

In `app/api/websocket.py`, add this function directly after `_run_worker_bg` ends (after line 181, before the `# ── Message router ──` comment on line 184):

```python
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
```

- [ ] **Step 4: Branch on `browser_result` in `browser_relay_endpoint`**

In `app/main.py:99`, change:

```python
            await broadcast_event(data)
```

to:

```python
            if data.get("type") == "browser_result":
                asyncio.create_task(ws_module.handle_browser_result(data))
            else:
                await broadcast_event(data)
```

- [ ] **Step 5: Run the test and confirm it passes**

Run: `cd /mnt/HC_Volume_105874680/virtual-company && python -m pytest tests/test_websocket.py -v`

Expected: PASS — `test_handle_browser_result_records_and_reinvokes_agent` green.

- [ ] **Step 6: Commit**

```bash
git add app/api/websocket.py app/main.py tests/test_websocket.py
git commit -m "feat: feed completed browser-svc results back into the worker's conversation over the relay channel"
```

### Task 9: Push `browser_result` events from `browser-svc` whenever a job application finishes

Every one of the four apply-style flows (`/apply`, `/discover`, `/company-apply`, `/profile-match`) funnels each individual job application through `_apply_on_slot` (`main.py:78-88`) — it's the single choke point where an `ApplyResult` is produced. Pushing the relay event there, once, reports every outcome from all four flows without touching each endpoint's background `run()` separately.

**Files:**
- Modify: `browser-svc/main.py:78-88` (`_apply_on_slot`)
- Test: `browser-svc/tests/test_main.py` (append after the apply/discover/company/profile-match tests)

- [ ] **Step 1: Write the failing test**

Append to `browser-svc/tests/test_main.py`:

```python
@pytest.mark.asyncio
async def test_apply_on_slot_pushes_browser_result(client):
    import main as m
    from session_manager import SlotInfo
    from job_workflow import ApplyResult

    fake_result = ApplyResult(
        url="https://linkedin.com/jobs/123", company="Stripe", role="Backend Engineer",
        status="applied",
    )
    fake_slot = SlotInfo(slot_id=2)

    with patch("job_workflow.apply_to_job", new_callable=AsyncMock, return_value=fake_result), \
         patch.object(m.relay, "push") as mock_push:
        await m._apply_on_slot(fake_slot, "https://linkedin.com/jobs/123", True)

    mock_push.assert_called_once()
    assert mock_push.call_args[0][0] == {
        "type": "browser_result",
        "agent_id": "maya",
        "slot_id": 2,
        "tool": "browser_apply",
        "result": "Stripe — Backend Engineer: applied (https://linkedin.com/jobs/123)",
    }
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `cd browser-svc && python -m pytest tests/test_main.py::test_apply_on_slot_pushes_browser_result -v`

Expected: FAIL — `mock_push.assert_called_once()` raises `AssertionError: Expected 'push' to have been called once. Called 0 times` because `_apply_on_slot` never calls `relay.push`.

- [ ] **Step 3: Push a `browser_result` event after every apply**

In `browser-svc/main.py`, replace `_apply_on_slot` (lines 78-88):

```python
async def _apply_on_slot(slot: SlotInfo, url: str, tailor_cv: bool):
    """Apply to a job URL using an already-acquired slot (caller handles acquire/release)."""
    from job_workflow import apply_to_job

    cv_path = str(CV_DEFAULT_PATH)
    result = await apply_to_job(
        slot.page, url, cv_path,
        slot_info=slot, tailor_cv=tailor_cv,
    )
    logger.info("Apply result: %s %s → %s", result.company, result.role, result.status)
    return result
```

with:

```python
async def _apply_on_slot(slot: SlotInfo, url: str, tailor_cv: bool):
    """Apply to a job URL using an already-acquired slot (caller handles acquire/release)."""
    from job_workflow import apply_to_job

    cv_path = str(CV_DEFAULT_PATH)
    result = await apply_to_job(
        slot.page, url, cv_path,
        slot_info=slot, tailor_cv=tailor_cv,
    )
    logger.info("Apply result: %s %s → %s", result.company, result.role, result.status)
    relay.push({
        "type": "browser_result",
        "agent_id": "maya",
        "slot_id": slot.slot_id,
        "tool": "browser_apply",
        "result": f"{result.company} — {result.role}: {result.status} ({url})",
    })
    return result
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `cd browser-svc && python -m pytest tests/test_main.py -v`

Expected: PASS — `test_apply_on_slot_pushes_browser_result` and every other test in the file green.

- [ ] **Step 5: Commit**

```bash
git add browser-svc/main.py browser-svc/tests/test_main.py
git commit -m "feat: push browser_result events to NEXUS over the relay whenever a job application finishes"
```

---

## Phase 3 — Live Dashboard / Browser Board Redesign (spec Section 2)

**Goal of this phase:** make the "live peek" actually trustworthy. Today the Browser Board renders 5 tiles (one for the now-removed Overleaf/CV slot), shows frames only when they happen to arrive over the relay WebSocket with no independent signal of slot health, and has no way to hand control to a human. This phase shrinks the board to the real 4-slot layout, adds a polled, frame-stream-independent status signal per tile (the spec's "structural backup signal... if frames stop arriving, the chip still tells you the slot's actual state"), and wires up the "Take over" entry point into Section 3's manual handoff.

**Design decisions for this phase (documented up front so the rationale is traceable):**

1. **Grid layout: 2×2 instead of 3-column-with-a-gap.** The current grid is `grid-template-columns:repeat(3,1fr)` sized for 5 browser tiles + 1 log tile = 6 cells (a clean 2×3). Dropping to 4 browser tiles + 1 log tile = 5 cells would leave an awkward empty cell in a 3-column layout. Switching to `repeat(2,1fr)` gives a clean 2×2 grid of browser tiles, with the log tile spanning both columns in its own row beneath (`grid-column:1 / -1`) — no leftover cells, no UI surgery beyond a CSS value and one inline style. This is the "drop or keep [the log tile] depending on remaining UI space" call the spec leaves to the implementation plan: **keep it**, but make it span the full width.

2. **Status chip and "last frame" timestamp combined into one element.** The spec lists these as two separate bullets, but showing two overlapping badges per tile (chip + timestamp + the existing "LIVE" badge) would clutter a tile that's roughly 280×200px. Rendering them as one chip — e.g. `"streaming · 2s ago"` or `"connecting · no frames yet"` — satisfies both requirements (the state is visible, and the staleness is visible) with a single, readable element, and trivially shows a stalled stream as `"connecting · 47s ago"` sitting frozen on screen.

3. **`SlotState` enum is NOT extended.** The spec's example chip states are `idle / connecting / streaming / error / awaiting input`, but `browser-svc`'s `SlotState` enum (`session_manager.py:9-12`) only has `idle / busy / error`, and that enum is load-bearing — `_slot_is_busy()` (`main.py:74-75`) and the acquire/release state machine (`session_manager.py:73-87`) all compare against it, as do several Phase-1-rewritten tests. Extending it to a 5-state machine would be a much larger, riskier surgery than this dashboard phase warrants, and isn't necessary: the frontend can derive the richer chip label by combining the polled `state` (`idle`/`busy`/`error`) with **frame-arrival recency it already observes** from the relay stream — "busy + a frame arrived in the last 5s" reads as "streaming"; "busy + no recent frame" reads as "connecting" (which is exactly the stalled-stream signal the spec wants surfaced). This keeps the backend's state machine untouched while still delivering every distinction the spec asks the *user* to be able to see.

4. **"Awaiting input" is deferred to Phase 4 (spec Section 3) — not stubbed here.** There is currently no signal anywhere in the system that a slot is blocked on a captcha/login-wall; that detection is exactly what Section 3's escalation flow (Phase 4 of this plan) will add. Writing an `"awaiting input"` branch now would mean branching on a condition that can never be true yet — a disguised placeholder. Instead, `_computeSlotChip` (Task 2) is written as a small, three-way `backendState` switch that Phase 4 extends with one more branch once it defines the actual escalation signal (e.g. a `blocked: true` flag on the polled slot or a dedicated WS message) — no rework of this phase's code, just an addition to it.

5. **"Auto-reconnect" in `relay_client.py` is already implemented — no code task needed.** Re-reading the spec's Section 2 bullet "Auto-reconnect + fixed logging in `relay_client.py`" against the actual code (`browser-svc/relay_client.py:35-56`): `_run()` is already wrapped in an outer `while True` with a `try/except` that logs a warning and retries after `await asyncio.sleep(3)` on any disconnect — that *is* the auto-reconnect mechanism, and it was already exercised by `test_start_creates_task` before this plan started. The spec bundles it with "fixed logging" because the reconnect attempts were *invisible* (the bug Phase 1 Task 5 fixed by adding `logging.basicConfig(...)`); now that the logger is configured, the existing reconnect loop's `"browser-relay disconnected (%s) — retrying in 3s"` warnings will actually appear in `docker logs`, making the already-correct mechanism observable. Writing a second "add auto-reconnect" task here would duplicate working code — so this phase contains no `relay_client.py` changes at all.

### Task 1: Shrink the Browser Board to 4 tiles in a clean 2×2 grid, relabeled Slot 0–3

**Files:**
- Modify: `app/static/index.html:161, 175-181`
- Modify: `app/static/app-v5.js:1079, 1087, 1103, 1156-1225`
- Test: none — this is presentation-only vanilla JS/HTML with no test harness in the repo (confirmed: no `package.json`/`*.test.js`/Jest config exists). Verified by manual browser check in Step 4.

- [ ] **Step 1: Update the slot-select dropdown and header comment in `index.html`**

In `app/static/index.html`, change line 161 from:

```html
<!-- Browser Board island — live view of all 5 Maya browser slots -->
```

to:

```html
<!-- Browser Board island — live view of all 4 Maya browser slots -->
```

Then change lines 175-181 from:

```html
    <select id="board-slot-select" onchange="selectBoardSlot(parseInt(this.value))" style="background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:4px;font-size:11px;padding:2px 4px">
      <option value="0">Overleaf (CV)</option>
      <option value="1" selected>Slot 1</option>
      <option value="2">Slot 2</option>
      <option value="3">Slot 3</option>
      <option value="4">Slot 4</option>
    </select>
```

to:

```html
    <select id="board-slot-select" onchange="selectBoardSlot(parseInt(this.value))" style="background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:4px;font-size:11px;padding:2px 4px">
      <option value="0" selected>Slot 0</option>
      <option value="1">Slot 1</option>
      <option value="2">Slot 2</option>
      <option value="3">Slot 3</option>
    </select>
```

- [ ] **Step 2: Update `_SLOT_LABELS`, the highlight loop, and the default-selected slot in `app-v5.js`**

Change line 1079 from:

```javascript
const _SLOT_LABELS = ["Overleaf (CV)", "Slot 1", "Slot 2", "Slot 3", "Slot 4"];
```

to:

```javascript
const _SLOT_LABELS = ["Slot 0", "Slot 1", "Slot 2", "Slot 3"];
```

Change line 1087 (inside `selectBoardSlot`) from:

```javascript
  for (let i = 0; i < 5; i++) {
```

to:

```javascript
  for (let i = 0; i < 4; i++) {
```

Change line 1103 (inside `getSelectedBoardSlot`) from:

```javascript
  return select ? parseInt(select.value) : 1;
```

to:

```javascript
  return select ? parseInt(select.value) : 0;
```

- [ ] **Step 3: Rebuild `initBrowserBoard` for a 4-tile 2×2 grid with a full-width log tile**

Replace the entire `initBrowserBoard` function (`app/static/app-v5.js:1156-1225`) — i.e. everything from `function initBrowserBoard() {` through its closing `}` — with:

```javascript
function initBrowserBoard() {
  const grid = document.getElementById("browser-board-grid");
  if (!grid || Object.keys(_boardTiles).length > 0) return;
  grid.style.cssText =
    "display:grid;grid-template-columns:repeat(2,1fr);gap:6px;padding:8px;height:calc(100% - 72px);box-sizing:border-box";

  for (let i = 0; i < 4; i++) {
    const tile = document.createElement("div");
    tile.style.cssText =
      "position:relative;background:#0d1117;border:1px solid var(--border);border-radius:6px;overflow:hidden;cursor:pointer";
    tile.innerHTML =
      `<img id="bframe-${i}" src="" style="width:100%;height:100%;object-fit:fill;display:none">` +
      `<div id="bidle-${i}" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:4px">` +
        `<span style="color:var(--muted);font-size:11px">${_SLOT_LABELS[i]}</span>` +
        `<span style="color:var(--border);font-size:9px">idle</span>` +
      `</div>` +
      `<div id="bstatus-${i}" style="position:absolute;bottom:0;left:0;right:0;padding:3px 6px;background:rgba(0,0,0,0.75);font-size:9px;color:#00d4ff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:none"></div>` +
      `<div id="bbadge-${i}" style="position:absolute;top:4px;right:4px;padding:1px 5px;border-radius:3px;font-size:8px;font-weight:700;background:rgba(0,255,128,0.15);color:#0f0;display:none">LIVE</div>`;

    tile.addEventListener("click", e => {
      selectBoardSlot(i);
      const img = document.getElementById(`bframe-${i}`);
      if (img && img.style.display !== "none" && e.target === img) {
        const rect = img.getBoundingClientRect();
        const clickX = e.clientX - rect.left;
        const clickY = e.clientY - rect.top;
        const pctX = clickX / rect.width;
        const pctY = clickY / rect.height;
        const x = Math.round(pctX * 1280);
        const y = Math.round(pctY * 900);

        fetch(`/api/browser-svc/slots/${i}/click`, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({ x, y }),
        });
      }
    });

    grid.appendChild(tile);
    _boardTiles[i] = {
      img: document.getElementById(`bframe-${i}`),
      idle: document.getElementById(`bidle-${i}`),
      status: document.getElementById(`bstatus-${i}`),
      badge: document.getElementById(`bbadge-${i}`),
    };
  }

  // Setup inputs Enter listeners
  const boardUrlInput = document.getElementById("board-url-input");
  if (boardUrlInput) {
    boardUrlInput.addEventListener("keydown", e => { if (e.key === "Enter") boardNavigate(); });
  }
  const boardTypeInput = document.getElementById("board-type-input");
  if (boardTypeInput) {
    boardTypeInput.addEventListener("keydown", e => { if (e.key === "Enter") boardType(); });
  }

  // Log tile spans both columns of the 2×2 grid so 4 browser tiles + 1 log
  // tile leave no awkward empty cell (was a clean 2×3 with 5 browser tiles;
  // a plain 3-column grid with 4 would leave a gap).
  const logTile = document.createElement("div");
  logTile.style.cssText =
    "background:#0d1117;border:1px solid var(--border);border-radius:6px;padding:8px;overflow-y:auto;grid-column:1 / -1";
  logTile.innerHTML =
    `<div style="font-size:10px;color:#00ff88;margin-bottom:4px;font-weight:600">Apply Log</div>` +
    `<div id="board-log" style="font-size:9px;color:var(--muted);display:flex;flex-direction:column;gap:3px"></div>`;
  grid.appendChild(logTile);

  // Default-select Slot 0 — it's a real browser slot now, not Overleaf/CV
  setTimeout(() => selectBoardSlot(0), 100);
}
```

- [ ] **Step 4: Manually verify the 4-tile layout**

Start the app (or use whatever local dev flow is already running it), open the dashboard in a browser, and open the Browser Board island (the 🌐 "Open Browser Panel" action). Confirm:
- Exactly 4 browser tiles render in a 2×2 grid (not 5, not a 3-column layout with a gap)
- The "Apply Log" tile spans the full width beneath the 2×2 grid
- The slot-select dropdown shows "Slot 0" (selected by default) through "Slot 3" — no "Overleaf (CV)" entry
- Clicking each tile highlights it and updates the dropdown selection to match (the existing `selectBoardSlot` highlight behavior, now bounded to 4 tiles)

- [ ] **Step 5: Commit**

```bash
git add app/static/index.html app/static/app-v5.js
git commit -m "feat: shrink Browser Board to a 4-tile 2x2 grid (slots 0-3), removing the retired Overleaf/CV slot"
```

### Task 2: Add per-slot status chips with frame-recency, polled from `/api/browser-svc/slots`

This is the spec's "structural backup signal that's independent of the JPEG frame stream" plus the "last frame received" staleness indicator — combined into one chip per tile (see Design Decision 2 above). The chip is computed by combining the polled `state` (`idle`/`busy`/`error` — confirmed in `session_manager.py:89-93`) with how recently `handleBrowserFrame` last updated that tile, so a tile reads `"streaming · 2s ago"` when healthy and `"connecting · 47s ago"` when the stream has stalled — visually obvious exactly as the spec asks, with no reliance on the frame stream itself to report its own health.

**Files:**
- Modify: `app/static/app-v5.js` (tile markup + `_boardTiles` shape inside `initBrowserBoard`, `handleBrowserFrame`, `showIsland`/`hideIsland`; new helpers + polling functions)
- Test: none — vanilla JS, no test harness (see Task 1). Verified by manual browser check in Step 5.

- [ ] **Step 1: Add a `bchip-${i}` element to each tile and track `lastFrameAt` per tile**

In `app/static/app-v5.js`, inside `initBrowserBoard` (as rebuilt in Task 1), change the `tile.innerHTML` assignment from:

```javascript
    tile.innerHTML =
      `<img id="bframe-${i}" src="" style="width:100%;height:100%;object-fit:fill;display:none">` +
      `<div id="bidle-${i}" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:4px">` +
        `<span style="color:var(--muted);font-size:11px">${_SLOT_LABELS[i]}</span>` +
        `<span style="color:var(--border);font-size:9px">idle</span>` +
      `</div>` +
      `<div id="bstatus-${i}" style="position:absolute;bottom:0;left:0;right:0;padding:3px 6px;background:rgba(0,0,0,0.75);font-size:9px;color:#00d4ff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:none"></div>` +
      `<div id="bbadge-${i}" style="position:absolute;top:4px;right:4px;padding:1px 5px;border-radius:3px;font-size:8px;font-weight:700;background:rgba(0,255,128,0.15);color:#0f0;display:none">LIVE</div>`;
```

to:

```javascript
    tile.innerHTML =
      `<img id="bframe-${i}" src="" style="width:100%;height:100%;object-fit:fill;display:none">` +
      `<div id="bidle-${i}" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:4px">` +
        `<span style="color:var(--muted);font-size:11px">${_SLOT_LABELS[i]}</span>` +
        `<span style="color:var(--border);font-size:9px">idle</span>` +
      `</div>` +
      `<div id="bchip-${i}" style="position:absolute;top:4px;left:4px;padding:1px 6px;border-radius:3px;font-size:8px;font-weight:700;background:rgba(255,255,255,0.08);color:var(--muted)">idle</div>` +
      `<div id="bstatus-${i}" style="position:absolute;bottom:0;left:0;right:0;padding:3px 6px;background:rgba(0,0,0,0.75);font-size:9px;color:#00d4ff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:none"></div>` +
      `<div id="bbadge-${i}" style="position:absolute;top:4px;right:4px;padding:1px 5px;border-radius:3px;font-size:8px;font-weight:700;background:rgba(0,255,128,0.15);color:#0f0;display:none">LIVE</div>`;
```

Then change the `_boardTiles[i] = {...}` assignment from:

```javascript
    _boardTiles[i] = {
      img: document.getElementById(`bframe-${i}`),
      idle: document.getElementById(`bidle-${i}`),
      status: document.getElementById(`bstatus-${i}`),
      badge: document.getElementById(`bbadge-${i}`),
    };
```

to:

```javascript
    _boardTiles[i] = {
      img: document.getElementById(`bframe-${i}`),
      idle: document.getElementById(`bidle-${i}`),
      status: document.getElementById(`bstatus-${i}`),
      badge: document.getElementById(`bbadge-${i}`),
      chip: document.getElementById(`bchip-${i}`),
      lastFrameAt: null,
    };
```

- [ ] **Step 2: Record `lastFrameAt` whenever a real frame arrives**

In `app/static/app-v5.js`, change `handleBrowserFrame` (lines 1227-1245) from:

```javascript
function handleBrowserFrame(obj) {
  const boardEl = document.getElementById("island-board");
  if (!boardEl) return;
  initBrowserBoard();
  const slot = obj.slot != null ? obj.slot : 0;
  const tile = _boardTiles[slot];
  if (!tile) return;
  if (obj.frame) {
    tile.img.src = "data:image/jpeg;base64," + obj.frame;
    tile.img.style.display = "block";
    tile.idle.style.display = "none";
    tile.badge.style.display = "block";
  }
  const label = (obj.action ? obj.action + (obj.url ? "  —  " + obj.url : "") : obj.url) || "";
  if (label) {
    tile.status.textContent = label;
    tile.status.style.display = "block";
  }
}
```

to:

```javascript
function handleBrowserFrame(obj) {
  const boardEl = document.getElementById("island-board");
  if (!boardEl) return;
  initBrowserBoard();
  const slot = obj.slot != null ? obj.slot : 0;
  const tile = _boardTiles[slot];
  if (!tile) return;
  if (obj.frame) {
    tile.img.src = "data:image/jpeg;base64," + obj.frame;
    tile.img.style.display = "block";
    tile.idle.style.display = "none";
    tile.badge.style.display = "block";
    tile.lastFrameAt = Date.now();
  }
  const label = (obj.action ? obj.action + (obj.url ? "  —  " + obj.url : "") : obj.url) || "";
  if (label) {
    tile.status.textContent = label;
    tile.status.style.display = "block";
  }
}
```

- [ ] **Step 3: Add the chip-formatting helpers and the polling loop**

In `app/static/app-v5.js`, add the following directly after `handleBrowserFrame`'s closing `}` (i.e. immediately before `function logApplyResult(obj) {`):

```javascript
function _formatFrameAge(ms) {
  if (ms == null) return "no frames yet";
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s ago`;
  return `${Math.round(s / 60)}m ago`;
}

// Combines browser-svc's polled slot state with frame-arrival recency into one
// chip: "busy" + a frame within the last 5s reads as "streaming"; "busy" with
// no recent frame reads as "connecting" — the stalled-stream signal the spec
// wants visible even when the JPEG stream itself goes silent. An "awaiting
// input" branch belongs here once Phase 4 (spec Section 3) defines the
// escalation signal that would set it — see Design Decision 4 above.
function _computeSlotChip(backendState, lastFrameAt) {
  const ageMs = lastFrameAt != null ? Date.now() - lastFrameAt : null;
  if (backendState === "error") return { text: "error", color: "#ff4444" };
  if (backendState === "idle")  return { text: "idle",  color: "var(--muted)" };
  if (ageMs == null || ageMs > 5000) {
    return { text: `connecting · ${_formatFrameAge(ageMs)}`, color: "#ffaa00" };
  }
  return { text: `streaming · ${_formatFrameAge(ageMs)}`, color: "#00ff88" };
}

let _boardStatusInterval = null;

async function pollBoardSlotStatuses() {
  let slots;
  try {
    const r = await fetch("/api/browser-svc/slots");
    if (!r.ok) return;
    slots = await r.json();
  } catch (e) {
    return; // browser-svc unreachable this tick — chips simply hold their last value
  }
  for (const s of slots) {
    const tile = _boardTiles[s.slot_id];
    if (!tile || !tile.chip) continue;
    const label = _computeSlotChip(s.state, tile.lastFrameAt);
    tile.chip.textContent = label.text;
    tile.chip.style.color = label.color;
  }
}

function startBoardStatusPolling() {
  if (_boardStatusInterval) return;
  pollBoardSlotStatuses();
  _boardStatusInterval = setInterval(pollBoardSlotStatuses, 3000);
}

function stopBoardStatusPolling() {
  if (_boardStatusInterval) {
    clearInterval(_boardStatusInterval);
    _boardStatusInterval = null;
  }
}
```

- [ ] **Step 4: Start/stop polling when the board island opens/closes**

This follows the exact pattern `showIsland`/`hideIsland` already use for `startBrowserAutoRefresh`/`stopBrowserAutoRefresh` (lines 446, 451) — polling only runs while the island is visible.

In `app/static/app-v5.js`, change `showIsland` (`app/static/app-v5.js:440-447`) from:

```javascript
function showIsland(name) {
  $id(`island-${name}`).style.display = "block";
  if (name === "design") {
    const iframe = $id("design-iframe");
    if (!iframe.src || iframe.src === location.origin + "/") iframe.src = "/static/previews/index.html";
  }
  if (name === "browser") startBrowserAutoRefresh();
}
```

to:

```javascript
function showIsland(name) {
  $id(`island-${name}`).style.display = "block";
  if (name === "design") {
    const iframe = $id("design-iframe");
    if (!iframe.src || iframe.src === location.origin + "/") iframe.src = "/static/previews/index.html";
  }
  if (name === "browser") startBrowserAutoRefresh();
  if (name === "board") startBoardStatusPolling();
}
```

Then change `hideIsland` (`app/static/app-v5.js:449-452`) from:

```javascript
function hideIsland(name) {
  $id(`island-${name}`).style.display = "none";
  if (name === "browser") stopBrowserAutoRefresh();
}
```

to:

```javascript
function hideIsland(name) {
  $id(`island-${name}`).style.display = "none";
  if (name === "browser") stopBrowserAutoRefresh();
  if (name === "board") stopBoardStatusPolling();
}
```

- [ ] **Step 5: Manually verify chips and polling lifecycle**

Open the dashboard, open the Browser Board island, and confirm:
- Each tile shows a chip in its top-left corner reading e.g. `"idle"`, `"connecting · no frames yet"`, or `"streaming · 2s ago"`, refreshing roughly every 3 seconds
- While Maya is actively running a browser task on a slot, that tile's chip transitions from `"connecting · ..."` to `"streaming · Ns ago"` as frames start arriving, and the "Ns ago" portion stays low (≤ ~5s) while frames keep flowing
- If frames stop arriving mid-task (e.g. simulate by leaving a tab idle), the chip visibly drifts to `"connecting · 23s ago"`, `"connecting · 51s ago"`, etc., making the stall obvious without a frozen image being mistaken for "still working"
- Open the browser DevTools Network tab, confirm `GET /api/browser-svc/slots` requests fire every ~3s while the island is open, and confirm they **stop** within ~3s of clicking the island's ✕ close button (`hideIsland('board')`)

- [ ] **Step 6: Commit**

```bash
git add app/static/app-v5.js
git commit -m "feat: add per-slot status chips with frame-recency to the Browser Board, polled from /api/browser-svc/slots"
```

### Task 3: Add a "Take over" button per slot, backed by a new `ensure-interactive` browser-svc endpoint

This is the UI entry point into Section 3's manual handoff (Phase 4 of this plan): clicking "Take over" calls `ensure_interactive()` (`session_manager.py:136-140`), which gets-or-creates the slot's page and starts its screencast — the same mechanism the existing `click`/`type`/`navigate`/etc. interactive endpoints already rely on (`browser-svc/main.py:252-336`), just without requiring the user to also supply click coordinates or text first.

**Files:**
- Modify: `browser-svc/main.py` (add `slot_ensure_interactive` after `slot_back`, i.e. after line 336)
- Test: `browser-svc/tests/test_main.py` (append after `test_profile_match_queues`)
- Modify: `app/static/app-v5.js` (tile markup + click handler inside `initBrowserBoard`, as rebuilt in Tasks 1-2)

- [ ] **Step 1: Write the failing backend tests**

Append to `browser-svc/tests/test_main.py` (it already imports `pytest`, `AsyncMock`, `patch` — see lines 1-4):

```python
def test_ensure_interactive_starts_screencast_and_returns_ok(client):
    import main as m
    with patch.object(m.session_manager, "ensure_interactive", new_callable=AsyncMock) as mock_ensure:
        r = client.post("/slots/2/ensure-interactive")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    mock_ensure.assert_called_once_with(2, m.relay)


def test_ensure_interactive_rejects_out_of_range_slot(client):
    r = client.post("/slots/4/ensure-interactive")
    assert r.status_code == 400
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd browser-svc && python -m pytest tests/test_main.py -k ensure_interactive -v`

Expected: FAIL — both tests get a `404 Not Found` response (no such route registered), so `assert r.status_code == 200` and `assert r.status_code == 400` both fail with `assert 404 == 200` / `assert 404 == 400`.

- [ ] **Step 3: Add the endpoint**

In `browser-svc/main.py`, add this directly after `slot_back` ends (after line 336 — the `except Exception as exc: raise HTTPException(500, f"Go back failed: {exc}")` block — and before EOF):

```python
@app.post("/slots/{slot_id}/ensure-interactive")
async def slot_ensure_interactive(slot_id: int):
    if slot_id < 0 or slot_id >= session_manager.NUM_SLOTS:
        raise HTTPException(400, f"slot_id must be 0–{session_manager.NUM_SLOTS - 1}")
    await session_manager.ensure_interactive(slot_id, relay)
    return {"ok": True}
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd browser-svc && python -m pytest tests/test_main.py -v`

Expected: PASS — `test_ensure_interactive_starts_screencast_and_returns_ok`, `test_ensure_interactive_rejects_out_of_range_slot`, and every other test in the file green.

- [ ] **Step 5: Commit the backend endpoint**

```bash
git add browser-svc/main.py browser-svc/tests/test_main.py
git commit -m "feat: add /slots/{id}/ensure-interactive endpoint as the backend entry point for Take over"
```

- [ ] **Step 6: Add the "Take over" button to each tile**

In `app/static/app-v5.js`, inside `initBrowserBoard`, change the `tile.innerHTML` assignment (as it stands after Task 2 Step 1) from:

```javascript
    tile.innerHTML =
      `<img id="bframe-${i}" src="" style="width:100%;height:100%;object-fit:fill;display:none">` +
      `<div id="bidle-${i}" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:4px">` +
        `<span style="color:var(--muted);font-size:11px">${_SLOT_LABELS[i]}</span>` +
        `<span style="color:var(--border);font-size:9px">idle</span>` +
      `</div>` +
      `<div id="bchip-${i}" style="position:absolute;top:4px;left:4px;padding:1px 6px;border-radius:3px;font-size:8px;font-weight:700;background:rgba(255,255,255,0.08);color:var(--muted)">idle</div>` +
      `<div id="bstatus-${i}" style="position:absolute;bottom:0;left:0;right:0;padding:3px 6px;background:rgba(0,0,0,0.75);font-size:9px;color:#00d4ff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:none"></div>` +
      `<div id="bbadge-${i}" style="position:absolute;top:4px;right:4px;padding:1px 5px;border-radius:3px;font-size:8px;font-weight:700;background:rgba(0,255,128,0.15);color:#0f0;display:none">LIVE</div>`;
```

to:

```javascript
    tile.innerHTML =
      `<img id="bframe-${i}" src="" style="width:100%;height:100%;object-fit:fill;display:none">` +
      `<div id="bidle-${i}" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:4px">` +
        `<span style="color:var(--muted);font-size:11px">${_SLOT_LABELS[i]}</span>` +
        `<span style="color:var(--border);font-size:9px">idle</span>` +
      `</div>` +
      `<div id="bchip-${i}" style="position:absolute;top:4px;left:4px;padding:1px 6px;border-radius:3px;font-size:8px;font-weight:700;background:rgba(255,255,255,0.08);color:var(--muted)">idle</div>` +
      `<div id="bstatus-${i}" style="position:absolute;bottom:0;left:0;right:0;padding:3px 6px;background:rgba(0,0,0,0.75);font-size:9px;color:#00d4ff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:none"></div>` +
      `<div id="bbadge-${i}" style="position:absolute;top:4px;right:4px;padding:1px 5px;border-radius:3px;font-size:8px;font-weight:700;background:rgba(0,255,128,0.15);color:#0f0;display:none">LIVE</div>` +
      `<button id="btakeover-${i}" style="position:absolute;bottom:4px;right:4px;padding:2px 8px;font-size:8px;font-weight:700;border-radius:3px;border:1px solid #00d4ff;background:rgba(0,212,255,0.12);color:#00d4ff;cursor:pointer;z-index:2">Take over</button>`;
```

Then, in the same loop body, directly after the existing `tile.addEventListener("click", e => { ... });` block and before `grid.appendChild(tile);`, add:

```javascript
    const takeoverBtn = tile.querySelector(`#btakeover-${i}`);
    if (takeoverBtn) {
      takeoverBtn.addEventListener("click", e => {
        e.stopPropagation();
        selectBoardSlot(i);
        fetch(`/api/browser-svc/slots/${i}/ensure-interactive`, { method: "POST" });
      });
    }
```

(`e.stopPropagation()` keeps the button click from also bubbling into the tile's own click handler, which would otherwise interpret the button's on-screen coordinates as a page click and fire a spurious `/api/browser-svc/slots/{i}/click`.)

- [ ] **Step 7: Manually verify "Take over"**

Open the Browser Board, open DevTools' Network tab, and click "Take over" on a slot tile. Confirm:
- A single `POST /api/browser-svc/slots/{id}/ensure-interactive` request fires, returning `{"ok": true}` with no accompanying `/click` request (the `stopPropagation` guard working)
- The dropdown's selection updates to that slot (the existing `selectBoardSlot` call)
- The tile's chip (Task 2) transitions toward `"streaming · Ns ago"` shortly after, since `ensure_interactive` starts the slot's screencast — confirming the button actually engaged the browser session rather than just returning a fake "ok"

- [ ] **Step 8: Commit**

```bash
git add app/static/app-v5.js
git commit -m "feat: add Take over button per Browser Board tile wired to the ensure-interactive endpoint"
```

---

## Phase 4 — Automation ↔ Manual Handoff, Learning Loop & Future-Worker Pattern (spec Sections 3 & 5)

**Goal of this phase:** stop the workflow from retry-looping or silently failing when it hits a captcha or login wall. Detect the blocker, classify it, hand control to a human via the "Take over" button (Phase 3 Task 3), let them resolve it, then **continue from the unblocked page state** — not restart. Persist what happened so Maya can warn proactively next time she's about to run into the same site. Finally, write down the worker-integration pattern this whole redesign established (spec Section 5), so the next worker after Maya doesn't reinvent it.

**Design decisions for this phase:**

1. **Pause/resume is a per-slot `asyncio.Event`, not a polling loop.** `job_workflow.py` already runs inside `browser-svc`'s event loop (it's all `async def`). The cleanest way to block one slot's workflow coroutine until a human acts — without burning CPU on a poll — is `asyncio.Event.wait()`. `SlotInfo` gains `blocked_reason: str` (what the dashboard chip shows) and `resume_event: asyncio.Event` (what the workflow coroutine awaits); `SessionManager` gains `mark_blocked`/`wait_for_resume`/`resume` to manage them under its existing lock, mirroring how `acquire`/`release` already manage `state`.

2. **Resuming re-fetches the job description instead of restarting `apply_to_job`.** The spec requires "the workflow continues from the now-unblocked page state — not a restart from scratch." Once a human resolves a login wall or captcha (in interactive mode, via "Take over"), the *page* has moved on, but `apply_to_job` is still mid-flight on the same `page` object — so the only stale piece of state is the job description it fetched *before* the blocker appeared. Re-running `fetch_job_description(page, url)` on the now-unblocked page picks up from where things actually are, without re-navigating, re-tailoring a CV that's already in flight, or repeating any of the apply-button-clicking that hasn't happened yet. This is "continue," not "restart," in the most literal sense the existing code structure allows.

3. **Two relay event types, two destinations — not one event serving double duty.** `browser_blocked` (fired the moment a blocker is detected) is a pure **notification** signal: the frontend already has a generic `else: await broadcast_event(data)` fallback (added in Phase 2 Task 8) that forwards any relay message it doesn't specially handle straight to connected dashboards, exactly like `approval_requested` works today — so `browser_blocked` needs *no* new NEXUS-side Python handler, only a new `case` in the frontend's switch (Task 6). `browser_blocker_resolved` (fired after the human resumes) is a **persistence** signal carrying the `{site, blocker_type, resolution, timestamp}` tuple the spec's learning loop wants — and persistence requires a database write, which only NEXUS can do (browser-svc is a separate container/process and cannot import `app.services.memory`). So it gets a dedicated handler, `handle_browser_blocker_resolved` (Task 5), mirroring `handle_browser_result` from Phase 2 Task 8. One relay channel, two message types, each routed to wherever the work for it actually has to happen.

4. **The "proactive query" half of the learning loop needs no new code — it already exists.** The spec says "Before starting a new run on a site that has caused trouble before, Maya proactively queries memory and adapts or warns up front." Look at `_build_context_block` (`app/agents/executor.py:138-141`): it already calls `mem_svc.get_relevant_memories(agent_id, user_query, limit=5)` on **every single turn** and injects the results into Maya's prompt as "Relevant memories." The moment Task 5 starts saving blocker memories whose `content` string names the site (e.g., `"Blocker on naukri.com: login_wall — ..."`), a user message like "apply to naukri.com jobs" will retrieve that memory through the exact same FTS5 path Phase 1 Task 4 already fixed for punctuated free text — and Maya will see it in her live context before she ever queues a `[BROWSER_DISCOVER:...]`. Writing a second, bespoke "check memory before starting a browser run" code path would duplicate a mechanism that already runs unconditionally on every turn; it would also be *redundant* in the DRY/YAGNI sense the user has emphasized for this plan. Task 5's job is simply to make sure the memory *exists* and is *findable* — the "querying it proactively" half is the existing context-injection pipeline doing what it already does.

5. **Section 5 (future-worker pattern) is documentation, not code — exactly as the spec's own Testing section says.** Spec line 249-250: *"no new code to test directly — validated by Section 1 working as a generic mechanism."* Writing a fake "pattern test" or a stub "next worker" would be inventing work the spec explicitly says isn't needed. Instead, Task 7 writes the actual checklist as a living reference document, populated with concrete pointers into the code this plan just built (not generic advice) — so the next person adding a worker has a copy-pasteable map instead of a vague suggestion to "follow the pattern."

### Task 1: Add blocker detection to `job_workflow.py`

This is the spec's "Detection... check for captcha selectors/text, unexpected login-wall redirects, or missing expected DOM elements" — implemented as a single `detect_blocker(page)` classifier that returns a structured `{"blocker_type": ..., "description": ...}` dict (or `None`) so the rest of the pipeline (Tasks 3-5) can act on, display, and persist a clean signal rather than re-deriving it from raw page state at each step.

**Files:**
- Modify: `browser-svc/job_workflow.py` (add `_CAPTCHA_SELECTORS`/`_CAPTCHA_TEXT_PATTERNS`/`_LOGIN_WALL_SELECTORS`/`_LOGIN_WALL_TEXT_PATTERNS`, `_any_visible`, `_any_match`, `detect_blocker` after `attach_cv`, i.e. after line 158, before the "LinkedIn Easy Apply" section comment on line 161)
- Test: `browser-svc/tests/test_job_workflow.py` (append after the existing tests; uses `AsyncMock`/`MagicMock`, already imported at the top of the file per line 4)

- [ ] **Step 1: Write the failing tests**

Append to `browser-svc/tests/test_job_workflow.py`:

```python
import pytest
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_detect_blocker_recognizes_captcha_selector():
    from job_workflow import detect_blocker

    page = AsyncMock()
    page.url = "https://example.com/apply"
    page.inner_text = AsyncMock(return_value="")
    locator_mock = MagicMock()
    locator_mock.first.is_visible = AsyncMock(return_value=True)
    page.locator = MagicMock(return_value=locator_mock)

    blocker = await detect_blocker(page)
    assert blocker == {"blocker_type": "captcha", "description": "Captcha challenge on https://example.com/apply"}


@pytest.mark.asyncio
async def test_detect_blocker_recognizes_login_wall_text():
    from job_workflow import detect_blocker

    page = AsyncMock()
    page.url = "https://naukri.com/jobs/123"
    page.inner_text = AsyncMock(return_value="Please log in to view this job posting")
    locator_mock = MagicMock()
    locator_mock.first.is_visible = AsyncMock(return_value=False)
    page.locator = MagicMock(return_value=locator_mock)

    blocker = await detect_blocker(page)
    assert blocker == {"blocker_type": "login_wall", "description": "Login wall on https://naukri.com/jobs/123"}


@pytest.mark.asyncio
async def test_detect_blocker_returns_none_when_page_is_clean():
    from job_workflow import detect_blocker

    page = AsyncMock()
    page.url = "https://example.com/jobs/456"
    page.inner_text = AsyncMock(return_value="Senior Backend Engineer — apply below")
    locator_mock = MagicMock()
    locator_mock.first.is_visible = AsyncMock(return_value=False)
    page.locator = MagicMock(return_value=locator_mock)

    assert await detect_blocker(page) is None
```

(`MagicMock` is already imported at the top of `test_job_workflow.py` per line 4 — `from unittest.mock import MagicMock, patch`.)

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd browser-svc && python -m pytest tests/test_job_workflow.py -k detect_blocker -v`

Expected: FAIL — all three with `ImportError: cannot import name 'detect_blocker' from 'job_workflow'`.

- [ ] **Step 3: Implement `detect_blocker`**

In `browser-svc/job_workflow.py`, insert directly after `attach_cv` ends (after line 158, before the `# ── LinkedIn Easy Apply ──` comment on line 161):

```python
# ── Blocker detection ─────────────────────────────────────────────────────────

_CAPTCHA_SELECTORS = [
    "iframe[src*='recaptcha']",
    "iframe[title*='challenge']",
    "[class*='captcha']",
    "#captcha",
]
_CAPTCHA_TEXT_PATTERNS = [
    r"(?i)verify you('re| are) human",
    r"(?i)i'?m not a robot",
    r"(?i)complete the (security check|captcha)",
]
_LOGIN_WALL_SELECTORS = [
    "input[type='password']",
    "form[action*='login']",
    "form[action*='signin']",
]
_LOGIN_WALL_TEXT_PATTERNS = [
    r"(?i)sign in to continue",
    r"(?i)log ?in to (view|continue|apply)",
    r"(?i)please log ?in",
]


async def _any_visible(page: "Page", selectors: list[str]) -> bool:
    for selector in selectors:
        try:
            if await page.locator(selector).first.is_visible(timeout=500):
                return True
        except Exception:
            continue
    return False


def _any_match(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


async def detect_blocker(page: "Page") -> Optional[dict]:
    """Classify a blocking condition on the current page, if any.

    Returns {"blocker_type": "captcha"|"login_wall", "description": "..."} or
    None. Captcha is checked first — a captcha overlay can sit on top of what
    would otherwise look like a login form, and misclassifying it as a login
    wall would send a human toward the wrong remedy.
    """
    try:
        body_text = (await page.inner_text("body"))[:4000]
    except Exception:
        body_text = ""

    if await _any_visible(page, _CAPTCHA_SELECTORS) or _any_match(body_text, _CAPTCHA_TEXT_PATTERNS):
        return {"blocker_type": "captcha", "description": f"Captcha challenge on {page.url}"}

    if await _any_visible(page, _LOGIN_WALL_SELECTORS) or _any_match(body_text, _LOGIN_WALL_TEXT_PATTERNS):
        return {"blocker_type": "login_wall", "description": f"Login wall on {page.url}"}

    return None
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd browser-svc && python -m pytest tests/test_job_workflow.py -k detect_blocker -v`

Expected: PASS — all three tests green.

- [ ] **Step 5: Commit**

```bash
git add browser-svc/job_workflow.py browser-svc/tests/test_job_workflow.py
git commit -m "feat: classify captcha and login-wall blockers via detect_blocker(page)"
```

### Task 2: Add pause/resume primitives to `SlotInfo` and `SessionManager`

**Files:**
- Modify: `browser-svc/session_manager.py` (extend `SlotInfo`, `release`, `status`; add `mark_blocked`/`wait_for_resume`/`resume`)
- Test: `browser-svc/tests/test_session_manager.py` (append after the existing tests, using the existing `sm` fixture)

- [ ] **Step 1: Write the failing tests**

Append to `browser-svc/tests/test_session_manager.py`:

```python
@pytest.mark.asyncio
async def test_mark_blocked_sets_reason_and_clears_resume_event(sm):
    slot = await sm.acquire(0)
    slot.resume_event.set()
    await sm.mark_blocked(0, "Naukri is showing a login page")
    assert sm._slots[0].blocked_reason == "Naukri is showing a login page"
    assert not sm._slots[0].resume_event.is_set()


@pytest.mark.asyncio
async def test_resume_clears_reason_and_sets_event(sm):
    await sm.acquire(0)
    await sm.mark_blocked(0, "Captcha on LinkedIn")
    resumed = sm.resume(0)
    assert resumed is True
    assert sm._slots[0].blocked_reason == ""
    assert sm._slots[0].resume_event.is_set()


@pytest.mark.asyncio
async def test_resume_returns_false_when_slot_is_not_blocked(sm):
    await sm.acquire(0)
    assert sm.resume(0) is False


@pytest.mark.asyncio
async def test_status_reports_blocked_reason(sm):
    await sm.acquire(0)
    await sm.mark_blocked(0, "Login wall on naukri.com")
    statuses = sm.status()
    assert statuses[0]["blocked_reason"] == "Login wall on naukri.com"
    assert statuses[1]["blocked_reason"] == ""


@pytest.mark.asyncio
async def test_release_clears_blocked_state(sm):
    await sm.acquire(0)
    await sm.mark_blocked(0, "Captcha on LinkedIn")
    await sm.release(0)
    assert sm._slots[0].blocked_reason == ""
    assert sm._slots[0].resume_event.is_set() is False
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd browser-svc && python -m pytest tests/test_session_manager.py -k "blocked or resume" -v`

Expected: FAIL — `AttributeError: 'SlotInfo' object has no attribute 'blocked_reason'` (or `'SessionManager' object has no attribute 'mark_blocked'`/`'resume'`) across all five new tests.

- [ ] **Step 3: Extend `SlotInfo` with `blocked_reason` and `resume_event`**

In `browser-svc/session_manager.py`, change the `SlotInfo` dataclass (lines 16-23) from:

```python
@dataclass
class SlotInfo:
    slot_id: int
    state: SlotState = SlotState.IDLE
    url: str = ""
    action: str = ""
    context: Optional[BrowserContext] = field(default=None, repr=False)
    page: Optional[Page] = field(default=None, repr=False)
    cdp_session: Optional[object] = field(default=None, repr=False)
```

to:

```python
@dataclass
class SlotInfo:
    slot_id: int
    state: SlotState = SlotState.IDLE
    url: str = ""
    action: str = ""
    blocked_reason: str = ""
    context: Optional[BrowserContext] = field(default=None, repr=False)
    page: Optional[Page] = field(default=None, repr=False)
    cdp_session: Optional[object] = field(default=None, repr=False)
    resume_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
```

- [ ] **Step 4: Reset blocked state on release, report it in `status`, and add `mark_blocked`/`wait_for_resume`/`resume`**

Change `release` (lines 86-91) from:

```python
    async def release(self, slot_id: int):
        async with self._lock:
            slot = self._slots[slot_id]
            slot.state = SlotState.IDLE
            slot.url = ""
            slot.action = ""
```

to:

```python
    async def release(self, slot_id: int):
        async with self._lock:
            slot = self._slots[slot_id]
            slot.state = SlotState.IDLE
            slot.url = ""
            slot.action = ""
            slot.blocked_reason = ""
            slot.resume_event.clear()
```

Change `status` (lines 93-97) from:

```python
    def status(self) -> list[dict]:
        return [
            {"slot_id": s.slot_id, "state": s.state.value, "url": s.url, "action": s.action}
            for s in self._slots
        ]
```

to:

```python
    def status(self) -> list[dict]:
        return [
            {
                "slot_id": s.slot_id,
                "state": s.state.value,
                "url": s.url,
                "action": s.action,
                "blocked_reason": s.blocked_reason,
            }
            for s in self._slots
        ]
```

Then, directly after `find_free_slot` ends (after line 101, before the `# ── ` screencast section comment on line 103), add:

```python
    async def mark_blocked(self, slot_id: int, reason: str) -> None:
        async with self._lock:
            slot = self._slots[slot_id]
            slot.blocked_reason = reason
            slot.resume_event.clear()

    async def wait_for_resume(self, slot_id: int) -> None:
        await self._slots[slot_id].resume_event.wait()

    def resume(self, slot_id: int) -> bool:
        slot = self._slots[slot_id]
        if not slot.blocked_reason:
            return False
        slot.blocked_reason = ""
        slot.resume_event.set()
        return True
```

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `cd browser-svc && python -m pytest tests/test_session_manager.py -v`

Expected: PASS — every test in the file green, including the five new ones.

- [ ] **Step 6: Commit**

```bash
git add browser-svc/session_manager.py browser-svc/tests/test_session_manager.py
git commit -m "feat: add pause/resume primitives (blocked_reason, resume_event, mark_blocked/wait_for_resume/resume) to SlotInfo and SessionManager"
```

### Task 3: Wire detection + escalation into `apply_to_job` via `pause_for_input`

This is the spec's **Escalation** sequence in code: "(1) Switch the slot to interactive mode via `ensure_interactive()`, (2) Dashboard tile shows 'awaiting input' with a short blocker description, (3) Send a notification with a 'Take over' prompt." `pause_for_input` performs all three, then blocks on `wait_for_resume` until the human acts — and on the way out, fires the `browser_blocker_resolved` event that Task 5 turns into a learning-loop memory.

**Files:**
- Modify: `browser-svc/job_workflow.py` (add `from datetime import datetime` import; add `pause_for_input` after `detect_blocker`; wire it into `apply_to_job`)
- Modify: `browser-svc/main.py` (`_apply_on_slot` passes `relay=relay` through to `apply_to_job`)
- Test: `browser-svc/tests/test_job_workflow.py`

- [ ] **Step 1: Write the failing test for `pause_for_input`**

Append to `browser-svc/tests/test_job_workflow.py`:

```python
@pytest.mark.asyncio
async def test_pause_for_input_escalates_then_resolves(monkeypatch):
    from job_workflow import pause_for_input
    import session_manager as sm_module
    from session_manager import SlotInfo

    slot = SlotInfo(slot_id=2)
    slot.resume_event.set()  # pre-set so wait_for_resume returns immediately

    mock_sm = AsyncMock()
    mock_sm.mark_blocked = AsyncMock()
    mock_sm.ensure_interactive = AsyncMock()
    mock_sm.wait_for_resume = AsyncMock()
    monkeypatch.setattr(sm_module, "session_manager", mock_sm)

    page = AsyncMock()
    page.url = "https://naukri.com/jobs/123"
    relay = MagicMock()

    blocker = {"blocker_type": "login_wall", "description": "Login wall on https://naukri.com/jobs/123"}
    await pause_for_input(page, slot, blocker, relay)

    mock_sm.mark_blocked.assert_called_once_with(2, "Login wall on https://naukri.com/jobs/123")
    mock_sm.ensure_interactive.assert_called_once_with(2, relay)
    mock_sm.wait_for_resume.assert_called_once_with(2)

    assert relay.push.call_count == 2
    blocked_call, resolved_call = relay.push.call_args_list
    assert blocked_call.args[0] == {
        "type": "browser_blocked",
        "slot_id": 2,
        "blocker_type": "login_wall",
        "description": "Login wall on https://naukri.com/jobs/123",
    }
    resolved_payload = resolved_call.args[0]
    assert resolved_payload["type"] == "browser_blocker_resolved"
    assert resolved_payload["agent_id"] == "maya"
    assert resolved_payload["site"] == "naukri.com"
    assert resolved_payload["blocker_type"] == "login_wall"
    assert resolved_payload["resolution"] == "user took over in interactive mode and resumed manually"
    assert "timestamp" in resolved_payload
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `cd browser-svc && python -m pytest tests/test_job_workflow.py::test_pause_for_input_escalates_then_resolves -v`

Expected: FAIL — `ImportError: cannot import name 'pause_for_input' from 'job_workflow'`.

- [ ] **Step 3: Add `from datetime import datetime` and implement `pause_for_input`**

In `browser-svc/job_workflow.py`, change the import block (lines 1-9) from:

```python
import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from urllib.parse import urlparse
```

to:

```python
import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from urllib.parse import urlparse
```

Then, directly after `detect_blocker` ends (the function added in Task 1, immediately before the `# ── LinkedIn Easy Apply ──` comment), add:

```python
async def pause_for_input(page: "Page", slot_info: "SlotInfo", blocker: dict, relay) -> None:
    """Escalate a detected blocker to a human, per the spec's escalation sequence:
    switch to interactive mode, mark the slot 'awaiting input' for the dashboard,
    notify the user with a Take-over prompt, then block until they signal resume.
    On the way out, report what happened so Task 5 can persist it for the
    learning loop — closing the spec's 'pause and classify... not blindly retry
    or silently fail' requirement end to end.
    """
    import session_manager as sm_module

    blocker_type = blocker["blocker_type"]
    description  = blocker["description"]
    logger.warning("Slot %d blocked (%s): %s", slot_info.slot_id, blocker_type, description)

    slot_info.action = f"Awaiting input — {description}"
    await sm_module.session_manager.mark_blocked(slot_info.slot_id, description)
    await sm_module.session_manager.ensure_interactive(slot_info.slot_id, relay)
    relay.push({
        "type": "browser_blocked",
        "slot_id": slot_info.slot_id,
        "blocker_type": blocker_type,
        "description": description,
    })

    await sm_module.session_manager.wait_for_resume(slot_info.slot_id)

    logger.info("Slot %d resumed by user — continuing on %s", slot_info.slot_id, page.url)
    slot_info.action = f"Resumed — continuing on {_guess_company(page.url)}"
    relay.push({
        "type": "browser_blocker_resolved",
        "agent_id": "maya",
        "site": urlparse(page.url).netloc,
        "blocker_type": blocker_type,
        "description": description,
        "resolution": "user took over in interactive mode and resumed manually",
        "timestamp": datetime.now().isoformat(),
    })
```

(Importing `session_manager` as a module inside the function — rather than `from session_manager import session_manager` at the top — matches the test's `monkeypatch.setattr(sm_module, "session_manager", mock_sm)` pattern and avoids a circular import: `session_manager.py` doesn't import `job_workflow`, but keeping the reference late and through the module object makes the singleton swappable in tests, exactly like `_apply_on_slot` already does with its `from job_workflow import apply_to_job` inside the function body.)

- [ ] **Step 4: Run the test and confirm it passes**

Run: `cd browser-svc && python -m pytest tests/test_job_workflow.py::test_pause_for_input_escalates_then_resolves -v`

Expected: PASS.

- [ ] **Step 5: Wire `detect_blocker`/`pause_for_input` into `apply_to_job`**

In `browser-svc/job_workflow.py`, change the `apply_to_job` signature and body (the version from the founding spec, currently spanning what is now lines ~239-276 after Task 3's import-block insertion) from:

```python
async def apply_to_job(
    page: "Page",
    url: str,
    cv_path: str,
    slot_info: Optional["SlotInfo"] = None,
    tailor_cv: bool = False,
) -> ApplyResult:
    try:
        profile = load_profile()
    except RuntimeError as exc:
        logger.error("Skipping %s — %s", url, exc)
        return ApplyResult(url=url, company=_guess_company(url), role="", status="skipped", error=str(exc))
    company = _guess_company(url)
    role = ""
    try:
        if slot_info:
            slot_info.url = url
            slot_info.action = "Fetching job description"
        jd = await fetch_job_description(page, url)
        try:
            role = await page.title() or "Role"
        except Exception:
            role = "Role"
```

to:

```python
async def apply_to_job(
    page: "Page",
    url: str,
    cv_path: str,
    slot_info: Optional["SlotInfo"] = None,
    tailor_cv: bool = False,
    relay=None,
) -> ApplyResult:
    try:
        profile = load_profile()
    except RuntimeError as exc:
        logger.error("Skipping %s — %s", url, exc)
        return ApplyResult(url=url, company=_guess_company(url), role="", status="skipped", error=str(exc))
    company = _guess_company(url)
    role = ""
    try:
        if slot_info:
            slot_info.url = url
            slot_info.action = "Fetching job description"
        jd = await fetch_job_description(page, url)

        if slot_info is not None and relay is not None:
            blocker = await detect_blocker(page)
            if blocker:
                await pause_for_input(page, slot_info, blocker, relay)
                # Continue from the now-unblocked page state — re-fetch rather than
                # restart, per the spec's "not a restart from scratch" requirement.
                jd = await fetch_job_description(page, url)

        try:
            role = await page.title() or "Role"
        except Exception:
            role = "Role"
```

- [ ] **Step 6: Pass `relay` through from `_apply_on_slot`**

In `browser-svc/main.py`, change `_apply_on_slot` (as it stands after Phase 2 Task 9 — including the `relay.push({"type": "browser_result", ...})` call at its end) from:

```python
async def _apply_on_slot(slot: SlotInfo, url: str, tailor_cv: bool):
    """Apply to a job URL using an already-acquired slot (caller handles acquire/release)."""
    from job_workflow import apply_to_job

    cv_path = str(CV_DEFAULT_PATH)
    result = await apply_to_job(
        slot.page, url, cv_path,
        slot_info=slot, tailor_cv=tailor_cv,
    )
    logger.info("Apply result: %s %s → %s", result.company, result.role, result.status)
```

to:

```python
async def _apply_on_slot(slot: SlotInfo, url: str, tailor_cv: bool):
    """Apply to a job URL using an already-acquired slot (caller handles acquire/release)."""
    from job_workflow import apply_to_job

    cv_path = str(CV_DEFAULT_PATH)
    result = await apply_to_job(
        slot.page, url, cv_path,
        slot_info=slot, tailor_cv=tailor_cv, relay=relay,
    )
    logger.info("Apply result: %s %s → %s", result.company, result.role, result.status)
```

(leave the trailing `relay.push({"type": "browser_result", ...})` block from Phase 2 Task 9 exactly as-is — only the `apply_to_job(...)` call gains the new `relay=relay` argument.)

- [ ] **Step 7: Run the full browser-svc suite and confirm everything passes**

Run: `cd browser-svc && python -m pytest -v`

Expected: PASS — every test in `browser-svc/tests/` green, including all of Tasks 1-3's new tests and the existing apply/discover/session-manager suites (the new `relay` parameter defaults to `None`, so any test that calls `apply_to_job` without it is unaffected).

- [ ] **Step 8: Commit**

```bash
git add browser-svc/job_workflow.py browser-svc/main.py browser-svc/tests/test_job_workflow.py
git commit -m "feat: detect captcha/login-wall blockers during apply and escalate to a human via pause_for_input, continuing from the unblocked page state on resume"
```

### Task 4: Add a `POST /slots/{id}/resume` endpoint — the hand-back signal

This is the **"the user signals 'resume'... via the dashboard"** half of the spec's hand-back requirement — the backend counterpart to the frontend "Resume" button added in Task 6. It does one thing: flip the slot's `resume_event`, which `pause_for_input` (Task 3) is blocked on inside `apply_to_job`'s coroutine.

**Files:**
- Modify: `browser-svc/main.py` (add `slot_resume` directly after `slot_ensure_interactive`, the endpoint Phase 3 Task 3 added after `slot_back`)
- Test: `browser-svc/tests/test_main.py`

- [ ] **Step 1: Write the failing tests**

Append to `browser-svc/tests/test_main.py`:

```python
def test_resume_signals_a_blocked_slot(client):
    import main as m
    with patch.object(m.session_manager, "resume", return_value=True) as mock_resume:
        r = client.post("/slots/2/resume")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    mock_resume.assert_called_once_with(2)


def test_resume_rejects_a_slot_that_is_not_blocked(client):
    import main as m
    with patch.object(m.session_manager, "resume", return_value=False):
        r = client.post("/slots/2/resume")
    assert r.status_code == 409


def test_resume_rejects_out_of_range_slot(client):
    r = client.post("/slots/9/resume")
    assert r.status_code == 400
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd browser-svc && python -m pytest tests/test_main.py -k test_resume -v`

Expected: FAIL — all three get `404 Not Found` (no such route), so `assert r.status_code == 200`/`409`/`400` each fail with `assert 404 == ...`.

- [ ] **Step 3: Add the endpoint**

In `browser-svc/main.py`, add this directly after `slot_ensure_interactive` (the endpoint Phase 3 Task 3 placed after `slot_back`):

```python
@app.post("/slots/{slot_id}/resume")
async def slot_resume(slot_id: int):
    if slot_id < 0 or slot_id >= session_manager.NUM_SLOTS:
        raise HTTPException(400, f"slot_id must be 0–{session_manager.NUM_SLOTS - 1}")
    if not session_manager.resume(slot_id):
        raise HTTPException(409, f"Slot {slot_id} is not currently awaiting input")
    return {"ok": True}
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd browser-svc && python -m pytest tests/test_main.py -v`

Expected: PASS — `test_resume_signals_a_blocked_slot`, `test_resume_rejects_a_slot_that_is_not_blocked`, `test_resume_rejects_out_of_range_slot`, and every other test in the file green.

- [ ] **Step 5: Commit**

```bash
git add browser-svc/main.py browser-svc/tests/test_main.py
git commit -m "feat: add /slots/{id}/resume endpoint as the hand-back signal for paused workflows"
```

### Task 5: Persist resolved blockers as structured memories — the learning loop

This is the spec's **Learning loop**: *"persist structured blocker entries — `{site, blocker_type, resolution, timestamp}` — to `memory.py`, tagged for retrieval scoped per-agent and per-site via `get_relevant_memories()`."* `handle_browser_blocker_resolved` mirrors `handle_browser_result` (Phase 2 Task 8) — both are NEXUS-side handlers for events that only NEXUS can act on (re-invoking an agent; writing to a database `browser-svc` cannot reach). As Design Decision 4 explains, no separate "query before starting" code is needed — `_build_context_block` already retrieves relevant memories on every turn.

**Files:**
- Modify: `app/api/websocket.py` (add `from app.services import memory as mem_svc` to the import block; add `handle_browser_blocker_resolved` after `handle_browser_result`)
- Modify: `app/main.py:99` (extend the `browser_result` branch with an `elif` for `browser_blocker_resolved`)
- Test: `tests/test_websocket.py` (append; the file and its `pytest`/`AsyncMock`/`patch` imports already exist from Phase 2 Task 8)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_websocket.py`:

```python
@pytest.mark.asyncio
async def test_handle_browser_blocker_resolved_persists_a_retrievable_memory(tmp_path):
    from app.api import websocket as ws_module
    from app.services import memory as mem_svc

    original_db = mem_svc.DB_PATH
    mem_svc.DB_PATH = tmp_path / "test_memory.db"
    mem_svc.init_db()
    try:
        await ws_module.handle_browser_blocker_resolved({
            "type": "browser_blocker_resolved",
            "agent_id": "maya",
            "site": "naukri.com",
            "blocker_type": "login_wall",
            "resolution": "user took over in interactive mode and resumed manually",
            "timestamp": "2026-06-08T10:00:00",
        })
        results = mem_svc.get_relevant_memories("maya", "naukri.com login wall")
        assert any("naukri.com" in r and "login_wall" in r for r in results)
    finally:
        mem_svc.DB_PATH = original_db
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `cd /mnt/HC_Volume_105874680/virtual-company && python -m pytest tests/test_websocket.py::test_handle_browser_blocker_resolved_persists_a_retrievable_memory -v`

Expected: FAIL — `AttributeError: <module 'app.api.websocket' ...> does not have the attribute 'handle_browser_blocker_resolved'`.

- [ ] **Step 3: Import `mem_svc` and add `handle_browser_blocker_resolved`**

In `app/api/websocket.py`, change the import block (the lines that currently read, per lines 33-39):

```python
from app.agents import backend_state
from app.agents import definitions as defs
from app.agents.executor import run_agent
from app.services import delegation as deleg_svc
from app.services import email as email_svc
from app.state import manager as state
from app.skills import skill_loader
```

to:

```python
from app.agents import backend_state
from app.agents import definitions as defs
from app.agents.executor import run_agent
from app.services import delegation as deleg_svc
from app.services import email as email_svc
from app.services import memory as mem_svc
from app.state import manager as state
from app.skills import skill_loader
```

Then add this directly after `handle_browser_result` ends (the function Phase 2 Task 8 added after `_run_worker_bg`):

```python
async def handle_browser_blocker_resolved(data: dict) -> None:
    """Persist a resolved automation blocker as a structured memory, closing the
    spec's learning loop. No separate retrieval path is needed: _build_context_block
    (executor.py:138-141) already calls get_relevant_memories(agent_id, user_query)
    on every turn, so once this content names the site, it surfaces in Maya's live
    context the next time the user asks her to work on that site — satisfying
    "Maya proactively queries memory and adapts or warns up front" via the existing
    context-injection pipeline rather than a second, redundant lookup."""
    agent_id     = data.get("agent_id", "maya")
    site         = data.get("site", "")
    blocker_type = data.get("blocker_type", "")
    resolution   = data.get("resolution", "")
    timestamp    = data.get("timestamp", "")
    content = f"Blocker on {site}: {blocker_type} — {resolution} (at {timestamp})"
    mem_svc.save_memory(agent_id, content, mem_type="browser_blocker", importance=0.6)
```

- [ ] **Step 4: Branch on `browser_blocker_resolved` in `browser_relay_endpoint`**

In `app/main.py:99`, change the branch Phase 2 Task 8 added:

```python
            if data.get("type") == "browser_result":
                asyncio.create_task(ws_module.handle_browser_result(data))
            else:
                await broadcast_event(data)
```

to:

```python
            if data.get("type") == "browser_result":
                asyncio.create_task(ws_module.handle_browser_result(data))
            elif data.get("type") == "browser_blocker_resolved":
                asyncio.create_task(ws_module.handle_browser_blocker_resolved(data))
            else:
                await broadcast_event(data)
```

- [ ] **Step 5: Run the test and confirm it passes**

Run: `cd /mnt/HC_Volume_105874680/virtual-company && python -m pytest tests/test_websocket.py -v`

Expected: PASS — `test_handle_browser_blocker_resolved_persists_a_retrievable_memory` green alongside `test_handle_browser_result_records_and_reinvokes_agent` from Phase 2. The new test also exercises `get_relevant_memories` end-to-end with the punctuated site name `"naukri.com"`, confirming Phase 1 Task 4's FTS5 escaping fix covers this learning-loop path too — directly satisfying the spec's Section 3 testing requirement: *"Confirm a blocker entry is written to memory.py and that a subsequent run on the same site retrieves it via get_relevant_memories without throwing an FTS5 syntax error."*

- [ ] **Step 6: Commit**

```bash
git add app/api/websocket.py app/main.py tests/test_websocket.py
git commit -m "feat: persist resolved automation blockers as structured memories, closing the learning loop"
```

### Task 6: Frontend — "awaiting input" chip, Resume button, and Take-over notification

Completes the dashboard side of the handoff: the chip (Phase 3 Task 2) gains the `awaiting input` branch that Phase 3's Design Decision 4 explicitly deferred to "once Phase 4 defines the actual escalation signal" — that signal is now the polled `blocked_reason` field (Task 2). A "Resume" button lets the human hand control back, and a `browser_blocked` notification (forwarded generically per Design Decision 3) tells them something needs attention in the first place.

**Files:**
- Modify: `app/static/app-v5.js` (tile markup + `_boardTiles` shape inside `initBrowserBoard`; `_computeSlotChip`; `pollBoardSlotStatuses`; the WS message switch)
- Test: none — vanilla JS, no test harness (see Phase 3 Task 1). Verified by manual browser check in Step 4.

- [ ] **Step 1: Add a `bresume-${i}` button to each tile and track it in `_boardTiles`**

In `app/static/app-v5.js`, inside `initBrowserBoard`, change the `tile.innerHTML` assignment (as it stands after Phase 3 Task 3 added the "Take over" button) from:

```javascript
    tile.innerHTML =
      `<img id="bframe-${i}" src="" style="width:100%;height:100%;object-fit:fill;display:none">` +
      `<div id="bidle-${i}" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:4px">` +
        `<span style="color:var(--muted);font-size:11px">${_SLOT_LABELS[i]}</span>` +
        `<span style="color:var(--border);font-size:9px">idle</span>` +
      `</div>` +
      `<div id="bchip-${i}" style="position:absolute;top:4px;left:4px;padding:1px 6px;border-radius:3px;font-size:8px;font-weight:700;background:rgba(255,255,255,0.08);color:var(--muted)">idle</div>` +
      `<div id="bstatus-${i}" style="position:absolute;bottom:0;left:0;right:0;padding:3px 6px;background:rgba(0,0,0,0.75);font-size:9px;color:#00d4ff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:none"></div>` +
      `<div id="bbadge-${i}" style="position:absolute;top:4px;right:4px;padding:1px 5px;border-radius:3px;font-size:8px;font-weight:700;background:rgba(0,255,128,0.15);color:#0f0;display:none">LIVE</div>` +
      `<button id="btakeover-${i}" style="position:absolute;bottom:4px;right:4px;padding:2px 8px;font-size:8px;font-weight:700;border-radius:3px;border:1px solid #00d4ff;background:rgba(0,212,255,0.12);color:#00d4ff;cursor:pointer;z-index:2">Take over</button>`;
```

to:

```javascript
    tile.innerHTML =
      `<img id="bframe-${i}" src="" style="width:100%;height:100%;object-fit:fill;display:none">` +
      `<div id="bidle-${i}" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:4px">` +
        `<span style="color:var(--muted);font-size:11px">${_SLOT_LABELS[i]}</span>` +
        `<span style="color:var(--border);font-size:9px">idle</span>` +
      `</div>` +
      `<div id="bchip-${i}" style="position:absolute;top:4px;left:4px;padding:1px 6px;border-radius:3px;font-size:8px;font-weight:700;background:rgba(255,255,255,0.08);color:var(--muted)">idle</div>` +
      `<div id="bstatus-${i}" style="position:absolute;bottom:0;left:0;right:0;padding:3px 6px;background:rgba(0,0,0,0.75);font-size:9px;color:#00d4ff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:none"></div>` +
      `<div id="bbadge-${i}" style="position:absolute;top:4px;right:4px;padding:1px 5px;border-radius:3px;font-size:8px;font-weight:700;background:rgba(0,255,128,0.15);color:#0f0;display:none">LIVE</div>` +
      `<button id="bresume-${i}" style="position:absolute;bottom:4px;left:4px;padding:2px 8px;font-size:8px;font-weight:700;border-radius:3px;border:1px solid #ff66cc;background:rgba(255,102,204,0.12);color:#ff66cc;cursor:pointer;z-index:2;display:none">Resume</button>` +
      `<button id="btakeover-${i}" style="position:absolute;bottom:4px;right:4px;padding:2px 8px;font-size:8px;font-weight:700;border-radius:3px;border:1px solid #00d4ff;background:rgba(0,212,255,0.12);color:#00d4ff;cursor:pointer;z-index:2">Take over</button>`;
```

Then change the `_boardTiles[i] = {...}` assignment from:

```javascript
    _boardTiles[i] = {
      img: document.getElementById(`bframe-${i}`),
      idle: document.getElementById(`bidle-${i}`),
      status: document.getElementById(`bstatus-${i}`),
      badge: document.getElementById(`bbadge-${i}`),
      chip: document.getElementById(`bchip-${i}`),
      lastFrameAt: null,
    };
```

to:

```javascript
    _boardTiles[i] = {
      img: document.getElementById(`bframe-${i}`),
      idle: document.getElementById(`bidle-${i}`),
      status: document.getElementById(`bstatus-${i}`),
      badge: document.getElementById(`bbadge-${i}`),
      chip: document.getElementById(`bchip-${i}`),
      resumeBtn: document.getElementById(`bresume-${i}`),
      lastFrameAt: null,
    };
```

Finally, in the same loop body, directly after the `takeoverBtn` click-handler block Phase 3 Task 3 added (and before `grid.appendChild(tile);`), add:

```javascript
    const resumeBtn = tile.querySelector(`#bresume-${i}`);
    if (resumeBtn) {
      resumeBtn.addEventListener("click", e => {
        e.stopPropagation();
        fetch(`/api/browser-svc/slots/${i}/resume`, { method: "POST" });
      });
    }
```

- [ ] **Step 2: Teach `_computeSlotChip` the `awaiting input` state and show/hide the Resume button from polling**

In `app/static/app-v5.js`, change `_computeSlotChip` (added in Phase 3 Task 2) from:

```javascript
function _computeSlotChip(backendState, lastFrameAt) {
  const ageMs = lastFrameAt != null ? Date.now() - lastFrameAt : null;
  if (backendState === "error") return { text: "error", color: "#ff4444" };
  if (backendState === "idle")  return { text: "idle",  color: "var(--muted)" };
  if (ageMs == null || ageMs > 5000) {
    return { text: `connecting · ${_formatFrameAge(ageMs)}`, color: "#ffaa00" };
  }
  return { text: `streaming · ${_formatFrameAge(ageMs)}`, color: "#00ff88" };
}
```

to:

```javascript
function _computeSlotChip(backendState, lastFrameAt, blockedReason) {
  const ageMs = lastFrameAt != null ? Date.now() - lastFrameAt : null;
  if (blockedReason) {
    const short = blockedReason.length > 36 ? blockedReason.slice(0, 36) + "…" : blockedReason;
    return { text: `awaiting input · ${short}`, color: "#ff66cc" };
  }
  if (backendState === "error") return { text: "error", color: "#ff4444" };
  if (backendState === "idle")  return { text: "idle",  color: "var(--muted)" };
  if (ageMs == null || ageMs > 5000) {
    return { text: `connecting · ${_formatFrameAge(ageMs)}`, color: "#ffaa00" };
  }
  return { text: `streaming · ${_formatFrameAge(ageMs)}`, color: "#00ff88" };
}
```

Then change `pollBoardSlotStatuses` (added in Phase 3 Task 2) from:

```javascript
async function pollBoardSlotStatuses() {
  let slots;
  try {
    const r = await fetch("/api/browser-svc/slots");
    if (!r.ok) return;
    slots = await r.json();
  } catch (e) {
    return; // browser-svc unreachable this tick — chips simply hold their last value
  }
  for (const s of slots) {
    const tile = _boardTiles[s.slot_id];
    if (!tile || !tile.chip) continue;
    const label = _computeSlotChip(s.state, tile.lastFrameAt);
    tile.chip.textContent = label.text;
    tile.chip.style.color = label.color;
  }
}
```

to:

```javascript
async function pollBoardSlotStatuses() {
  let slots;
  try {
    const r = await fetch("/api/browser-svc/slots");
    if (!r.ok) return;
    slots = await r.json();
  } catch (e) {
    return; // browser-svc unreachable this tick — chips simply hold their last value
  }
  for (const s of slots) {
    const tile = _boardTiles[s.slot_id];
    if (!tile || !tile.chip) continue;
    const label = _computeSlotChip(s.state, tile.lastFrameAt, s.blocked_reason);
    tile.chip.textContent = label.text;
    tile.chip.style.color = label.color;
    if (tile.resumeBtn) {
      tile.resumeBtn.style.display = s.blocked_reason ? "block" : "none";
    }
  }
}
```

- [ ] **Step 3: Add a `browser_blocked` notification to the WS message switch**

In `app/static/app-v5.js`, inside the WS `onmessage` switch, change the `case "apply_result":` block (added in Phase 2 Task 8) from:

```javascript
    case "apply_result":
      logApplyResult(obj);
      break;
```

to:

```javascript
    case "apply_result":
      logApplyResult(obj);
      break;

    case "browser_blocked":
      pushNotif(`🧑‍💻 Slot ${obj.slot_id} needs you — ${obj.description || obj.blocker_type}`, "warn");
      appendMsg("maya", "assistant",
        `⚠️ I'm stuck on slot ${obj.slot_id} — ${obj.description}\n\n` +
        `Open the Browser Board, click **Take over**, resolve it, then click **Resume** so I can continue from where I left off.`
      );
      break;
```

(This relies on Phase 2 Task 8's existing `else: await broadcast_event(data)` fallback in `browser_relay_endpoint` to forward the `browser_blocked` event — no NEXUS-side Python handler is needed, per Design Decision 3.)

- [ ] **Step 4: Manually verify the full handoff loop end to end**

Open the dashboard, open the Browser Board, and either point Maya at a known captcha/login-wall page (e.g., a Naukri job listing without `NAUKRI_EMAIL`/`NAUKRI_PASSWORD` configured — `_login_naukri` will be skipped and the listing's login wall will trigger `detect_blocker`) or temporarily lower a `_CAPTCHA_TEXT_PATTERNS`/`_LOGIN_WALL_TEXT_PATTERNS` match against a controlled test page. Confirm, in order:

1. A `🧑‍💻 Slot N needs you — ...` notification appears (top-right notification island) and a matching message from Maya appears in chat
2. The slot's tile chip changes to `awaiting input · Login wall on https://...` (pink) within ~3s (one polling tick)
3. The tile's screencast becomes live/interactive (►`ensure_interactive` started it) — clicking the tile sends real clicks to the page (the existing click-coordinate-math handler from Phase 3 Task 1)
4. A "Resume" button appears at the tile's bottom-left
5. After manually resolving the blocker (e.g., logging in) and clicking "Resume": the button disappears, the chip returns to `streaming · Ns ago`, and `apply_to_job` continues — visible as the `action` status line changing to `"Resumed — continuing on <Company>"` and then through its normal apply flow (not a restart from the discovery step)
6. `docker logs` for browser-svc shows `Slot N resumed by user — continuing on https://...` (the `logger.info` from `pause_for_input`)

- [ ] **Step 5: Commit**

```bash
git add app/static/app-v5.js
git commit -m "feat: add awaiting-input chip state, Resume button, and Take-over notification to the Browser Board"
```

### Task 7: Document the clean pattern for adding future workers (spec Section 5)

Per the spec's own Testing section: *"Section 5: no new code to test directly — validated by Section 1 working as a generic mechanism (i.e., it doesn't need to know 'browser' by name to function)."* This task therefore produces a reference document, not code — a concrete, copy-pasteable checklist populated with pointers into the exact files and functions this redesign built, so the next worker after Maya has a map instead of a suggestion to "follow the pattern."

**Files:**
- Create: `docs/superpowers/patterns/adding-a-new-worker.md`

- [ ] **Step 1: Write the pattern document**

Create `docs/superpowers/patterns/adding-a-new-worker.md` with this content:

```markdown
# Pattern: Adding a New Worker With Real-World Side Effects

Maya (the browser-automation worker) is the reference implementation of this
pattern, established by `docs/superpowers/specs/2026-06-07-browser-automation-cohesive-redesign-design.md`
and built out across `docs/superpowers/plans/2026-06-07-browser-automation-cohesive-redesign-plan.md`.
Copy this checklist directly when adding the next one.

## 1. Define the persona and tool tags

Add the worker's persona and its `[TOOL_TAG:...]` syntax to `app/agents/definitions.py`,
following Maya's `BROWSER_DISCOVER` / `BROWSER_APPLY` / `BROWSER_COMPANY` /
`BROWSER_PROFILE_MATCH` tags as the template. Keep the tag vocabulary small and
the argument grammar simple — Maya's `parse_browser_discover_args` (`app/agents/tools.py`,
added in Phase 2 Task 1) shows the shape: a single regex capturing one
comma-or-keyword-separated argument blob, parsed into a typed dict by one small
helper function that the registry handler can call without duplicating the regex.

## 2. Register each tag as an output-pipeline handler — NOT a per-backend special case

This is **the** integration point (spec Section 1 / this plan's Phase 2). Add one
handler module per tag under `app/output/handlers/` (see `browser_apply.py`,
`browser_discover.py`, `browser_company.py`, `browser_profile_match.py` from
Phase 2 Tasks 2-5) and register them in `app/output/registry.py`'s `get_registry()`
(Phase 2 Task 6).

Why this matters — and why it's the *whole point* of this redesign: `pipeline.process()`
runs on **every** backend's full response text (`executor.py:359` for `run_tgpt_agent`,
`executor.py:446` for `run_claude_agent`/`run_gemini_agent`). A handler registered here
fires identically no matter which backend produced the text. There is **never** a
reason to write `if agent_id == "maya": ...` anywhere in `executor.py` — if you find
yourself doing that, the tag belongs in the registry instead.

Each handler should, in order (mirroring `browser_apply.py` / Phase 2 Task 2):
1. Parse its arguments by delegating to a small helper (don't duplicate regexes).
2. Pick a resource via the service's existing allocator (Maya: `find_free_slot()`,
   `browser-svc/session_manager.py:99-101` — wired up in Phase 1 Task 3 after being
   dead code; check whether your sidecar already has an analogous allocator before
   writing a new one).
3. Fire the side-effecting call as `asyncio.create_task(...)` — fire-and-forget,
   because real-world actions are slow and must never block the chat turn
   (Phase 2's Design Decision: the immediate status line cannot know which
   resource will be allocated, so it omits that detail; the async result message
   reports the real, authoritative outcome instead of a guess).
4. Replace the tag in the displayed text with a clean status line and let the
   pipeline emit whatever frontend event makes the UI reflect that something
   real just started.

## 3. If the worker needs a sidecar service, follow `browser-svc`'s shape

- A FastAPI app with a `lifespan` that starts/stops the underlying resource pool
  (`browser-svc/main.py:17-25` — `session_manager.start()`/`relay.start()`)
- Background-task endpoints using `BackgroundTasks.add_task` so HTTP responses
  return immediately while the real work runs after (`browser-svc/main.py:117-124`)
- A `/status`-style introspection endpoint so the dashboard and other code can
  poll real state independent of any push channel (`GET /slots`,
  `browser-svc/main.py:35-37`, backed by `SessionManager.status()` —
  this is exactly the "structural backup signal... independent of the frame
  stream" the Phase 3 dashboard redesign relies on)
- An optional relay (`browser-svc/relay_client.py`) for live state — note its
  `_run()` loop already implements auto-reconnect with backoff
  (`while True` + `try/except` + `sleep(3)`); copy that shape rather than
  writing a bespoke reconnect loop, and remember to call `logging.basicConfig(...)`
  (Phase 1 Task 5) or your reconnect attempts will be invisible in `docker logs`
  exactly like Maya's were.

## 4. Close the loop: completion → re-invocation, not narration

Long-running or async actions must report their real outcome back to the worker,
or the worker will hallucinate plausible-sounding narration about its own
unconfirmed prior claims — this was Maya's root-cause bug (spec "Root cause"
section; `app/api/websocket.py`'s `handle_browser_result`, Phase 2 Task 8).

The shape to copy:
1. The sidecar pushes a structured result event over its relay channel
   (`relay.push({"type": "<worker>_result", "agent_id": ..., ...})`, mirroring
   `browser-svc/main.py`'s `_apply_on_slot`, Phase 2 Task 9).
2. NEXUS branches on that `type` inside the relay's WebSocket endpoint
   (`app/main.py`'s `browser_relay_endpoint`, the `if/elif/else` chain built up
   across Phase 2 Task 8 and Phase 4 Task 5) and dispatches to a handler.
3. The handler mirrors `_run_worker_bg`'s `record → run_agent → record` sequence
   (`app/api/websocket.py:127-129` / `handle_browser_result`): record the result
   as a `user` turn, re-invoke the worker via `run_agent`, record its grounded
   reply as an `assistant` turn, broadcast `thinking`/`done` so the dashboard
   reflects the re-invocation.

## 5. If the worker should learn from past attempts, persist tagged memories

Use `app.services.memory.save_memory(agent_id, content, mem_type=..., importance=...)`
with a `mem_type` specific to the kind of structured event you're recording —
e.g. Maya's `"browser_blocker"` (`handle_browser_blocker_resolved`, Phase 4 Task 5)
for `{site, blocker_type, resolution, timestamp}` entries.

**Do not** also write a bespoke "check memory before starting" code path. Every
agent turn already runs through `_build_context_block` (`app/agents/executor.py:138-141`),
which calls `get_relevant_memories(agent_id, user_query, limit=5)` and injects the
results into the prompt as "Relevant memories" — automatically, on every turn, for
every agent. As long as your `content` string names the thing a future query would
mention (a site, a company, a tool name), it surfaces on its own. A second lookup
path would be pure duplication of a mechanism that already runs unconditionally.

One prerequisite worth checking before you rely on this: free-text queries are
quoted before being passed to FTS5's `MATCH` (`app/services/memory.py:76`,
fixed in Phase 1 Task 4 — `'"' + query.replace('"', '""') + '"'`). If you're
extending `memory.py` itself, preserve that quoting; punctuated content
(company names with apostrophes, domains with dots) is the norm, not the
exception, for structured worker memories.

## Anti-patterns to avoid (all observed in Maya's original, broken implementation)

- **Backend-specific tool wiring.** The original bug: `parse_tool_call`/`_execute_tool`
  was wired into `run_tgpt_agent` only — invisible to the `run_claude_agent`/
  `run_gemini_agent` paths the worker actually runs on ~99% of the time. The
  registry handler pattern (step 2) makes this structurally impossible to repeat.
- **Hardcoded resource IDs with no collision handling.** Maya's `ApplyRequest`/
  `DiscoverRequest`/etc. defaulted `slot_id: int = 1`, so two concurrent actions
  collided on the same slot (`409 Slot 1 is busy`) — even though `find_free_slot()`
  already existed to solve exactly this (Phase 1 Task 3 wired it up). Check for
  an existing allocator before introducing a new resource pool.
- **Narrating instead of grounding.** Without the completion → re-invocation loop
  (step 4), a worker has no `[Tool Output]` feedback and will produce plausible
  fabrications about its own results — exactly what produced Maya's fabricated
  `/api/task-history` summaries. Don't ship a worker that can act in the real
  world without a path for it to learn what actually happened.
```

- [ ] **Step 2: Verify the document renders and all referenced paths exist**

Run: `cd /mnt/HC_Volume_105874680/virtual-company && for f in app/agents/definitions.py app/agents/tools.py app/output/registry.py app/output/handlers/browser_apply.py browser-svc/session_manager.py browser-svc/main.py browser-svc/relay_client.py app/api/websocket.py app/main.py app/services/memory.py app/agents/executor.py; do test -f "$f" && echo "OK   $f" || echo "MISSING $f"; done`

Expected: every line printed as `OK   <path>` — confirming every file the document points the next implementer toward actually exists at the path named (the line-number references inside those files were fixed at the moment each was written across Phases 1-4, and may drift with future edits — but the *files* are real and the *functions/patterns* named are the ones this plan built).

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/patterns/adding-a-new-worker.md
git commit -m "docs: write the clean-pattern checklist for adding future workers, populated with concrete pointers into Maya's reference implementation"
```

---

## Self-Review

**1. Spec coverage** — every section of the spec maps to a concrete task:

| Spec section | Plan coverage |
|---|---|
| Root cause / "Relationship to existing specs" | Phase 1 preamble + Phase 2 preamble explain the architecture mismatch and how Section 1's registry approach resolves it; no separate task needed since it's diagnosis, not a requirement |
| Section 1 — Universal tag dispatch | Phase 2 Tasks 1-9 (parsing helper, four handler modules, registry registration, slot-default cleanup, async result-feedback loop both directions) |
| Section 2 — Live dashboard redesign | Phase 3 Tasks 1-3 (4-tile 2×2 grid, status chips + frame-recency, Take-over button + `ensure-interactive` endpoint) |
| Section 3 — Automation ↔ manual handoff & learning loop | Phase 4 Tasks 1-6 (detection, pause/resume primitives, escalation wiring, resume endpoint, learning-loop persistence, dashboard handoff UI) |
| Section 4 — Architectural cleanup (a) slot renumbering, (b) `find_free_slot()`, (c) FTS5 fix, (d) relay logger fix | All four items are Phase 1 Tasks 1-5 (slot pool 5→4, consistent validation, `_resolve_slot`/`find_free_slot` wiring, FTS5 escaping, relay logging config) |
| Section 5 — Clean pattern for future workers | Phase 4 Task 7 (reference-document checklist, per the spec's own "no new code to test directly" guidance) |
| Testing — Section 1 | Phase 2 Tasks 1-9 steps include the registry-fires / backend-agnostic / result-feedback assertions the spec calls for |
| Testing — Section 2 | Phase 3 Tasks 1-3 manual-verification steps cover 4-tile rendering, chip independence from frame arrival, staleness visibility, relay logger lines, and Take-over → interactive mode |
| Testing — Section 3 | Phase 4 Task 6 Step 4's end-to-end manual walkthrough covers pause/notify/awaiting-input/resume/continue-not-restart; Phase 4 Task 5's automated test covers the memory-write + FTS5-safe retrieval requirement directly |
| Testing — Section 4 | Phase 1's final checkpoint task runs the full suite confirming consistent slot validation, collision-free `find_free_slot`, and FTS5 safety |
| Testing — Section 5 | Phase 4 Task 7 — documentation-only, as the spec itself specifies no code to test |
| Out of scope (tgpt rewrite, `_classify_model` changes, captcha-solving, Overleaf/CV pipeline) | Respected throughout — Phase 2 explicitly preserves `run_tgpt_agent`'s existing loop as a second entry point rather than rewriting it; Phase 4's `detect_blocker`/`pause_for_input` *classify and escalate to a human*, never attempt to solve a captcha; no CV-tailoring-pipeline code is touched anywhere in this plan beyond the slot-removal already covered in Phase 1 |

No gaps found.

**2. Placeholder scan** — searched for "TBD", "TODO", "implement later", "fill in", "appropriate", "similar to Task", "handle edge cases" across all four phases: none found. Every step that changes code shows the actual code (full function bodies, full diffs with before/after blocks, exact file:line references). Every "Run" step names the exact command and the exact expected output/assertion/error message. The one place a future addition is *named* rather than written out — `_computeSlotChip`'s `awaiting input` branch in Phase 3 — is explicitly deferred with a stated reason (no backend signal exists yet) and then *delivered* in Phase 4 Task 6 Step 2, exactly as promised; it was never left as a dangling TODO.

**3. Type/name consistency** — cross-checked signatures and identifiers that span phase boundaries:
- `apply_to_job(page, url, cv_path, slot_info=None, tailor_cv=False, relay=None)` — Phase 4 Task 3 Step 5 extends the founding signature with `relay=None`, and Phase 4 Task 3 Step 6 updates `_apply_on_slot`'s call site to match (`relay=relay`) without disturbing Phase 2 Task 9's `relay.push({"type": "browser_result", ...})` addition that follows it
- `SlotInfo.blocked_reason` / `SlotInfo.resume_event` (Phase 4 Task 2) are referenced with identical names in `pause_for_input` (Task 3), `SessionManager.status()`'s output (Task 2 Step 4 / consumed in Task 6 Step 2 as `s.blocked_reason`), and the dashboard polling code (`tile.resumeBtn`, Task 6)
- `detect_blocker(page) -> Optional[dict]` returns `{"blocker_type": ..., "description": ...}` (Task 1) — and `pause_for_input` (Task 3) destructures exactly those two keys, no others
- `relay.push({"type": "browser_blocked", ...})` / `{"type": "browser_blocker_resolved", ...})` (Task 3) carry the exact field names that `app-v5.js`'s `case "browser_blocked"` (Task 6 Step 3) and `handle_browser_blocker_resolved` (Task 5) read (`slot_id`, `blocker_type`, `description`, `agent_id`, `site`, `resolution`, `timestamp`)
- `_computeSlotChip(backendState, lastFrameAt, blockedReason)` — Phase 4 Task 6 Step 2 extends the two-argument Phase 3 Task 2 signature with the third parameter, and updates its sole call site in `pollBoardSlotStatuses` to match
- `mem_svc.save_memory(agent_id, content, mem_type="browser_blocker", importance=0.6)` (Task 5) — `mem_svc` is the same import alias (`from app.services import memory as mem_svc`) already used in `executor.py`, kept consistent when adding it to `websocket.py`

No drift found between where an identifier is defined and where it's later consumed.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-07-browser-automation-cohesive-redesign-plan.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
