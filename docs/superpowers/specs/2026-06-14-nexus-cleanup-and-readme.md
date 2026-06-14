# NEXUS: Full Cleanup, Pipeline Fix & README Generation

**Date:** 2026-06-14  
**Scope:** Fix double-pipeline bug, remove dead code, wire standup, optimize UI selectors, write 7 READMEs.

---

## 1. Critical Bug Fix — Double `pipeline.process()`

### Problem
Every worker agent response runs `pipeline.process()` twice:
1. Inside `run_claude_agent()` / `run_gemini_agent()` / `run_tgpt_agent()` in `app/agents/runner.py` (lines 351, 438, 535)
2. Inside `output_node()` in `app/graph/nodes/output.py` (line 42)

Both use the same `broadcast.send` → SPEAK fires twice (voice double), EMAIL_USER sends email twice, BROWSER_* fires twice. Worker artifacts are also extracted twice (`workers/base.py:36` and `output_node:47`).

CEO path is unaffected (no `output_node` in CEO's graph path).

### Fix
- Remove `pipeline.process()` calls from `run_tgpt_agent`, `run_claude_agent`, `run_gemini_agent` — these functions return raw text only.
- `output_node` owns pipeline processing for the LangGraph worker path (already does it).
- `_run_direct()` in `websocket.py` (direct-chat path, bypasses LangGraph) must call `pipeline.process()` explicitly after `run_agent()` — capture the return value and process it.
- Remove duplicate artifact extraction from `worker_node` in `workers/base.py` — `output_node` handles it.

**Files changed:** `app/agents/runner.py`, `app/api/websocket.py`, `app/graph/workers/base.py`

---

## 2. Dead Code Removal

| Item | File | Action |
|---|---|---|
| `standup.py` | `app/services/standup.py` | Keep but wire to scheduler (see §3) |
| `browser_svc.py` | `app/services/browser_svc.py` | Delete — never imported, proxy route replaces it |
| `browser_frame` UI handler | `nexus-ui/src/store.ts:236-248` | Delete case from switch |
| `/api/workqueue` (4 routes) | `app/api/router.py:65-82` | Delete — return "replaced by LangGraph" errors |
| `/api/task-history` | `app/api/router.py:136-138` | Delete — returns `[]` |
| `/api/email-tasks/{task_id}` | `app/api/router.py:186-188` | Delete — returns 404 |
| `_ARTIFACT_RE` (×3) | `workers/base.py:15`, `nodes/output.py:14` | Keep one in `output.py`, import where needed |

---

## 3. Wire Standup to Scheduler

`app/services/standup.py` has `run_morning_standup()` fully implemented but never triggered.

**Fix:** In `app/services/scheduler.py`, add standup as a built-in routine or call it when a routine named `morning_standup` runs. Alternatively, seed a default routine record in the scheduler on startup. The cleanest approach: call `standup.run_morning_standup()` from the scheduler loop when a cron routine of type `standup` is detected.

**Files changed:** `app/services/scheduler.py` (add standup trigger), optionally seed `nexus_routines.json` with a default 9am weekday entry.

---

## 4. UI Selector Optimizations

### ReactorRing (`nexus-ui/src/components/ReactorRing.tsx`)
Currently subscribes to the entire `agents` map to count busy agents. Extract a selector:
```ts
const busyCount = useNexusStore(s =>
  Object.values(s.agents).filter(a => a.status === 'working' || a.status === 'thinking').length
)
```
This only re-renders when the busy count changes, not on every agent update.

### Background.tsx (`nexus-ui/src/components/Background.tsx`)
Currently subscribes to entire `agents` map just for CEO status. Extract:
```ts
const ceoStatus = useNexusStore(s => s.agents['ceo']?.status ?? 'idle')
```

### ReactorRing clock string
`new Date().toTimeString().slice(0, 5)` is computed at module evaluation time (render-body, line 40) — never updates. Wrap in `useFrame` or a `useState` with a 1-minute interval.

---

## 5. README Files (7 total)

Each README is written for Claude's future context — concise, technical, flow-oriented.

| File | Contents |
|---|---|
| `/README.md` | Project overview, architecture map, how to run/deploy, port registry |
| `app/graph/README.md` | LangGraph nodes, edges, state, how CEO→worker flow works, how to add a new agent to the graph |
| `app/agents/README.md` | Agent definitions, runner dispatch (Claude/Gemini/tgpt), how to add a new agent persona |
| `app/output/README.md` | Pipeline, registry, handlers, how to add a new `[TAG]` output handler |
| `app/services/README.md` | Each service (memory, email, scheduler, bark, browser, jira, self_heal, standup), configuration |
| `app/api/README.md` | All active routes (table), WebSocket protocol, all event types emitted, direct vs LangGraph paths |
| `nexus-ui/README.md` | Store structure, component map, WebSocket event↔UI mapping, 3D scene components |

---

## Implementation Order

1. Fix double pipeline (backend, highest impact, isolated changes)
2. Remove dead code (backend routes + frontend handler)
3. Wire standup to scheduler
4. Fix UI selectors + ReactorRing clock
5. Write 7 READMEs
6. Build frontend + run tests + commit
