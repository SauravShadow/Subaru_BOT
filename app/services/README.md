# app/services/ — Background Services

Stateless utility modules and background loop services. All are imported lazily
(inside async functions or lifespan handlers) to avoid circular import chains.

---

## Service Directory

| Module | Purpose |
|--------|---------|
| `bark_client.py` | HTTP client for bark-svc TTS sidecar |
| `browser.py` | Persistent Playwright session (in-container browser) |
| `browser_svc.py` | HTTP client for browser-svc job application sidecar |
| `email.py` | SMTP send + IMAP read (basic) |
| `email_inbox.py` | Enhanced IMAP: threaded replies, Message-ID tracking, mark-as-read |
| `email_poller.py` | Async poll loop; dispatches inbox to email_graph |
| `jira.py` | Jira Cloud REST API v3 wrapper |
| `memory.py` | SQLite FTS5 long-term agent memory |
| `scheduler.py` | Cron routine executor (croniter) |
| `self_heal.py` | Zone-based source file protection and approval workflow |
| `standup.py` | Morning standup generator |

---

## scheduler.py

Cron-based routine scheduler running as an asyncio background task.

**Loop**: `start_scheduler_loop()` — ticks every 30s via `asyncio.sleep(30)`.

**Race-condition safety**: fire key `{id}:{YYYYMMDDHHMM}` ensures each routine
fires at most once per scheduled minute regardless of 30s tick frequency.

**Persistence**:
- `nexus_routines.json` — routine definitions (id, name, schedule, agent, prompt, enabled, timezone)
- `nexus_routine_logs.json` — rolling last 200 run logs

**Default routine seeding**: `_seed_default_routines()` is called at startup.
Inserts `morning_standup` (disabled by default) if it doesn't exist. Never
overwrites existing entries.

**Execution**: `run_routine(routine)` — for `morning_standup` id, calls
`standup.run_morning_standup()` directly. For all other routines, calls
`run_agent(routine["agent"], routine["prompt"], ...)` and parses any
`[EMAIL_USER:...]` tags from the output via `email_handler.parse_emails()`.
Broadcasts `{type: "routine_completed", routine_id, status, output[:500]}` WS event.

**API**: CRUD via `GET/POST/PUT/DELETE /api/routines`, manual trigger via
`POST /api/routines/{id}/run`, logs via `GET /api/routines/{id}/logs`.

---

## standup.py

**Entry point**: `run_morning_standup(broadcast_fn=None) -> str`

Generates a 200-300 word CEO morning briefing:
1. `generate_standup_prompt()` — reads active projects from `state.load_projects()`,
   formats current date (IST), builds a structured prompt requesting email via
   `[EMAIL_USER: Subaru Morning Briefing — {date}]`.
2. Calls `run_agent("ceo", prompt, _send, model="claude")` — always Claude.
3. Parses `[EMAIL_USER:...]` from the accumulated response and sends via SMTP.
4. Broadcasts `{type: "standup", content: text, date: iso_string}` WS event.

The scheduler calls this via `run_routine()` when `morning_standup` routine fires.

---

## bark_client.py

HTTP client for the `bark-svc` sidecar (port 9001). Returns `None` on any error
so callers degrade gracefully (fallback to Web Speech API in the frontend).

| Function | Endpoint | Purpose |
|----------|----------|---------|
| `speak(text, emotion)` | `POST /speak` | TTS audio — returns base64 WAV or None |
| `sing(lyrics, style)` | `POST /sing` | Singing audio — returns base64 WAV or None |
| `get_filler(context)` | `GET /filler` | Pre-built filler clip — returns base64 WAV or None |

`emotion` values: `"calm"`, `"excited"`, `"sad"`, `"whisper"`, `"energetic"`.
Timeout: 15s for speak/filler, 30s for sing.

---

## email.py

Basic SMTP/IMAP client. Uses `config.SMTP_*` and `config.IMAP_*` env vars.
Both send and read run in a thread executor to avoid blocking the event loop.

```python
async def send_mail(subject, body, to=None) -> dict  # {"ok": bool, "error"?: str}
async def read_emails(max_emails, folder, unread_only) -> dict  # {"ok", "emails": [...]}
```

`send_mail` defaults `to` to `config.USER_EMAIL` if None.
Does not mark emails as read — use `email_inbox.fetch_new_emails()` for that.

---

## email_inbox.py

Enhanced IMAP layer used by `email_poller.py`. Key differences from `email.py`:
- Marks fetched emails as read (`STORE \Seen`).
- Returns full metadata including `message_id`, `from_email`, `references`,
  `in_reply_to` for thread tracking.
- `fetch_new_emails(max_emails=10)` — filters UNSEEN, returns list of dicts.

---

## email_poller.py

Async poll loop: `start(email_graph)` runs indefinitely with 30s sleep.
Each `poll_once(email_graph)` call:
1. Fetches new emails via `email_inbox.fetch_new_emails()`.
2. Skips automated senders (`noreply`, `mailer-daemon`, etc.) and
   OOO/auto-reply subjects.
3. For each email, builds `thread_id = "email_{message_id}"`.
4. Checks `email_graph.aget_state(cfg)`: if `graph.next` is truthy (graph is
   waiting for user reply), invokes with `{"user_reply": body}` to resume.
   Otherwise invokes fresh with `{"email": email, "is_owner": bool}`.
5. Tracks tasks in `_email_tasks` dict (runtime cache, not persisted).

`_is_trusted(email_addr)` — checks against `USER_EMAIL`, `IMAP_USER`, `SMTP_USER`.

`list_tasks()` — returns last 20 email tasks sorted by updated timestamp.
Exposed via `GET /api/email-tasks`.

---

## memory.py

SQLite FTS5 long-term memory at `nexus_memory.db` (via `config.MEMORY_DB`).

**Schema**:
- `memories` table: `id, agent_id, mem_type, content, importance, created_at, last_hit_at`
- `memories_fts` virtual table: FTS5 index with porter stemmer
- `user_preferences` table: `key, value, updated_at`

**Key functions**:

```python
init_db()                            # Called in lifespan; creates tables + WAL mode
save_memory(agent_id, content, mem_type, importance)  # Inserts into both tables
get_relevant_memories(agent_id, query, limit=5) -> list[str]
    # FTS5 MATCH query on content, filtered by agent_id or 'shared'
    # Ranks by rank * importance; updates last_hit_at on hits
save_preference(key, value)
get_preference(key, default="") -> str
decay_old_memories(days_threshold=7, decay_amount=0.05) -> int
    # Reduces importance of unhit memories; not called automatically
```

`mem_type` values in practice: `"user_query"`, `"agent_response"`,
`"compacted_history"`, `"vision_query"`, `"vision_response"`.

Memory is injected into every agent prompt via `_build_context_block()` in `runner.py`.

---

## self_heal.py

Zone-based source file write protection. Called when tgpt agents use `[WRITE_SOURCE:]`.

**Zone model**:
| Zone | Paths | Action |
|------|-------|--------|
| `immutable` | `app/main.py`, `skills/loader.py`, `skills/core/` | Blocked entirely |
| `protected` | `app/agents/executor.py`, `definitions.py`, `router.py`, `websocket.py`, `requirements.txt`, `Dockerfile`, `docker-compose.yml`, `entrypoint.sh` | Email approval required |
| `surface` | `app/static/` prefix | Auto-applied immediately |
| `learning` | Everything else | Auto-applied immediately |

**Approval workflow** (protected zone):
1. `create_approval(file_path, content, agent, resolved_path)` → stores in
   `nexus_pending_approvals.json`, returns 8-char hex `approval_id`.
2. `build_approval_email(approval_id, ...)` → returns `(subject, body)` with
   unified diff included.
3. `email_svc.send_mail(subject, body)` sends to `config.USER_EMAIL`.
4. Operator replies `"APPROVE {id}"` or `"DENY {id}"`, OR uses
   `POST /api/approvals/{id}/apply` or `POST /api/approvals/{id}/deny`.
5. `apply_approval(approval_id)` writes file and sets status = "applied".

WS events emitted: `approval_requested`, `approval_applied`, `approval_denied`.

---

## browser.py

Persistent Playwright Chromium session. One page is kept alive across all operations
so login sessions, cookies, and form state persist between tool calls.

**Session lifecycle**: `_get_browser()` lazy-creates and auto-reconnects.
`_get_page()` creates a new page only if current one is closed or None.

**Public API**:
```python
write_preview(html) -> str           # Writes to /app/app/static/previews/index.html (no Playwright)
navigate(url) -> dict                # goto + screenshot → {title, url, screenshot}
click_element(selector) -> dict      # click + screenshot → {url, title, screenshot}
type_text(selector, text) -> dict    # fill form field → {ok, selector}
wait_for_element(selector) -> dict   # wait for CSS selector → {ok} or {error}
get_page_text() -> dict              # inner_text("body")[:8000] + screenshot
extract_text(selector) -> str        # inner_text(selector)
take_screenshot(url?) -> dict        # navigate optional, return screenshot path
```

Screenshot saved to `/app/app/static/previews/browser_screenshot.png` and
served at `/static/previews/browser_screenshot.png`.

This is for in-container browsing (CEO/workers using WEB_* tags). Job application
automation runs in the separate `browser-svc` container via `browser_svc.py`.

---

## jira.py

Jira Cloud REST API v3 wrapper. Auth: `(JIRA_EMAIL, JIRA_TOKEN)` basic auth.

```python
get_ticket(ticket_id) -> str          # Fetch ticket + last 5 comments, returns formatted text
search_tickets(jql) -> str            # JQL search, returns formatted list
update_status(ticket_id, transition) -> str  # Status transition by name
add_comment(ticket_id, body) -> str   # Add comment to ticket
get_context_summary() -> str          # Used by runner._get_ceo_context() for CEO awareness
```

Not configured by default; set `JIRA_URL`, `JIRA_EMAIL`, `JIRA_TOKEN` in `.env`.
