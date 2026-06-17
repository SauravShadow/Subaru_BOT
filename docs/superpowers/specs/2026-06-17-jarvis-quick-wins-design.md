# JARVIS Quick Wins — Design Spec

**Date:** 2026-06-17
**Status:** Approved for planning
**Source roadmap:** `docs/superpowers/specs/2026-06-16-jarvis-autonomy-upgrade-roadmap.md` (Section H — Quick Wins)

---

## Goal

Ship the **reality-verified** subset of the roadmap's "Quick Wins" — low-effort, high-value
changes with no architectural risk — as the first increment of the NEXUS → JARVIS upgrade.
Each subtask is independently testable. **Execution protocol:** implement ONE subtask, verify
its functionality (tests + a live check), get the user's OK, then move to the next.

## Background: reality check (why this differs from the roadmap)

The roadmap listed 6 quick wins. Verifying each against the actual code found several
inaccurate or already-done:

| Roadmap item | Verified state | Decision |
|---|---|---|
| #1 `max_revision_loops` guard | **Moot** — compiled graph is linear (`ceo→workers→wrapup→END`); `review.py`/`ceo_verdict` exist in state but are **not wired in**. No loop exists. | **Out of scope.** Wiring a real review/revise loop is a feature → defer to Phase 1/2. |
| #2 tool buffer 8000→32000 | Valid — `_truncate_content(max_chars=8000)` `runner.py:32` | **In** (Subtask 1) |
| #3 shared-memory injection | Partial — `get_relevant_memories` already queries `agent_id IN (?, 'shared')` | **In** (Subtask 3) — verify/ensure wiring |
| #4 routine log 2000→10000 | Valid — `_append_run_log` cuts `output[:2000]` `scheduler.py:66` | **In** (Subtask 1) |
| #5 health probe | ~Done — `/api/health` probes bark+browser in parallel | **In** (Subtask 2) — add sidecar, make registry-driven |
| #6 env-tunable constants | Partial — `CALL_SILENCE_MS` done; `MAX_HISTORY`/`_ASK_TIMEOUT` plain; **`MAX_TURNS` does not exist** | **In** (Subtask 1) |

## Scope

**In scope:** 3 subtasks (below). **Out of scope:** review/revise loop (deferred), and any
roadmap phase work. `MAX_TURNS` is dropped (does not exist).

## Scalability decisions

These quick wins establish patterns the rest of the roadmap will reuse, so they are designed
to scale:

1. **Typed env helpers** (not flat `os.environ.get`, not `pydantic-settings`). Add
   `_env_int/_env_float/_env_bool/_env_str` to `config.py`. Rationale: the roadmap will add
   many tunables; helpers give one consistent, type-safe, validated pattern with zero new
   dependencies. `pydantic-settings` is not installed and would be a larger refactor (YAGNI).
2. **Registry-driven health** — replace hardcoded bark/browser probes with a `_HEALTH_SERVICES`
   registry probed via `asyncio.gather`. Adding a service becomes one line.
3. **Bounded memory injection** — keep the existing `limit=N` cap so prompt size stays bounded
   as memory grows (semantic/embedding scaling is a later phase, explicitly not here).

---

## Subtask 1 — Config centralization (typed, env-overridable limits)

**What:** Introduce typed env helpers in `config.py` and route hardcoded limits through them.

**Helpers (new, in `config.py`):**
```python
def _env_int(name, default):   return int(os.environ.get(name, default))
def _env_float(name, default): return float(os.environ.get(name, default))
def _env_bool(name, default):  return os.environ.get(name, "1" if default else "0") == "1"
def _env_str(name, default):   return os.environ.get(name, default)
```
Each wraps the cast in a try/except that falls back to the default and logs a warning on a
bad value (so a typo in `.env` can't crash startup).

**New config settings (with env names + current default):**
| Setting | Env var | Default | Replaces |
|---|---|---|---|
| `MAX_TOOL_OUTPUT_CHARS` | `MAX_TOOL_OUTPUT_CHARS` | `32000` | `_truncate_content` literal `8000` |
| `ROUTINE_LOG_MAX_CHARS` | `ROUTINE_LOG_MAX_CHARS` | `10000` | `scheduler.py:66` literal `2000` |
| `MAX_HISTORY` | `MAX_HISTORY` | `30` | plain constant |
| `ASK_TIMEOUT` | `ASK_TIMEOUT` | `120` | `runner.py:41` `_ASK_TIMEOUT` |

**Edits:**
- `app/config.py` — add helpers + the 4 settings; migrate existing `MAX_HISTORY`,
  `CALL_SILENCE_MS` to use the helpers (consistency).
- `app/agents/runner.py` — `_truncate_content` default → `config.MAX_TOOL_OUTPUT_CHARS`;
  `_ASK_TIMEOUT` → `config.ASK_TIMEOUT`.
- `app/services/scheduler.py:66` — `output[:2000]` → `output[:config.ROUTINE_LOG_MAX_CHARS]`.

**Verification:**
- Unit tests: each helper returns default when env unset, parses when set, falls back +
  warns on a bad value.
- Live: set `MAX_TOOL_OUTPUT_CHARS=50` in env, confirm truncation kicks in earlier; unset →
  large output passes. Confirm a routine log keeps >2000 chars.
- Regression: existing call/runner tests still pass.

---

## Subtask 2 — Health probe completeness (registry-driven)

**What:** Make `/api/health` registry-driven and add the SRE operations sidecar (+ surface
Telnyx config readiness).

**Edits (`app/api/router.py`):**
- Add `SIDECAR_URL` to config via `_env_str`, default `http://host.docker.internal:3030`
  (the operations sidecar; verified live with a working `/health` returning 200).
- Define `_HEALTH_SERVICES = {"bark": f"{config.BARK_SVC_URL}/health", "browser":
  f"{config.BROWSER_SVC_URL}/health", "sidecar": f"{config.SIDECAR_URL}/health"}`.
- Probe all via `asyncio.gather` in a loop; build the response dict from the registry.
- Keep `email` (config-derived) and add `telephony` (Telnyx keys present) as config flags.

**Verification:**
- Unit test: `/api/health` returns a key per registered service; a service whose probe fails
  reports `false` while `app` stays `true` (patch `_probe_service`).
- Live: `curl 127.0.0.1:3031/api/health` shows `sidecar` status; matches `docker ps`.

---

## Subtask 3 — Shared-memory injection into every agent prompt

**What:** Confirm and, if needed, ensure the `shared` memory pool is injected into every
agent's prompt (CEO + all workers), not just retrieved.

**Investigation first:** trace where `get_relevant_memories` is called in prompt building
(`runner.py` / prompt builders). It already queries `agent_id IN (?, 'shared')`, so if every
agent prompt calls it, shared memories are already injected — in which case this subtask is a
**verification + test** only. If some agent path skips it, wire it in.

**Edits:** only if a gap is found (e.g. a worker prompt builder that omits memory retrieval).

**Verification:**
- Test: save a `shared` memory; assert it appears in the retrieved set for two different
  agent_ids.
- Live: add a shared memory, run a worker task, confirm it's present in the agent's context
  (log or transcript).

---

## Testing & execution protocol

- Tests run in-container: `docker exec -w /app virtual-company python -m pytest <target> -v`.
- New tests live under `tests/` following existing naming (`test_config_env.py`,
  `test_health.py`, `test_memory_shared.py`).
- Server uses uvicorn `--reload`; live checks via `curl 127.0.0.1:3031/...` and `docker logs`.
- **One subtask at a time.** After each: run its tests + one live check, report results, get
  the user's go-ahead before starting the next. Order: 1 → 2 → 3 (lowest risk first).

## Out of scope / deferred

- CEO review/revise loop (a feature; needs its own spec — Phase 1/2).
- `MAX_TURNS` (does not exist).
- Any roadmap Phase 1–7 work, semantic/embedding memory, real-time event system.
