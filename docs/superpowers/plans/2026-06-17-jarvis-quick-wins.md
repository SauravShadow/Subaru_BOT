# JARVIS Quick Wins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the reality-verified subset of the JARVIS roadmap's Quick Wins — env-tunable limits, a complete/registry-driven health probe, and always-on shared-memory injection.

**Architecture:** Add typed env helpers to `config.py` and route hardcoded limits through them; make `/api/health` iterate a service registry; add an importance-ranked "always inject" shared-memory pull alongside the existing FTS keyword match.

**Tech Stack:** Python 3.12 · FastAPI · SQLite FTS5 · pytest. Tests run in-container: `docker exec -w /app virtual-company python -m pytest <target> -v`. Server uses uvicorn `--reload`.

**Spec:** `docs/superpowers/specs/2026-06-17-jarvis-quick-wins-design.md`

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `app/config.py` | Typed env helpers + new tunable settings | Modify |
| `app/agents/runner.py` | Use `config.MAX_TOOL_OUTPUT_CHARS` / `config.ASK_TIMEOUT`; inject shared memories | Modify |
| `app/services/scheduler.py` | Use `config.ROUTINE_LOG_MAX_CHARS` | Modify |
| `app/api/router.py` | Registry-driven `/api/health` | Modify |
| `app/services/memory.py` | `get_shared_memories()` (importance-ranked, no FTS) | Modify |
| `tests/test_config_env.py` | Env-helper unit tests | Create |
| `tests/test_health.py` | Extend for sidecar/telephony keys | Modify |
| `tests/test_memory.py` | Add shared-pool tests | Modify |

**Execution protocol:** one Task at a time. After each Task, run its tests + the live check, report results, and get the user's go-ahead before the next. Order: 1 → 2 → 3.

---

## Task 1: Config centralization (typed env helpers + tunable limits)

**Files:**
- Modify: `app/config.py`
- Modify: `app/agents/runner.py:32` (`_truncate_content`), `app/agents/runner.py:41` (`_ASK_TIMEOUT`)
- Modify: `app/services/scheduler.py:66`
- Test: `tests/test_config_env.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_config_env.py`:
```python
from app import config


def test_env_int_default(monkeypatch):
    monkeypatch.delenv("QW_INT", raising=False)
    assert config._env_int("QW_INT", 7) == 7


def test_env_int_parses(monkeypatch):
    monkeypatch.setenv("QW_INT", "42")
    assert config._env_int("QW_INT", 7) == 42


def test_env_int_bad_falls_back(monkeypatch):
    monkeypatch.setenv("QW_INT", "not-a-number")
    assert config._env_int("QW_INT", 7) == 7


def test_env_float_parses(monkeypatch):
    monkeypatch.setenv("QW_FLOAT", "1.5")
    assert config._env_float("QW_FLOAT", 0.0) == 1.5


def test_env_bool_truthy_and_falsy(monkeypatch):
    monkeypatch.setenv("QW_BOOL", "true")
    assert config._env_bool("QW_BOOL", False) is True
    monkeypatch.setenv("QW_BOOL", "0")
    assert config._env_bool("QW_BOOL", True) is False


def test_new_settings_exist_with_defaults():
    assert config.MAX_TOOL_OUTPUT_CHARS == 32000
    assert config.ROUTINE_LOG_MAX_CHARS == 10000
    assert config.MAX_HISTORY == 30
    assert int(config.ASK_TIMEOUT) == 120
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec -w /app virtual-company python -m pytest tests/test_config_env.py -v`
Expected: FAIL — `AttributeError: module 'app.config' has no attribute '_env_int'`.

- [ ] **Step 3: Add the typed env helpers to `app/config.py`**

At the top of `app/config.py`, change the imports to add logging:
```python
"""Centralised configuration — reads all env vars once at import time."""
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Bad int for %s=%r; using default %d", name, raw, default)
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Bad float for %s=%r; using default %s", name, raw, default)
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)
```

- [ ] **Step 4: Add/migrate the tunable settings in `app/config.py`**

Replace the line `MAX_HISTORY      = 30` with:
```python
MAX_HISTORY      = _env_int("MAX_HISTORY", 30)
```
Replace the line `CALL_SILENCE_MS      = int(os.environ.get("CALL_SILENCE_MS", "1200"))` with:
```python
CALL_SILENCE_MS      = _env_int("CALL_SILENCE_MS", 1200)
```
Add these new settings just below `MAX_HISTORY`:
```python
MAX_TOOL_OUTPUT_CHARS = _env_int("MAX_TOOL_OUTPUT_CHARS", 32000)  # agent tool-output truncation cap
ROUTINE_LOG_MAX_CHARS = _env_int("ROUTINE_LOG_MAX_CHARS", 10000)  # routine run-log output cap
ASK_TIMEOUT           = _env_float("ASK_TIMEOUT", 120.0)          # inter-agent ask timeout (s)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `docker exec -w /app virtual-company python -m pytest tests/test_config_env.py -v`
Expected: PASS (all 6 tests).

- [ ] **Step 6: Wire `runner.py` to the new settings**

In `app/agents/runner.py`, change the `_truncate_content` signature (line ~32) from:
```python
def _truncate_content(text: str, max_chars: int = 8000) -> str:
```
to:
```python
def _truncate_content(text: str, max_chars: int = config.MAX_TOOL_OUTPUT_CHARS) -> str:
```
Change the `_ASK_TIMEOUT` constant (line ~41) from:
```python
_ASK_TIMEOUT: float = 120.0   # seconds before inter-agent ask times out
```
to:
```python
_ASK_TIMEOUT: float = config.ASK_TIMEOUT   # seconds before inter-agent ask times out
```
(`from app import config` is already imported at the top of `runner.py`.)

- [ ] **Step 7: Wire `scheduler.py` to the new setting**

In `app/services/scheduler.py` (`from app import config` is already imported at line 17), change the line `"output":     output[:2000],` (line ~66) to:
```python
        "output":     output[:config.ROUTINE_LOG_MAX_CHARS],
```

- [ ] **Step 8: Run the broader suite to confirm no regressions**

Run: `docker exec -w /app virtual-company python -m pytest tests/test_config_env.py tests/ -k 'call or config or memory or health' -q`
Expected: PASS (no failures).

- [ ] **Step 9: Live verification**

Confirm the server reloaded clean:
`docker logs virtual-company --tail 8 2>&1 | grep -iE 'startup complete|Error'` → shows "Application startup complete", no errors.
Sanity-check the values are importable:
`docker exec -w /app virtual-company python -c "from app import config; print(config.MAX_TOOL_OUTPUT_CHARS, config.ROUTINE_LOG_MAX_CHARS, int(config.ASK_TIMEOUT))"`
Expected output: `32000 10000 120`

- [ ] **Step 10: Commit**

```bash
git add app/config.py app/agents/runner.py app/services/scheduler.py tests/test_config_env.py
git commit -m "feat(config): typed env helpers + env-tunable output/log/history/timeout limits

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Health probe completeness (registry-driven + sidecar)

**Files:**
- Modify: `app/config.py` (add `SIDECAR_URL`)
- Modify: `app/api/router.py:540` (`api_health`)
- Test: `tests/test_health.py`

- [ ] **Step 1: Update the failing test**

Replace the body of `tests/test_health.py` with:
```python
import pytest
from httpx import AsyncClient, ASGITransport


@pytest.mark.asyncio
async def test_health_reports_all_services(monkeypatch):
    from app.api import router as router_module

    async def fake_probe(url: str) -> bool:
        return "bark" in url  # bark up; browser + sidecar down

    monkeypatch.setattr(router_module, "_probe_service", fake_probe)

    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router_module.router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/health")

    assert res.status_code == 200
    body = res.json()
    assert body["app"] is True
    assert body["bark"] is True
    assert body["browser"] is False
    assert body["sidecar"] is False        # new: probed via registry
    assert "email" in body                 # config-derived flag
    assert "telephony" in body             # new: config-derived flag
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec -w /app virtual-company python -m pytest tests/test_health.py -v`
Expected: FAIL — `KeyError: 'sidecar'` (current endpoint has no sidecar key).

- [ ] **Step 3: Add `SIDECAR_URL` to `app/config.py`**

Below the `BROWSER_SVC_URL` line, add:
```python
SIDECAR_URL = _env_str("SIDECAR_URL", "http://host.docker.internal:3030")  # SRE operations sidecar
```

- [ ] **Step 4: Make `/api/health` registry-driven in `app/api/router.py`**

Replace the `api_health` function (starts at line ~540) with:
```python
_HEALTH_SERVICES = {
    "bark":    f"{config.BARK_SVC_URL}/health",
    "browser": f"{config.BROWSER_SVC_URL}/health",
    "sidecar": f"{config.SIDECAR_URL}/health",
}


@router.get("/api/health")
async def api_health():
    names = list(_HEALTH_SERVICES)
    results = await asyncio.gather(
        *(_probe_service(_HEALTH_SERVICES[n]) for n in names)
    )
    health = {"app": True}
    health.update(dict(zip(names, results)))
    health["email"]     = all([config.SMTP_USER, config.SMTP_PASS, config.USER_EMAIL])
    health["telephony"] = all([config.TELNYX_API_KEY, config.TELNYX_CONNECTION_ID,
                               config.TELNYX_PHONE_NUMBER])
    return health
```

- [ ] **Step 5: Run test to verify it passes**

Run: `docker exec -w /app virtual-company python -m pytest tests/test_health.py -v`
Expected: PASS.

- [ ] **Step 6: Live verification**

Run: `curl -s http://127.0.0.1:3031/api/health` (after reload).
Expected: JSON with keys `app, bark, browser, sidecar, email, telephony`. Cross-check `sidecar` is `true` (sidecar is up on host:3030) and `bark`/`browser` are `true`.

- [ ] **Step 7: Commit**

```bash
git add app/config.py app/api/router.py tests/test_health.py
git commit -m "feat(health): registry-driven /api/health with sidecar + telephony status

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Always-inject shared memory pool

The existing `get_relevant_memories` includes the `shared` pool but only via FTS keyword
match — a shared fact is dropped if it doesn't match the query (or the query is empty). Add an
importance-ranked pull that is always injected, deduped against the keyword matches.

**Files:**
- Modify: `app/services/memory.py` (add `get_shared_memories`)
- Modify: `app/agents/runner.py:135` (`_build_context_block`)
- Test: `tests/test_memory.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_memory.py` (the `mem` fixture already exists in this file):
```python
def test_get_shared_memories_ranks_by_importance(mem):
    mem.save_memory("shared", "Company mission: ship reliable agents", importance=0.9)
    mem.save_memory("shared", "Minor shared note", importance=0.2)
    results = mem.get_shared_memories(limit=5)
    assert any("mission" in r for r in results)
    assert results[0] == "Company mission: ship reliable agents"  # highest importance first


def test_get_shared_memories_ignores_non_shared(mem):
    mem.save_memory("ceo", "CEO-only private note", importance=0.9)
    mem.save_memory("shared", "Shared broadcast note", importance=0.5)
    results = mem.get_shared_memories(limit=5)
    assert any("broadcast" in r for r in results)
    assert not any("private" in r for r in results)


def test_get_shared_memories_no_keyword_needed(mem):
    # Unlike get_relevant_memories, this needs no query/keyword match.
    mem.save_memory("shared", "Zzxq unrelated token", importance=0.7)
    results = mem.get_shared_memories(limit=5)
    assert any("Zzxq" in r for r in results)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec -w /app virtual-company python -m pytest tests/test_memory.py -k shared -v`
Expected: FAIL — `AttributeError: module 'app.services.memory' has no attribute 'get_shared_memories'`.

- [ ] **Step 3: Implement `get_shared_memories` in `app/services/memory.py`**

Add after `get_relevant_memories`:
```python
def get_shared_memories(limit: int = 3) -> list[str]:
    """Top shared memories by importance — ALWAYS injectable (no keyword match needed)."""
    try:
        with _conn() as c:
            rows = c.execute("""
                SELECT content
                FROM   memories
                WHERE  agent_id = 'shared'
                ORDER  BY importance DESC, last_hit_at DESC
                LIMIT  ?
            """, (limit,)).fetchall()
            return [r["content"] for r in rows]
    except sqlite3.OperationalError as exc:
        logger.warning("shared memory query failed: %s", exc)
        return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec -w /app virtual-company python -m pytest tests/test_memory.py -k shared -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Inject shared memories into every prompt via `_build_context_block`**

In `app/agents/runner.py`, replace the body of `_build_context_block` (line ~135) with:
```python
def _build_context_block(agent_id: str, user_query: str) -> str:
    """Live context injected into every agent prompt."""
    try:
        import datetime as _dt
        matched = mem_svc.get_relevant_memories(agent_id, user_query, limit=5)
        shared  = mem_svc.get_shared_memories(limit=3)
        # Always include top shared facts; dedupe against keyword matches, preserve order.
        seen, merged = set(), []
        for m in matched + shared:
            if m not in seen:
                seen.add(m)
                merged.append(m)
        now_str   = _dt.datetime.now(_IST).strftime("%A %d %B %Y, %H:%M IST")
        mem_lines = "\n".join(f"  - {m}" for m in merged) or "  (none yet)"
        return (
            f"\nLIVE CONTEXT [{now_str}]:\n"
            f"Relevant memories:\n{mem_lines}\n"
        )
    except Exception:
        return ""
```

- [ ] **Step 6: Write a test proving shared memory reaches the context block without a keyword match**

Append to `tests/test_memory.py`:
```python
def test_context_block_includes_shared_without_keyword(mem, monkeypatch):
    import app.agents.runner as runner
    monkeypatch.setattr(runner, "mem_svc", mem)
    mem.save_memory("shared", "Always-on fact: prefer Engine B for calls", importance=0.9)
    block = runner._build_context_block("backend", "totally unrelated query about widgets")
    assert "Always-on fact" in block
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `docker exec -w /app virtual-company python -m pytest tests/test_memory.py -k 'shared or context' -v`
Expected: PASS.

- [ ] **Step 8: Run the broader suite + live check**

Run: `docker exec -w /app virtual-company python -m pytest tests/test_memory.py tests/ -k 'memory or config or health or call' -q`
Expected: PASS.
Live: `docker logs virtual-company --tail 6 2>&1 | grep -iE 'startup complete|Error'` → clean reload.

- [ ] **Step 9: Commit**

```bash
git add app/services/memory.py app/agents/runner.py tests/test_memory.py
git commit -m "feat(memory): always-inject importance-ranked shared memory pool into agent prompts

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Done criteria

- All three Tasks committed; `tests/` green for config/health/memory/call selectors.
- `/api/health` reports `sidecar` + `telephony`.
- `MAX_TOOL_OUTPUT_CHARS`, `ROUTINE_LOG_MAX_CHARS`, `MAX_HISTORY`, `ASK_TIMEOUT`, `CALL_SILENCE_MS`, `SIDECAR_URL` all env-overridable.
- A high-importance `shared` memory appears in agent context regardless of query keywords.
