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
   because real-world actions are slow and must never block the chat turn.
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
  `browser-svc/main.py:35-37`, backed by `SessionManager.status()`)
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
quoted before being passed to FTS5's `MATCH` (`app/services/memory.py`,
fixed in Phase 1 Task 4). If you're extending `memory.py` itself, preserve that
quoting; punctuated content (company names with apostrophes, domains with dots)
is the norm, not the exception, for structured worker memories.

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
