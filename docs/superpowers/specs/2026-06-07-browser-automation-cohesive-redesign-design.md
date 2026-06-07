# Browser Automation Cohesive Redesign — Design Spec

**Date:** 2026-06-07
**Status:** Proposed
**Supersedes (in part):** `2026-06-07-delegation-and-maya-tooltag-fixes-design.md` Fix 2 — see "Relationship to existing specs" below
**Builds on:** `2026-06-06-browser-agent-maya-design.md` (founding Maya design — still the architectural baseline; this spec revises specific parts of it)

## Overview

Maya (the browser-automation worker) appears to run tasks — `/api/task-history` shows
self-reported summaries like "Session complete: 3 applied, 1 skipped" — but
`browser-svc` never receives a single request, the Browser Board never updates, and
nothing is ever actually applied to. This spec is a cohesive redesign covering the
root cause and five related areas: tag dispatch, the live dashboard, automation/manual
handoff, a learning loop, architectural cleanup, and a clean pattern for future workers.

## Root cause (diagnosis)

Maya emits her `[BROWSER_DISCOVER:...]` / `[BROWSER_APPLY:...]` tags exactly as
instructed — confirmed verbatim in her raw chat history. The problem is downstream:

- `run_agent()` (`executor.py:721-775`) dispatches every turn to one of three backends:
  `run_claude_agent` (default — active whenever `should_use_claude()` is true, which is
  the normal/default state), `run_gemini_agent`, or `run_tgpt_agent` (rare last-resort
  fallback, reached only when both Claude quota and Gemini fail).
- **Only `run_tgpt_agent`** (`executor.py:310-361`) runs the tool-execution loop:
  `parse_tool_call()` → `_execute_tool()` → (for browser tags) `call_browser_svc()`,
  followed by feeding `[Tool Output]` back into the next turn.
- `run_claude_agent` and `run_gemini_agent` stream the model's text straight through
  `pipeline.process()` (`app/output/pipeline.py:17-63`), which only recognizes tags
  registered in `app/output/registry.py` (`SPEAK`, `EMAIL_USER`, `GENERATE_IMAGE`, etc.)
  — **not** `BROWSER_*` tags. The tags pass through as inert display text. No HTTP call
  ever reaches `browser-svc`, no slot is acquired, no screencast starts.
- Because neither of the primary backends provides a `[Tool Output]` feedback loop
  (that exists only inside `run_tgpt_agent`), Maya has no ground truth on subsequent
  turns. She narrates plausible continuations of her own unconfirmed prior claims
  ("already launched... in flight... holding off on duplicate"), which is what produces
  the fabricated `/api/task-history` summaries.

This is an architecture mismatch: the tool-execution capability
(`parse_tool_call`/`_execute_tool`/`call_browser_svc`) exists in the codebase, but is
wired only into the rarely-used `run_tgpt_agent` fallback loop — not into the
`run_claude_agent`/`run_gemini_agent` paths Maya actually runs on ~99% of the time.

## Relationship to existing specs

- **`2026-06-06-browser-agent-maya-design.md`** is the founding architectural spec for
  Maya (status: Approved) and remains the baseline. This redesign revises two specific
  points in it: (a) slot 0 was reserved for Overleaf/CV tailoring — the user has since
  moved CV compilation to run locally, so slot 0 is removed entirely (Section 2); (b)
  `NUM_SLOTS` therefore goes from 5 to 4.

- **`2026-06-07-delegation-and-maya-tooltag-fixes-design.md`** contains two fixes:
  - **Fix 1** (anchoring the `[DELEGATE:role]` regex to line-start + a persona guard
    against stray mid-sentence tag mentions) is **independent and unaffected** by this
    redesign. It addresses a real, separate bug (the CEO emitting `[DELEGATE:browser]`
    inside ordinary prose) and should still be implemented as written.
  - **Fix 2** (teaching `_build_gemini_prompt` to allow Maya's `gemini_safe_tags`
    through instead of suppressing them) rests on the claim that `BROWSER_*` tags
    "are parsed from her final text response... and work identically regardless of
    backend." **That claim is the same false premise that produced the original bug**:
    `parse_tool_call`/`_execute_tool`/`call_browser_svc` are wired up only inside
    `run_tgpt_agent`, not `run_gemini_agent`. If Fix 2 is implemented in isolation,
    Maya would correctly *emit* `[BROWSER_APPLY:]` on Gemini — and the tags would
    *still be inert*, identical to the symptom on Claude today. It would look fixed
    (correct tags appear in her text) while doing nothing.
  - **This spec's Section 1 supersedes Fix 2.** Once `BROWSER_*` tags are registered
    as universal output-pipeline handlers (Section 1), they fire identically regardless
    of which backend produced the text — including Gemini. Fix 2's actual goal (Maya
    emitting real tags on Gemini instead of narrating in prose) becomes substantially
    easier to achieve too, because the tags will visibly *do something* the moment
    they appear, closing the loop that currently encourages narration over action.
    Fix 2 should be marked superseded; its `gemini_safe_tags` persona-prompt idea may
    still be worth keeping as a *complementary* nudge (it makes Maya more likely to
    emit the tags on Gemini at all), but it is no longer the load-bearing fix — Section
    1 is what makes the tags functional once emitted.

## Section 1 — Universal tag dispatch via the output pipeline

**This is the foundational fix (Approach B).**

Register `BROWSER_DISCOVER`, `BROWSER_APPLY`, `BROWSER_COMPANY`, and
`BROWSER_PROFILE_MATCH` as handlers in `app/output/registry.py`, following the exact
pattern already used for `SPEAK` / `EMAIL_USER` / `GENERATE_IMAGE`. Because
`pipeline.process()` runs on **every** backend's full response text — both call sites,
`executor.py:359` (inside `run_tgpt_agent`) and `executor.py:446`
(`run_claude_agent`/`run_gemini_agent`) — registering the tags here makes them fire
identically no matter which backend produced the text. No per-backend special-casing.

Each handler:

1. Parses its tag's arguments, reusing the existing parsing logic from
   `parse_tool_call()` (`tools.py:273-299`) rather than duplicating regexes.
2. Picks a free slot via `find_free_slot()` (currently dead code in
   `session_manager.py:95-99` — this is its first real caller).
3. Fires `call_browser_svc()` as a background `asyncio.create_task` — fire-and-forget,
   because browser actions take 30 seconds to several minutes and must not block the
   chat turn.
4. Replaces the tag in the displayed text with a clean status line (e.g. "🔎 Searching
   LinkedIn for Python backend roles in Bangalore (slot 2)...") and emits a `tool_call`
   frontend event so the UI reflects that something real just started.

**Async result-feedback loop:** when the background browser-svc task completes, a new
`/api/browser-result` endpoint (or the existing relay WS channel, extended with a
`result` message type) records the real outcome into Maya's conversation history and
re-invokes her. This grounds her next response in an actual result rather than her own
unconfirmed prior narration — directly closing the hallucination loop that produces
fabricated `/api/task-history` summaries.

This also retires `run_tgpt_agent`'s special status as "the only backend that can run
browser tools" — browser automation now works the same on whichever backend Maya
happens to be routed to, including the rare tgpt fallback (whose existing
`parse_tool_call`/`_execute_tool` path can remain as-is; the pipeline handler simply
becomes a second, backend-agnostic entry point to the same `call_browser_svc`).

## Section 2 — Live dashboard / "live peek" redesign

**Remove slot 0** (Overleaf/CV — CV tailoring now happens locally, per the user). This
revises the founding spec's slot table: `NUM_SLOTS` goes from 5 to 4, and the Browser
Board becomes a clean 4-tile grid (one queue/log tile can be dropped or kept depending
on remaining UI space — implementation plan to decide based on current layout code).

To make the live peek actually reliable (current symptom: "It does not seem stable...
it does not update at all"):

- **Per-slot status chips** (idle / connecting / streaming / error / awaiting input),
  sourced from `/api/browser-svc/slots` and polled on an interval. This is a
  structural backup signal that's independent of the JPEG frame stream — if frames stop
  arriving, the chip still tells you the slot's actual state rather than leaving a
  frozen image with no explanation.
- **"Last frame received" timestamp** per tile, so a stalled stream is visually obvious
  (e.g. greyed out / "no frames for 45s") instead of silently showing a stale image.
- **Auto-reconnect + fixed logging** in `relay_client.py`: its `logger.info`/`warning`
  calls currently produce zero output in `docker logs` despite the WebSocket connection
  being demonstrably alive — almost certainly a logger-propagation/handler-config
  mismatch with uvicorn's root logger. Fixing this is a prerequisite for diagnosing any
  future relay issues, since right now the relay is a black box.
- **"Take over" button** per slot, calling the existing `ensure_interactive()` — this
  is the UI entry point into the manual handoff designed in Section 3.

## Section 3 — Automation ↔ manual handoff and the learning loop

**Detection** happens inside `job_workflow.py` (running in `browser-svc`): check for
captcha selectors/text, unexpected login-wall redirects, or missing expected DOM
elements after a retry. On detection, the workflow **pauses and classifies** the
blocker rather than blindly retrying or silently failing.

**Escalation:**
1. Switch the slot to interactive mode via the existing `ensure_interactive()`.
2. Dashboard tile shows "awaiting input" with a short blocker description (e.g.
   "Naukri is showing a login page — needs manual sign-in").
3. Send a notification with a "Take over" prompt (ties into Section 2's button).

**Hand-back:** the user signals "resume" (via the dashboard or chat) and the workflow
continues from the now-unblocked page state — **not** a restart from scratch.

**Learning loop:** persist structured blocker entries — `{site, blocker_type,
resolution, timestamp}` — to `memory.py`, tagged for retrieval scoped per-agent and
per-site via `get_relevant_memories()`. Before starting a new run on a site that has
caused trouble before, Maya proactively queries memory and adapts or warns up front
("naukri.com required manual login last time — I may need you to step in again").

This depends on fixing the active FTS5 query-escaping bug in `memory.py` first
(raw user free-text is currently passed unescaped into `MATCH` queries, throwing
`fts5: syntax error near ","` on nearly every turn) — the loop is only as good as
its retrieval, and broken retrieval would silently make the "learning" inert in
exactly the same way the original tag-dispatch bug was silent.

## Section 4 — Architectural cleanup

- **(a) Slot renumbering to 0–3.** Removing slot 0 (Section 2) also resolves an
  existing inconsistency: `apply`/`discover`/`company-apply`/`profile-match` endpoints
  in `main.py` validate `1 ≤ slot_id ≤ 4` while the interactive endpoints
  (`click`/`type`/`key`/`navigate`/`reload`/`back`) validate `0 ≤ slot_id < NUM_SLOTS`.
  After the redesign there is one consistent valid range (`0 ≤ slot_id < 4`) used
  everywhere.
- **(b) Wire up `find_free_slot()`** to replace the hardcoded `slot_id: int = 1`
  defaults on `ApplyRequest`/`DiscoverRequest`/`CompanyRequest`/`ProfileMatchRequest`
  in `main.py`. Today, two concurrent actions both default to slot 1 and collide
  (`409 Slot 1 is busy`); `find_free_slot()` already exists for exactly this purpose
  but has never been called.
- **(c) Fix the FTS5 query-escaping bug in `memory.py`** — escape or quote user
  free-text before composing `MATCH` queries. Required for Section 3's learning loop,
  but also a standing bug worth fixing on its own (it currently throws on nearly every
  `get_relevant_memories()` call with multi-word or punctuated input).
- **(d) Fix `relay_client.py` logger visibility** — likely a propagation or
  handler-configuration mismatch with uvicorn's root logger, since the WS connection is
  demonstrably alive but `logger.info`/`warning` calls never appear in `docker logs`.
  Needed to make Section 2's "auto-reconnect + fixed logging" actually observable.

## Section 5 — Clean pattern for adding future workers

Section 1 establishes the tag-registration mechanism as **the** integration point for
any worker that needs to trigger real-world side effects. The pattern, as a checklist
for adding a new worker:

1. Define the worker's persona and its tool tags in `definitions.py` (as Maya's
   `BROWSER_*` tags are defined today).
2. Register each tag as an output-pipeline handler in `registry.py`. This works
   identically regardless of which backend (Claude / Gemini / tgpt) produced the
   response — there is never a need to special-case a worker by name in the executor.
3. If the worker needs a sidecar service, follow `browser-svc`'s proven shape: FastAPI
   app, background-task endpoints (`bg.add_task`), a `/status`-style introspection
   endpoint, and an optional relay for live state.
4. If the action is long-running or async, reuse the completion-callback →
   re-invoke-with-real-result pattern from Section 1 (the `/api/browser-result`
   endpoint and re-invocation), so the worker is always grounded in actual outcomes.
5. If the worker should learn from past attempts, persist tagged structured entries to
   `memory.py`, scoped by `agent_id` and a `mem_type`, following Section 3's pattern.

This redesign turns Maya into the reference implementation of this pattern — the
template the next worker after her can copy directly, instead of reinventing
backend-specific tool wiring from scratch.

## Testing

- **Section 1**: with the registry handlers wired, send Maya a `[BROWSER_DISCOVER:...]`
  prompt on the Claude backend (the default) and confirm a real request reaches
  `browser-svc` (visible in its logs / `/slots` status), a slot transitions to `busy`,
  and the displayed chat text shows the replaced status line rather than the raw tag.
  Repeat forcing the Gemini backend to confirm backend-agnostic behavior. Confirm the
  result-feedback loop: after the background task completes, Maya's next turn reflects
  the real outcome (not a narrated guess) and `/api/task-history` matches reality.
- **Section 2**: verify the dashboard renders 4 tiles (not 5), status chips update from
  `/api/browser-svc/slots` independent of frame arrival, the "last frame" timestamp
  visibly stales when frames stop, and `docker logs` for browser-svc now shows
  `relay_client` log lines. Click "Take over" on a slot and confirm it enters
  interactive mode.
- **Section 3**: simulate a captcha/login-wall on a test page and confirm the workflow
  pauses (does not retry-loop or silently fail), the dashboard shows "awaiting input"
  with a description, and "resume" continues from the unblocked state rather than
  restarting. Confirm a blocker entry is written to `memory.py` and that a subsequent
  run on the same site retrieves it via `get_relevant_memories()` without throwing an
  FTS5 syntax error.
- **Section 4**: confirm slot IDs 0–3 validate consistently across every endpoint;
  fire two `discover` requests concurrently and confirm they land on different slots
  via `find_free_slot()` rather than colliding on slot 1; run
  `get_relevant_memories()` with punctuated/multi-word free text and confirm no FTS5
  syntax error.
- **Section 5**: no new code to test directly — validated by Section 1 working as a
  generic mechanism (i.e., it doesn't need to know "browser" by name to function).

## Out of scope

- Rewriting `run_tgpt_agent`'s existing `parse_tool_call`/`_execute_tool` loop — it
  continues to work as-is for the rare cases it's reached; Section 1 simply gives the
  primary backends an equivalent path via the output pipeline.
- `_classify_model` / backend routing logic changes (consistent with the 06-07 spec's
  own "out of scope" — no reason to revisit this here).
- Captcha-*solving* automation (out of scope per the founding 06-06 spec's "Bot
  Detection Avoidance" section — "no proxy rotation or captcha solving"; Section 3
  here handles captchas by pausing for a human, not by defeating them).
- Overleaf/CV-tailoring pipeline — removed from scope entirely now that CV compilation
  runs locally (this is *why* slot 0 is being removed, not a thing being redesigned).
