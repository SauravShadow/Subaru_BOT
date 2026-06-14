# NEXUS Orchestration Stability Fix — Design

**Date:** 2026-06-14
**Status:** Approved (pending spec review)

## Problem

When a user gives the company a task (e.g. "create a books recommendation site"), three failures were observed:

1. **Late response** — no visible feedback until the CEO's entire reply lands.
2. **Speaking repeatedly** — the same content is spoken/shown more than once.
3. **3–4 workers/CEO speaking at the same time** — overlapping audio.

## Root Causes (verified in code)

| Symptom | Cause | Location |
|---|---|---|
| Simultaneous voices | `route_after_ceo` returns a list of `Send(...)`; LangGraph runs all delegated worker subgraphs concurrently in one superstep, each ending in `pipeline.process` → `[SPEAK:]` → audio. No serialization of the audio channel. | `app/graph/nexus_graph.py:27`; `app/graph/workers/base.py`; `app/output/handlers/speak.py` |
| Every agent speaks | Gemini prompt mandates `[SPEAK: full reply]` in every response. | `app/agents/runner.py:485` |
| Repeating (cross-tab) | `broadcast_event` sends to every socket in `_sessions`; worker `send()` routes through it. Extra listeners double every utterance. | `app/api/websocket.py:173` |
| Repeating (overlap runs) | New user message does `_active_runs[thread_id] = t` without cancelling the previous run; double-submit / fast follow-up overlaps two full graph runs. | `app/api/websocket.py:272` |
| Repeating (dup emit) | `_translate_event`'s `on_chat_model_stream` branch emits `{type:assistant}` for the LangChain Gemini review node (attributed to "ceo"), duplicating `pipeline.process` text and leaking the review model's raw tokens. | `app/api/websocket.py:111-115` |
| Repeating (routines) | `scheduler.run_routine` / `standup` call `broadcast_event` directly with no coordination; a routine can speak over a live task. | `app/services/scheduler.py:166`; `app/services/standup.py` |
| Late | `ceo_node` runs the CEO model to full completion before emitting any visible text; short prompts route to non-streaming Gemini `generate_content`. | `app/graph/nodes/ceo.py:43`; `app/agents/runner.py:514` |

**Core architectural gap:** there is no notion of "whose turn it is to speak." Work can be parallel, but speech must be serialized — and it isn't.

**Latent bug folded in:** `NexusState.worker_results` is never populated. The worker subgraph returns `result`/`new_artifacts` (WorkerState keys), which do not map to the parent's `worker_results`. So `ceo_review_node` always sees `(no results yet)` and returns `done` — the review feature is effectively dead. The CEO wrap-up cannot summarize work without fixing this.

## Decisions

1. **Execution/speaking model:** parallel work, **CEO-only voice**. Workers run concurrently and report silently; only the CEO speaks aloud.
2. **Run conflicts:** **FIFO queue** — accept new tasks, run one at a time, and **notify the user** when their task is queued behind a running one. Routines queue behind user tasks.
3. **Latency:** **immediate ack + streamed CEO** planning.
4. **Conclusion:** **CEO spoken wrap-up** summarizing what the silent workers produced.

## Design

### A. CEO-only voice
- **Server-side audio gate:** audio (`bark_client.speak` / `{type:"audio"}` send) is emitted only when `agent_id == "ceo"`. Implemented in `pipeline.process` (or the `SPEAK`/`SING` handlers): for non-CEO agents, skip TTS and the audio message but keep returning display text.
- Workers continue to send their **text** `{type:"assistant"}` message plus `worker_step`/`worker_checkpoint`/`worker_done` status — silent, not spoken.
- **Prompt cleanup:** keep the mandatory `[SPEAK:]` instruction for the CEO only; worker personas/Gemini prompt instruct text-only reporting. Belt-and-suspenders with the server gate.
- Result: even with N parallel workers, there is exactly one possible voice.

### B. Global serial run queue + "queued" notice
- A single **global FIFO executor** (one async consumer task) — the company runs one task at a time across the whole app (matches the single shared audio output).
- User messages and scheduler/standup routines **enqueue** here instead of calling the graph / `broadcast_event` directly.
- On enqueue, if a run is already active, immediately broadcast `{type:"queued", position:N, task:…, agent:"ceo"}` so the user knows their task is waiting.
- `cancel_worker` cancels the current run; `clear` cancels the current run and flushes the queue.
- Replaces the `_active_runs[thread_id] = t` overwrite that orphaned in-flight runs.

### C. De-duplicate emission
- Remove the `on_chat_model_stream → {type:"assistant"}` branch in `_translate_event` (`app/api/websocket.py:111-115`). `pipeline.process` becomes the single canonical text emitter. CEO streaming is handled explicitly in (D), not via this generic branch.

### D. Immediate ack + streamed CEO
- On message receipt (before any model call), instantly broadcast a CEO `{type:"assistant", message:{content:[{type:"text", text:"On it — planning…"}]}}` (text only, no TTS latency).
- Switch the CEO turn to streaming:
  - Claude path: stop suppressing intermediate assistant text for the CEO in `run_claude_agent` (`app/agents/runner.py:387-389`) — stream text blocks as `{type:"assistant"}`.
  - Gemini path: use streaming generation for the CEO turn, emitting text as it arrives.
- The CEO's spoken `[SPEAK:]` audio still plays once when the reply completes (via the audio gate in A).

### E. CEO spoken wrap-up + worker_results fix
- **State fix:** introduce a shared reducer key. The worker subgraph emits `worker_results: [{"agent": id, "result": text}]` with `Annotated[list, operator.add]` in `WorkerState`, so values merge into `NexusState.worker_results`.
- **Replace** `ceo_review_node` with a **CEO wrap-up node**: runs the CEO agent over the collected `worker_results` to speak a short summary of what the team produced (CEO voice via the audio gate).
- The wrap-up node is **terminal** — `route_after_review`'s revise/`delegate_more` loop back to `ceo_node` is removed. This eliminates the unbounded cycle risk that would become live once `worker_results` actually populates.

## Out of Scope

- Per-session run isolation (decided: global queue).
- Reworking worker personas beyond the speech-instruction change.
- Browser-svc / email-graph behavior, unless touched incidentally by the audio gate.

## Testing

Extend existing suites (`tests/test_pipeline.py`, `test_delegation.py`, `test_websocket.py`, `test_standup.py`):

- **Audio gate:** worker `[SPEAK:]` → no `{type:"audio"}` emitted; CEO `[SPEAK:]` → audio emitted exactly once.
- **Queue:** two rapid messages run in order; the second triggers a `{type:"queued"}` notice; a routine firing during an active run is queued, not concurrent.
- **Dedup:** a CEO turn yields exactly one assistant text stream source (no `on_chat_model_stream` duplicate; no review-model token leak).
- **worker_results:** populated with one entry per delegated worker after a multi-delegation run.
- **Wrap-up:** runs once after workers complete, speaks (CEO audio), and is terminal (no loop back to `ceo_node`).
