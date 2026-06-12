# NEXUS Virtual Company — Full Gap Analysis: Features, Pipelines & UI

**Date:** 2026-06-12
**Scope:** Complete review of backend features vs UI reflection, pipeline health, and 3D immersion assessment.
**Verified against:** live container `virtual-company` (port 3031), git HEAD `1b322aa`, built bundle `index-CqjvjNr9.js` (current).

---

## 1. What works today (verified)

| Area | Status | Evidence |
|---|---|---|
| FastAPI app + LangGraph nexus graph (CEO → fan-out → review loop) | ✅ Up | `docker ps`, `/api/agents` responds |
| CEO task pipeline via WS (`thinking` → `delegation` → `worker_step` → `worker_checkpoint` → `worker_done` → `done`) | ✅ Wired both ends | `websocket.py:_translate_event` ↔ `store.ts` cases |
| 3D scene: arc-reactor CEO, icosahedron workers, neural edges, bloom, ⌘K palette, SmartIsland, HoverCard, OpsDrawer (routines/skills/approvals) | ✅ Built & deployed | bundle date == latest commit |
| Routines scheduler (cron, 30s tick, logs) + run-now from UI | ✅ | `scheduler.py`, OpsDrawer RUN button |
| Skills loader + localhost-gated register/rollback API | ✅ backend | `/api/skills` returns tools+learned |
| Self-heal write_source zones (immutable/surface/protected) + email approval gate | ✅ backend | `runner.py:964-1012` |
| Email graph (verify → plan → approve → execute → report → CF tunnel) + 30s poller | ✅ backend | `email/nodes.py`, poller running |
| Model routing Claude/Gemini/tgpt by task type + quota fallback | ✅ backend | `runner.py:_classify_model`, `run_agent` |
| Smart Claude/Gemini routing (your requested feedback) | ✅ implemented | `_classify_model` routes by length/signals |

## 2. Broken right now (pipeline health — fix first)

| # | Problem | Evidence | Impact |
|---|---|---|---|
| B1 | **bark-svc and browser-svc containers exited 32h ago** | `docker ps -a`; logs: `bark_client.speak failed: Temporary failure in name resolution` (repeating) | Voice/TTS pipeline dead; Maya's browser automation + live frames dead. No `restart:` policy in docker-compose.yml |
| B2 | **Memory recall fails on punctuation** | logs: `memory query failed: fts5: syntax error near ","` — escape regex `['"?*+()\[\].]` in `memory.py:70` misses `, - :` etc. | Agents silently lose long-term memory on most real queries |
| B3 | **SQLite `database is locked`** | logs 19:18, 19:44 | Memory writes dropped under concurrency; no WAL/busy_timeout |
| B4 | **Direct worker chat is broken** | `AgentDetailView` sends `{type:'message', agent:'backend', text}`; `websocket.py:ws_endpoint` ignores `agent` — everything runs the full CEO graph | Clicking Reinhard and typing to him actually messages Subaru. Regression from LangGraph transformation |
| B5 | **Chat panels empty on reload** | `/api/chat/{id}/history` exists; UI never fetches it | All conversation context invisible after refresh |

## 3. WS connectivity matrix (the core UI gap)

### Backend emits → UI deaf (event silently dropped)

| Event | Emitted from | What's lost in UI |
|---|---|---|
| `backend_status` | `runner.py:run_agent` (every model pick) | ModelPill stays stale — it only handles `backend_switch` (quota fallback), so the Claude/Gemini routing you built is invisible |
| `browser_navigated` | `runner.py` web tools | Maya's screenshots never shown |
| `browser_frame` / `browser_result` / `browser_blocker_resolved` | browser-svc → `/ws/browser-relay` → broadcast | Live CDP screencast (jpeg frames!) streams to the UI and is thrown away. The killer demo feature, already paid for |
| `image` blocks inside `assistant` | `output/handlers/image.py` (content block `type:"image"`) | `store.ts` assistant case filters `type==='text'` only → generated images dropped |
| `design_preview_updated` | router + runner `write_preview` | Emilia's live design preview (at `/static/previews/index.html`) never surfaces |
| `approval_requested/applied/denied` | self-heal flow | No badge/notification; user finds out only by email or by opening OpsDrawer |
| `source_file_modified` | self-heal surface writes | Self-modification activity invisible |
| `email_sent`, `standup`, `routine_completed` | email handler, standup svc, scheduler | No toast/notification |
| `bark_ok` flag on `assistant` | `output/pipeline.py` | Spec'd Web Speech fallback never implemented — with bark down there is **no voice at all** |

### UI listens → backend silent

| Event | UI handler | Reality |
|---|---|---|
| `queue_update` | `store.ts:181`, SmartIsland QUEUE tab | **Never emitted by backend.** Queue tab is permanently empty. Delegations data exists in `ceo_node` output — just not translated |

## 4. REST endpoints with no UI surface

`/api/projects` (GET/POST), `/api/hire` + `/api/fire`, `/api/changelog`, `/api/capabilities`, `/api/storage`, `/api/ceo-sessions`, `/api/email/inbox`, `/api/email-tasks/poll`, `/api/routines` CRUD (UI can list+run only — no create/edit/delete/logs), `/api/skills/{id}/rollback` + DELETE, `/api/browser/*` manual controls, `/api/compact`, `/api/filler` (spec'd voice filler — never called).
**Jira:** full service + tools + design spec exist (`jira.py`, 2026-06-04 spec) — zero UI.

## 5. Stub endpoints (backend feature gaps)

- `/api/workqueue` → `[]` hardcoded; `init` payload `work_queue: []` always
- `/api/email-tasks` → `[]` while the email graph actually processes tasks — email pipeline 100% invisible
- `/api/task-history` → `[]`
- Custom hired agents (`/api/hire`) can never render: `AGENT_POSITIONS`/`WORKER_IDS` hardcoded to 5 workers in `types.ts`/`NexusScene.tsx`/`store.ts`

## 6. 3D immersion assessment vs "Jarvis arc reactor" target

Present: arc reactor (3 rotating tori + core), bloom/chromatic-aberration/vignette, cortical wave floor shader, 500 particles, glass hex panels, palette, island.

Missing for the Jarvis feel:
1. **No camera choreography** — static camera; no fly-to on select, no idle orbit. This is the single biggest "feels basic" factor.
2. **No live holograms** — Maya's browser frames could be a floating 3D screen; Emilia's design preview a hologram panel. Data already streams.
3. **Static layout, no roster dynamism** — workers fixed in space; hired agents impossible.
4. **No boot sequence** — Jarvis powers up; NEXUS just appears.
5. **No data ring around the reactor** — clock/uptime/activity bars orbiting the core.
6. **No task context in 3D** — edges pulse but never say *what* is flowing.
7. **No scanline/noise film grain** — the "hologram in a helmet" finish.
8. **No offline state visual** — WS drop is silent.

## 7. Resource feasibility (8 GB RAM / 80 GB disk / weak GPU server)

- **All 3D runs in the viewer's browser** — R3F/bloom costs the server nothing. Safe additions: instanced meshes, capped `dpr≤1.5`, `AdaptiveDpr`. Avoid: SSAO, realtime shadows, >2k particles, render-targets per frame.
- **Server-side**: bark-lite is gTTS (lightweight ✅), browser-svc is one Chromium (~400 MB — the heaviest thing; keep single slot). No new server processes proposed. Do **not** add local Whisper/embedding models; Web Speech API does STT in-browser for free.
- jpeg screencast at quality 60 already throttled by CDP ack — fine on this box.

## 8. Recommended sequencing

1. **Plan A — `2026-06-12-pipeline-repairs-and-ui-connectivity.md`**: fix B1–B5, emit `queue_update`, wire all dropped events, surface routines CRUD / email tasks / team / vitals, TTS fallback, browser viewport + design preview panels.
2. **Plan B — `2026-06-12-jarvis-3d-immersion.md`**: camera director, dynamic orbital roster, boot sequence, reactor data ring, holo browser screen, edge task labels, scanlines + HUD frame.

Plan A makes everything *true*; Plan B makes it *feel like Jarvis*. Execute in that order — the holograms in Plan B feed off events wired in Plan A.
