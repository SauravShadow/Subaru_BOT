# app/api/ — REST Routes and WebSocket Handler

Two files: `router.py` (all REST endpoints) and `websocket.py` (WebSocket handler
and event translation layer). No authentication — internal only.

---

## REST Routes (`router.py`)

### Agents

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/agents` | List all agents (built-in + custom contractors), public info only |
| GET | `/api/chat/{agent_id}/history` | Conversation history for an agent |
| POST | `/api/hire` | Add a custom contractor agent at runtime |
| DELETE | `/api/hire/{agent_id}` | Remove a custom contractor (built-ins protected) |

### Projects & State

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/projects` | Load projects from `nexus_projects.json` |
| POST | `/api/projects` | Save a new project entry |
| GET | `/api/capabilities` | System capability summary + email/skills status |
| GET | `/api/storage` | Disk usage: `{used_gb, max_gb, percent}` |

### Changelog

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/changelog` | Load `nexus_changelog.json` |
| POST | `/api/changelog` | Append entry: `{feature, files, agent}` |

### Routines (cron scheduler)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/routines` | List all routines from `nexus_routines.json` |
| POST | `/api/routines` | Create a routine (required: id, name, agent, schedule, prompt) |
| PUT | `/api/routines/{id}` | Update updatable fields: name, description, schedule, timezone, prompt, enabled |
| DELETE | `/api/routines/{id}` | Delete routine |
| POST | `/api/routines/{id}/run` | Manually trigger a routine now |
| GET | `/api/routines/{id}/logs` | Last N run logs (default 10) |

### Email

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/email` | Send email: `{subject, body, to?}` |
| GET | `/api/email/inbox` | Read inbox: `?max_emails=5&folder=INBOX&unread_only=true` |
| GET | `/api/email-tasks` | List recent email_poller tasks (runtime cache) |
| POST | `/api/email-tasks/poll` | Trigger immediate email poll (needs `email_graph` in app state) |

### Skills

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/skills` | List registered tools and learned skill manifests |
| POST | `/api/skills/register` | Register a new skill (localhost-only) |
| POST | `/api/skills/{id}/rollback` | Rollback a skill to previous version |
| DELETE | `/api/skills/{id}` | Delete a learned skill and reload |

### Self-Heal Approvals

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/approvals` | List all pending/applied/denied approvals |
| POST | `/api/approvals/{id}/apply` | Apply an approved source file change |
| POST | `/api/approvals/{id}/deny` | Deny a pending approval |

### Browser (in-container Playwright)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/browser/navigate` | Navigate to URL, returns `{title, url, screenshot}` |
| GET | `/api/browser/screenshot` | Serve latest screenshot as `image/png` |
| POST | `/api/browser/screenshot` | Take screenshot, optionally navigate first |
| POST | `/api/browser/extract` | Extract text from CSS selector on page |
| POST | `/api/browser/click` | Click element by CSS selector |
| GET/POST/... | `/api/browser-svc/{path}` | Wildcard proxy to browser-svc container |

### Design Preview

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/design/preview` | Write HTML to live preview (localhost-only) |

### System

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | `{app, bark, browser, email}` health booleans |
| POST | `/api/rebuild` | Proxy rebuild request to SRE sidecar |
| GET | `/api/ceo-sessions` | CEO conversation history grouped into sessions (30-min gap) |
| POST | `/api/compact` | Archive old messages to memory, trim history |
| GET | `/api/filler` | Pre-built Bark filler audio clip |
| GET | `/{full_path:path}` | SPA catch-all: serves `app/static/index.html` |

---

## WebSocket Protocol (`websocket.py`)

**Connect**: `ws://host/ws?model=claude`

Model param: `"claude"` (default) | `"gemini"` | `"chatgpt"`.
One thread per connection. Thread id: `f"ws_{uuid4().hex}"`.

### Client → Server Messages

```json
{"type": "message", "text": "...", "agent": "ceo"}
```
- `agent` omitted or `"ceo"` → routes through `nexus_graph` (LangGraph path).
- `agent` == any other agent id → `_run_direct()` (direct chat, no CEO delegation).

```json
{"type": "cancel_worker"}
```
Cancels the current running asyncio task for this thread.

```json
{"type": "model", "model": "gemini"}
```
Switches the session model for subsequent messages.

```json
{"type": "clear"}
```
Cancels current task (same effect as cancel_worker).

### Server → Client Events

All events include `"thread_id"` (string) identifying the graph run.

| Type | Fields | When |
|------|--------|------|
| `init` | `agents: [{id, name, role, status}]`, `work_queue: []` | On WebSocket connect |
| `thinking` | `agent: "ceo"` | `on_chain_start` for `ceo_node` |
| `delegation` | `agent: worker_id` | `on_chain_start` for worker node |
| `worker_step` | `agent, step, tool, label` | `on_tool_start` in LangGraph |
| `worker_checkpoint` | `agent, index, summary, step` | `on_chain_end` for `worker_node` |
| `worker_done` | `agent` | `on_chain_end` for `output_node` |
| `done` | `agent: "ceo"` | `on_chain_end` for `ceo_node` |
| `queue_update` | `queue: [{id, task, status, agent}]` | After CEO delegates; after each worker_done |
| `error` | `agent, message` | `on_chain_error` or exception |
| `assistant` | `agent, message: {content}, bark_ok?` | Streaming token or pipeline output |
| `audio` | `mode: "speak"\|"sing", data: base64` | Bark TTS from SPEAK/SING handlers |
| `email_sent` | `subject, ok, error` | EMAIL_USER handler |
| `backend_switch` | `backend, quota_ok, gemini_ok, retry_at, message` | Claude quota hit, switching backend |
| `backend_status` | `agent, backend, quota_ok, gemini_ok` | Backend status change notification |
| `browser_navigated` | `screenshot, title, url` | WEB_NAVIGATE/CLICK/GET_TEXT tool |
| `browser_result` | `summary\|message` | browser-svc relay (job application result) |
| `design_preview_updated` | `message` | WRITE_PREVIEW tool |
| `routine_completed` | `routine_id, status, output, timestamp` | Scheduler routine finished |
| `standup` | `content, date` | Morning standup completed |
| `source_file_modified` | `path, zone, agent` | WRITE_SOURCE auto-applied |
| `approval_requested` | `approval_id, file_path, agent` | WRITE_SOURCE to protected zone |
| `approval_applied` | `approval_id, message` | `POST /api/approvals/{id}/apply` |
| `approval_denied` | `approval_id, message` | `POST /api/approvals/{id}/deny` |
| `tool_call` | `agent, tool, label, path` | tgpt loop tool dispatch (non-LangGraph) |

---

## Routing: Direct vs LangGraph

```python
# In ws_endpoint:
if target == "ceo":
    _run_and_stream(text, thread_id, model)  # → nexus_graph.astream_events()
else:
    _run_direct(target, text, model)         # → run_agent() + pipeline.process()
```

**LangGraph path** (`_run_and_stream`):
- Uses `graph.astream_events(initial_state, config, version="v2")`.
- `_translate_event()` maps LangGraph event types to WebSocket message types.
- `_queue_updates()` maintains the work queue state from CEO delegations.
- Registers a broadcast callback in `app.graph.broadcast` before streaming.

**Direct path** (`_run_direct`):
- Bypasses all graph nodes and CEO planning.
- Calls `runner.run_agent()` directly with the worker's agent_id.
- Calls `pipeline.process()` on the raw text result.
- Use when you want to chat 1:1 with a specific worker (frontend, backend, etc.)
  without CEO orchestration overhead.

---

## Browser Relay WebSocket (`/ws/browser-relay`)

Receives events from `browser-svc` container:
- `browser_result` → dispatches to `handle_browser_result(data, active_model)` → `broadcast_event(data)`.
- `browser_blocker_resolved` → `broadcast_event(data)`.
- Any other type → `broadcast_event(data)` directly.

Optional `BROWSER_RELAY_SECRET` env var enforces `Authorization: Bearer <secret>` on connect.

---

## Session and Broadcast

`_sessions: set[Session]` — all connected WebSocket clients. Each `Session` wraps
its WebSocket with an asyncio lock to prevent concurrent send races.

`broadcast_event(data)` — sends `data` to all sessions. Called from everywhere
(nodes, handlers, router endpoints, browser-relay).

`_active_runs: dict[str, asyncio.Task]` — maps thread_id → current asyncio task.
Allows `cancel_worker` to cancel exactly the running graph task.

---

## Authentication

None. All routes are internal-only. The container exposes only port 3030 → mapped
to host 3031. The SPA serves from the same origin, so WebSocket connects same-origin.
Skill registration and design preview endpoints are restricted to `127.0.0.1` by
checking `request.client.host`.
