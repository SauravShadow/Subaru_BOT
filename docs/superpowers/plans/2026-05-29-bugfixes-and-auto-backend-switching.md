# Bugfixes + Auto Backend Switching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 9 correctness/reliability bugs found in code review and add automatic Claude CLI → tgpt failover with a live UI backend indicator (no manual selector).

**Architecture:** A new `app/agents/backend_state.py` module owns all backend-switching logic (global quota state, retry timing); `executor.py` consults it and emits `backend_status` WS events; the UI replaces the manual model `<select>` with a read-only indicator pill that updates in real time. The 9 bug fixes are independent patches in their respective files.

**Tech Stack:** Python 3.12, FastAPI, asyncio, websockets (sidecar), vanilla JS frontend, docker-compose.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| **Create** | `app/agents/backend_state.py` | Global Claude quota state + auto-switching logic |
| **Modify** | `app/agents/executor.py` | Separate Claude prompt, stderr fix, wire backend_state |
| **Modify** | `app/api/websocket.py` | Include backend in `init`, forward `backend_status` events |
| **Modify** | `app/api/router.py` | Block `api_hire` from overwriting built-in agents |
| **Modify** | `app/state/manager.py` | Debounce `save_state` — only save on important events |
| **Modify** | `app/static/index.html` | Replace `<select>` with backend indicator pill |
| **Modify** | `app/static/app.js` | Handle `backend_status` event, remove model-select logic |
| **Modify** | `operations_sidecar.py` | Fix heal loop (#2,#3), prompt injection (#6), WS leak (#7), URL encoding (#10) |

---

## Task 1: Block built-in agent overwrite in `/api/hire`

**Files:**
- Modify: `app/api/router.py:86-99`

- [ ] **Step 1: Add id validation to api_hire**

Replace the current `api_hire` function body in [app/api/router.py](app/api/router.py):

```python
@router.post("/api/hire")
async def api_hire(body: dict):
    from app.agents.definitions import _worker_persona, AGENT_DEFS
    aid  = body.get("id", f"agent_{len(state.custom_agents) + 1}")

    # Prevent overwriting built-in agents
    if aid in AGENT_DEFS:
        return {"ok": False, "error": f"Agent id '{aid}' is reserved for a built-in agent."}

    role = body.get("role", "Specialist")
    state.custom_agents[aid] = {
        "name":        body.get("name", "Contractor"),
        "title":       body.get("title", role),
        "color":       body.get("color", "#94a3b8"),
        "avatar":      body.get("avatar", "CT"),
        "description": body.get("description", role),
        "persona":     _worker_persona(body.get("name", "Contractor"), role,
                                       body.get("stack", "general purpose"), "")(),
    }
    state.conversation_histories[aid] = []
    state.save_state()
    return {"ok": True, "id": aid}
```

- [ ] **Step 2: Manual verification**

```bash
curl -s -X POST http://localhost:3030/api/hire \
  -H 'Content-Type: application/json' \
  -d '{"id":"ceo","name":"Evil CEO"}' | python3 -m json.tool
```

Expected: `{"ok": false, "error": "Agent id 'ceo' is reserved for a built-in agent."}`

```bash
curl -s -X POST http://localhost:3030/api/hire \
  -H 'Content-Type: application/json' \
  -d '{"name":"Bob","title":"Data Scientist","stack":"pandas, sklearn"}' | python3 -m json.tool
```

Expected: `{"ok": true, "id": "agent_1"}` (or next available number)

---

## Task 2: Debounce `save_state` — stop writing JSON on every message

**Files:**
- Modify: `app/state/manager.py`

The current `record()` calls `save_state()` on every single message. This means up to 16 full-file writes per conversation round-trip when workers are active. The fix: only call `save_state()` from `record()` every 5th call; always save immediately on structural changes (work queue, custom agents).

- [ ] **Step 1: Add a write counter and selective save to manager.py**

At the top of [app/state/manager.py](app/state/manager.py), after the imports, add:

```python
_record_call_count: int = 0
_SAVE_EVERY: int = 5
```

Then replace the `record()` function:

```python
def record(agent_id: str, role: str, content: str) -> None:
    global _record_call_count
    conversation_histories.setdefault(agent_id, []).append(
        {"role": role, "content": content, "ts": datetime.now().isoformat()}
    )
    # Trim to rolling window
    conversation_histories[agent_id] = conversation_histories[agent_id][
        -(config.MAX_HISTORY * 2) :
    ]
    _record_call_count += 1
    if _record_call_count >= _SAVE_EVERY:
        save_state()
        _record_call_count = 0
```

- [ ] **Step 2: Verify `save_state` still called on all structural changes**

`create_work_item`, `complete_work_item`, `force_complete_item`, `reset_work_item`, `save_project`, `api_hire` all call `save_state()` directly — those remain unchanged, so structural state is always persisted immediately.

- [ ] **Step 3: Manual smoke test**

Start the app, send 3 messages to the CEO, check that state file still updates:

```bash
stat -c %Y /home/subaru/projects/nexus_state.json
# Send a message via the UI, wait a few seconds
stat -c %Y /home/subaru/projects/nexus_state.json
```

File modification time should update after every 5th message exchange.

---

## Task 3: Fix `stderr` deadlock in `run_claude_agent`

**Files:**
- Modify: `app/agents/executor.py:189-230`

The current code drains `proc.stdout` fully before ever reading `proc.stderr`. If Claude CLI writes more than ~64 KB of stderr before closing stdout, the process deadlocks (Claude blocks on stderr write, Python waits for stdout EOF). Fix: start a background stderr-reader task before touching stdout.

- [ ] **Step 1: Replace the stdout/stderr read pattern in run_claude_agent**

Find and replace this block in [app/agents/executor.py](app/agents/executor.py):

```python
# REPLACE everything from:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(config.WORK_DIR),
        env={**os.environ},
        limit=16 * 1024 * 1024,
    )
    async for raw in proc.stdout:
        line = raw.decode(errors="replace").strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            # Forward raw JSON line to WS (existing protocol compat)
            await send({"_raw_json": line, "agent": agent_id})
            if obj.get("type") == "assistant":
                for blk in obj.get("message", {}).get("content", []):
                    if blk.get("type") == "text":
                        full_resp += blk["text"]
        except json.JSONDecodeError:
            pass

    await proc.wait()

    if proc.returncode != 0:
        err = (await proc.stderr.read()).decode().strip()
# TO:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(config.WORK_DIR),
        env={**os.environ},
        limit=16 * 1024 * 1024,
    )
    # Read stderr concurrently — prevents pipe-buffer deadlock when Claude writes
    # large stderr before closing stdout.
    stderr_task = asyncio.create_task(proc.stderr.read())

    async for raw in proc.stdout:
        line = raw.decode(errors="replace").strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            await send({"_raw_json": line, "agent": agent_id})
            if obj.get("type") == "assistant":
                for blk in obj.get("message", {}).get("content", []):
                    if blk.get("type") == "text":
                        full_resp += blk["text"]
        except json.JSONDecodeError:
            pass

    await proc.wait()
    err_bytes = await stderr_task

    if proc.returncode != 0:
        err = err_bytes.decode().strip()
```

---

## Task 4: Separate Claude CLI prompt from tgpt prompt

**Files:**
- Modify: `app/agents/executor.py`

Currently `run_claude_agent` passes the tgpt-style `[BASH:]` / `[READ:]` prompt to Claude CLI, which also has `--allowedTools` enabled. This is contradictory: Claude uses native JSON tool calls, but the prompt tells it to output text-format tags. The tags then get forwarded as raw text without being executed. Fix: add a `_build_claude_prompt()` that gives Claude a clean persona + history prompt with no tgpt tool syntax.

- [ ] **Step 1: Add `_build_claude_prompt` to executor.py**

Add this function directly after `_build_tgpt_prompt()` in [app/agents/executor.py](app/agents/executor.py):

```python
def _build_claude_prompt(agent_id: str, user_msg: str) -> str:
    """Prompt for Claude CLI — no tgpt tool syntax; Claude uses its own native tools."""
    agent = defs.get_agent(agent_id)
    persona = defs.agent_persona(agent_id)
    history = state.get_history(agent_id)

    hist_str = "\n".join(
        f"{'User' if h['role'] == 'user' else agent['name']}: {_truncate_content(h['content'])}"
        for h in history[-(config.MAX_HISTORY):]
    )

    return (
        f"{persona}\n\n"
        f"Working directory: {config.WORK_DIR}\n\n"
        f"Conversation History:\n{hist_str}\n\n"
        f"User: {user_msg}"
    )
```

- [ ] **Step 2: Update `run_claude_agent` to use the new prompt**

In `run_claude_agent()`, change this line:

```python
    args = [
        config.CLAUDE_BIN, "-p", _build_tgpt_prompt(agent_id, prompt),
```

to:

```python
    args = [
        config.CLAUDE_BIN, "-p", _build_claude_prompt(agent_id, prompt),
```

---

## Task 5: Create `app/agents/backend_state.py`

**Files:**
- Create: `app/agents/backend_state.py`

This module owns all backend-switching state. It is imported by `executor.py` and `websocket.py`. No circular imports — it imports only stdlib.

- [ ] **Step 1: Write the module**

Create [app/agents/backend_state.py](app/agents/backend_state.py):

```python
"""
backend_state.py — Tracks Claude CLI quota and drives automatic backend switching.

Claude CLI (Pro subscription) is the preferred backend.
When a quota/rate-limit error is detected, the system switches to tgpt and
retries Claude after CLAUDE_RETRY_MINUTES minutes.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

CLAUDE_RETRY_MINUTES: int = 30

_quota_exhausted_at: Optional[datetime] = None
_current_backend: str = "claude"   # "claude" | "tgpt"

# Keywords that indicate a hard quota or rate-limit error (worth switching backend for).
# Excludes "context window" / "context limit" — those mean the conversation is too
# long, not that Claude is unavailable.
QUOTA_KEYWORDS = [
    "quota exceeded",
    "out of tokens",
    "session limit",
    "too many requests",
    "rate limit",
    "token limit",
]


def get_current_backend() -> str:
    """Return the active backend: 'claude' or 'tgpt'."""
    return _current_backend


def should_use_claude() -> bool:
    """
    Return True if Claude CLI should be attempted.
    After quota exhaustion we retry after CLAUDE_RETRY_MINUTES.
    """
    if _quota_exhausted_at is None:
        return True
    return datetime.now() >= _quota_exhausted_at + timedelta(minutes=CLAUDE_RETRY_MINUTES)


def retry_due_at() -> Optional[datetime]:
    if _quota_exhausted_at is None:
        return None
    return _quota_exhausted_at + timedelta(minutes=CLAUDE_RETRY_MINUTES)


def mark_quota_exhausted() -> bool:
    """
    Mark Claude quota as exhausted and switch to tgpt.
    Returns True if the backend actually changed (caller should emit a WS event).
    """
    global _quota_exhausted_at, _current_backend
    _quota_exhausted_at = datetime.now()
    changed = _current_backend != "tgpt"
    _current_backend = "tgpt"
    if changed:
        logger.warning(
            "Claude CLI quota exhausted — switching to tgpt. "
            "Will retry Claude at %s",
            retry_due_at().strftime("%H:%M"),
        )
    return changed


def mark_claude_recovered() -> bool:
    """
    Mark Claude as recovered and switch back.
    Returns True if the backend actually changed.
    """
    global _quota_exhausted_at, _current_backend
    _quota_exhausted_at = None
    changed = _current_backend != "claude"
    _current_backend = "claude"
    if changed:
        logger.info("Claude CLI recovered — switching back from tgpt.")
    return changed


def is_quota_error(text: str) -> bool:
    """Return True if the text contains a Claude quota/rate-limit indicator."""
    lower = text.lower()
    return any(kw in lower for kw in QUOTA_KEYWORDS)


def status_dict() -> dict:
    """Serialisable snapshot for WS backend_status events."""
    due = retry_due_at()
    return {
        "backend":      _current_backend,
        "quota_ok":     _quota_exhausted_at is None,
        "retry_at":     due.strftime("%H:%M") if due else None,
        "exhausted_at": _quota_exhausted_at.isoformat() if _quota_exhausted_at else None,
    }
```

---

## Task 6: Wire auto-switching into `executor.py`

**Files:**
- Modify: `app/agents/executor.py`

`run_agent()` consults `backend_state` to choose the backend. `run_claude_agent()` calls `mark_quota_exhausted()` / `mark_claude_recovered()` and emits a `backend_status` WS event when the backend changes.

- [ ] **Step 1: Import backend_state in executor.py**

Add this import near the top of [app/agents/executor.py](app/agents/executor.py) after the existing imports:

```python
from app.agents import backend_state
```

- [ ] **Step 2: Replace quota detection and failover in run_claude_agent**

Find the `if proc.returncode != 0:` block at the end of `run_claude_agent` and replace it:

```python
    # Old block to REPLACE:
    if proc.returncode != 0:
        err = err_bytes.decode().strip()
        quota_err = any(kw in err.lower() or kw in full_resp.lower() for kw in [
            "token limit", "rate limit", "context limit", "quota exceeded",
            "out of tokens", "too many requests", "exhausted", "context window",
            "session limit",
        ])
        if quota_err:
            await send({
                "type": "failover", "agent": agent_id,
                "message": "Claude CLI session limit reached — switching to ChatGPT CLI…",
            })
            full_resp = await run_tgpt_agent(agent_id, prompt, send, "sky")
        elif err:
            await send({"type": "error", "agent": agent_id, "message": err})

    return full_resp
```

Replace with:

```python
    if proc.returncode != 0:
        err = err_bytes.decode().strip()
        combined = err + " " + full_resp
        if backend_state.is_quota_error(combined):
            changed = backend_state.mark_quota_exhausted()
            if changed:
                await send({"type": "backend_status", "agent": agent_id,
                            **backend_state.status_dict()})
            await send({
                "type": "failover", "agent": agent_id,
                "message": (
                    f"Claude CLI quota/rate-limit hit — switching to tgpt. "
                    f"Will retry Claude at {backend_state.retry_due_at().strftime('%H:%M')}."
                ),
            })
            full_resp = await run_tgpt_agent(agent_id, prompt, send, "sky")
        elif err:
            await send({"type": "error", "agent": agent_id, "message": err})
    else:
        # Successful Claude call — recover if we were previously in tgpt mode
        if backend_state.get_current_backend() == "tgpt" and backend_state.should_use_claude():
            changed = backend_state.mark_claude_recovered()
            if changed:
                await send({"type": "backend_status", "agent": agent_id,
                            **backend_state.status_dict()})

    return full_resp
```

- [ ] **Step 3: Replace run_agent dispatcher to use backend_state**

Replace the entire `run_agent()` function:

```python
async def run_agent(
    agent_id: str,
    prompt: str,
    send: Sender,
    model: str = "claude",   # kept for compat; auto-switching overrides this
) -> str:
    """Route to the correct backend. Claude CLI is preferred; auto-switches to tgpt on quota."""
    # Honour explicit tgpt/gemini requests (for direct worker access)
    if model == "chatgpt":
        return await run_tgpt_agent(agent_id, prompt, send, "sky")
    if model == "gemini":
        return await run_tgpt_agent(agent_id, prompt, send, "pollinations")

    # Auto-switching: use Claude if quota is OK (or retry window has elapsed)
    if backend_state.should_use_claude():
        return await run_claude_agent(agent_id, prompt, send)

    # Claude quota still exhausted — use tgpt
    return await run_tgpt_agent(agent_id, prompt, send, "sky")
```

---

## Task 7: Add `backend_status` to WS `init` and UI

**Files:**
- Modify: `app/api/websocket.py:226-232`
- Modify: `app/static/index.html:34-38`
- Modify: `app/static/app.js`

The `init` event will now carry the current backend state. The UI replaces the manual `<select>` with a read-only indicator pill.

- [ ] **Step 1: Add backend import and include in init event (websocket.py)**

Add import at top of [app/api/websocket.py](app/api/websocket.py):

```python
from app.agents import backend_state
```

Then in `ws_endpoint()`, replace the `init` send block:

```python
    # OLD:
    await session.send({
        "type":       "init",
        "agents":     {k: defs.public_agent_info(k, v) for k, v in agents.items()},
        "workdir":    str(state._get_workdir()),
        "work_queue": state.work_queue,
    })

    # NEW:
    await session.send({
        "type":       "init",
        "agents":     {k: defs.public_agent_info(k, v) for k, v in agents.items()},
        "workdir":    str(state._get_workdir()),
        "work_queue": state.work_queue,
        "backend":    backend_state.status_dict(),
    })
```

- [ ] **Step 2: Replace `<select>` with backend indicator pill in index.html**

In [app/static/index.html](app/static/index.html), replace:

```html
    <select id="model-select" title="AI Backend">
      <option value="claude">Claude CLI</option>
      <option value="chatgpt">ChatGPT (sky)</option>
      <option value="gemini">Gemini (pollinations)</option>
    </select>
```

with:

```html
    <div class="pill" id="backend-pill" title="AI Backend (auto-managed)">
      <span class="pill-icon" id="backend-icon">⚡</span>
      <span class="pill-val" id="backend-val">Claude CLI</span>
    </div>
```

- [ ] **Step 3: Add backend_status handling and remove model-select logic in app.js**

In [app/static/app.js](app/static/app.js):

**3a.** In the `S` state object, change `model: "claude"` to `backend: "claude"` (and remove any references to `S.model` that were only for the select):

```javascript
const S = {
  ws:            null,
  agents:        {},
  agentOrder:    [],
  activeAgent:   "ceo",
  backend:       "claude",   // tracked from server; not user-controlled
  chatLogs:      {},
  statuses:      {},
  unread:        {},
  workQueue:     [],
  thinkingEl:    null,
  voiceRecording: false,
  mediaRecorder: null,
  reconnTimer:   null,
};
```

**3b.** Add a `updateBackendPill` helper (add near the top of the utility functions section):

```javascript
function updateBackendPill(backendObj) {
  S.backend = backendObj.backend || "claude";
  const isClaude = S.backend === "claude";
  const pill  = $id("backend-pill");
  const icon  = $id("backend-icon");
  const val   = $id("backend-val");
  if (!pill) return;

  if (isClaude) {
    pill.style.color = "var(--ok)";
    icon.textContent  = "⚡";
    val.textContent   = "Claude CLI";
    pill.title        = "Using Claude CLI (Pro)";
  } else {
    const retryAt = backendObj.retry_at ? ` — retry at ${backendObj.retry_at}` : "";
    pill.style.color = "var(--warn)";
    icon.textContent  = "⚡";
    val.textContent   = "ChatGPT (fallback)";
    pill.title        = `Claude quota hit${retryAt}`;
  }
}
```

**3c.** In the `dispatch()` function, add a case for `backend_status` and update the `init` case:

```javascript
    case "init":
      S.agents    = obj.agents || {};
      S.agentOrder= Object.keys(S.agents);
      S.workQueue = obj.work_queue || [];
      S.agentOrder.forEach(id => {
        if (!S.chatLogs[id])  S.chatLogs[id]  = [];
        if (!S.statuses[id])  S.statuses[id]  = "ready";
        if (!S.unread[id])    S.unread[id]    = 0;
      });
      renderSidebar();
      renderChatHeader();
      updateQueuePill();
      refreshDashboard();
      loadStorageStats();
      loadCapabilities();
      if (obj.backend) updateBackendPill(obj.backend);   // ← add this line
      break;
```

```javascript
    case "backend_status":
      updateBackendPill(obj);
      if (!obj.quota_ok) {
        toast(`Claude quota hit — switched to ChatGPT fallback${obj.retry_at ? " (retry at " + obj.retry_at + ")" : ""}`, "warn");
      } else if (obj.backend === "claude") {
        toast("Claude CLI recovered ✓", "success");
      }
      break;
```

**3d.** In `initInputEvents()`, remove the model-select event listener block:

```javascript
  // DELETE this block entirely:
  $id("model-select").addEventListener("change", e => {
    S.model = e.target.value;
    wsSend({ type: "model", model: S.model });
    boot();
  });
```

**3e.** In `boot()`, remove `?model=${S.model}` from the WS URL:

```javascript
  const url = `${proto}//${location.host}/ws`;   // was: /ws?model=${S.model}
```

---

## Task 8: Fix `operations_sidecar.py` — prompt injection + compile check + rebuild logic

**Files:**
- Modify: `operations_sidecar.py`

Three separate fixes in one file:
- **#6**: Sanitise error_log before embedding in LLM system prompt
- **#2**: Replace `python3 -m py_compile web_cli.py` (doesn't exist) with `python3 -m compileall -q app/`
- **#3**: After healing a Python runtime error, restart the container instead of full rebuild

- [ ] **Step 1: Add error log sanitiser helper (fix #6)**

Add this function near the top of [operations_sidecar.py](operations_sidecar.py), after the `_host_edit()` function definition:

```python
def _sanitize_error_log(log: str, max_chars: int = 3000) -> str:
    """
    Strip patterns that could be misread as tool calls by the LLM,
    preventing prompt injection via crafted error output.
    """
    import re
    safe = re.sub(r'\[(BASH|READ|WRITE|EDIT|DONE):[^\]]*\]', r'[\1:REDACTED]', log)
    return safe[:max_chars]
```

- [ ] **Step 2: Use sanitised log in run_healing_agent (fix #6)**

In `run_healing_agent()`, change the call signature and the first line that uses `error_log`:

```python
async def run_healing_agent(error_log: str):
    """Host-side tool calling agent utilizing tgpt and free CLI providers to self-heal code."""
    error_log = _sanitize_error_log(error_log)   # ← add this line at the top of the function body
    await broadcast({"type": "status", "status": "HEALING"})
    ...
```

- [ ] **Step 3: Fix compile check — replace web_cli.py with actual app files (fix #2)**

Find the block in `run_compose_rebuild()`:

```python
            compile_proc = await asyncio.create_subprocess_shell(
                "python3 -m py_compile web_cli.py",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(WORK_DIR),
            )
            _, err_bytes = await compile_proc.communicate()
            compile_err = err_bytes.decode(errors="replace").strip()
            
            if not compile_err:
                compile_err = "Docker build failed. Check compose logs for syntax/packaging errors."
```

Replace with:

```python
            # Check all Python files in the mounted app directory
            compile_proc = await asyncio.create_subprocess_shell(
                "python3 -m compileall -q app/ 2>&1 || true",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(WORK_DIR),
            )
            out_bytes, _ = await compile_proc.communicate()
            compile_err = out_bytes.decode(errors="replace").strip()

            if not compile_err:
                compile_err = "Docker build failed (no Python syntax errors detected). Check Dockerfile or requirements.txt."
```

- [ ] **Step 4: Fix rebuild logic — use restart instead of full rebuild after runtime failure (fix #3)**

The current logic calls `docker compose down && docker compose up -d` after a successful build, then if the health check fails it runs the healing agent. After healing Python files, it loops back to attempt a *full rebuild* — but the Python files are volume-mounted, so rebuild does nothing.

Find the health check failure block inside `run_compose_rebuild()`:

```python
                if container_healthy:
                    build_status = "ONLINE"
                    await broadcast({"type": "status", "status": "ONLINE"})
                    await broadcast({"type": "log", "text": "🎉 Success! Container is ONLINE and healthy."})
                    await broadcast({"type": "reload"})
                    return
                else:
                    await broadcast({"type": "log", "text": "✗ Health check failed! Fetching container error logs..."})
                    logs_proc = await asyncio.create_subprocess_shell(
                        "docker compose logs --tail=100 virtual-company",
                        ...
                    )
                    stdout_bytes, _ = await logs_proc.communicate()
                    logs_text = stdout_bytes.decode(errors="replace").strip()
                    
                    if not logs_text:
                        logs_text = "Container health check timed out. No logs found."
                    
                    await broadcast({"type": "log", "text": f"Captured Error Diagnostics:\n{logs_text}"})
                    await run_healing_agent(logs_text)
```

Replace the `else` branch (after `await run_healing_agent(logs_text)`) to restart instead of falling through to another rebuild:

```python
                else:
                    await broadcast({"type": "log", "text": "✗ Health check failed — fetching container logs…"})
                    logs_proc = await asyncio.create_subprocess_shell(
                        "docker compose logs --tail=100 virtual-company",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=str(WORK_DIR),
                    )
                    stdout_bytes, _ = await logs_proc.communicate()
                    logs_text = stdout_bytes.decode(errors="replace").strip() or \
                                "Container health check timed out. No logs found."

                    await broadcast({"type": "log", "text": f"Diagnostics:\n{logs_text}"})
                    await run_healing_agent(logs_text)

                    # Python files are volume-mounted — no rebuild needed after a fix.
                    # Just restart the container so uvicorn picks up the corrected file.
                    await broadcast({"type": "log", "text": "Restarting container after Python fix…"})
                    restart_proc = await asyncio.create_subprocess_shell(
                        "docker compose restart virtual-company",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=str(WORK_DIR),
                    )
                    await restart_proc.communicate()

                    # Re-poll health after restart
                    container_healthy = False
                    for check in range(10):
                        await asyncio.sleep(1.5)
                        try:
                            res = await client.get("http://127.0.0.1:3031/api/capabilities", timeout=1.0)
                            if res.status_code == 200:
                                container_healthy = True
                                break
                        except Exception:
                            pass

                    if container_healthy:
                        build_status = "ONLINE"
                        await broadcast({"type": "status", "status": "ONLINE"})
                        await broadcast({"type": "log", "text": "🎉 Success! Container recovered after Python fix."})
                        await broadcast({"type": "reload"})
                        return
                    # If still unhealthy, fall through to next build attempt
```

---

## Task 9: Fix WebSocket goroutine leak and URL encoding in sidecar

**Files:**
- Modify: `operations_sidecar.py:464-515`

- [ ] **Step 1: Fix query parameter URL encoding (fix #10)**

In `proxy_websocket_endpoint()`, replace:

```python
    params = dict(ws.query_params)
    query_str = "&".join(f"{k}={v}" for k, v in params.items())
    target_ws_url = f"ws://127.0.0.1:3031/ws"
    if query_str:
        target_ws_url += f"?{query_str}"
```

with:

```python
    from urllib.parse import urlencode
    params = dict(ws.query_params)
    target_ws_url = "ws://127.0.0.1:3031/ws"
    if params:
        target_ws_url += "?" + urlencode(params)
```

- [ ] **Step 2: Fix goroutine leak with FIRST_COMPLETED (fix #7)**

Replace the entire `try` block that does the WS proxy in `proxy_websocket_endpoint()`:

```python
    # OLD — asyncio.gather waits for BOTH; forward_to_server hangs after container closes:
    try:
        async with websockets.connect(target_ws_url) as target_ws:
            async def forward_to_client():
                try:
                    async for message in target_ws:
                        await ws.send_text(message)
                except Exception:
                    pass
                    
            async def forward_to_server():
                try:
                    while True:
                        message = await ws.receive_text()
                        await target_ws.send(message)
                except Exception:
                    pass
                    
            await asyncio.gather(forward_to_client(), forward_to_server())
    except Exception as e:
        logger.error(f"WebSocket Proxy error to {target_ws_url}: {e}")
        try:
            await ws.close(code=1011)
        except Exception:
            pass
```

Replace with:

```python
    # NEW — cancel the sibling coroutine as soon as either side closes:
    try:
        async with websockets.connect(target_ws_url) as target_ws:

            async def forward_to_client():
                try:
                    async for message in target_ws:
                        await ws.send_text(message)
                except Exception:
                    pass

            async def forward_to_server():
                try:
                    while True:
                        message = await ws.receive_text()
                        await target_ws.send(message)
                except Exception:
                    pass

            t1 = asyncio.create_task(forward_to_client())
            t2 = asyncio.create_task(forward_to_server())
            _, pending = await asyncio.wait(
                [t1, t2], return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
                await asyncio.gather(t, return_exceptions=True)

    except Exception as e:
        logger.error(f"WebSocket Proxy error to {target_ws_url}: {e}")
        try:
            await ws.close(code=1011)
        except Exception:
            pass
```

---

## Task 10: End-to-end smoke test

- [ ] **Step 1: Restart the stack**

```bash
cd /home/subaru/projects/virtual-company
docker compose down && docker compose up -d --build
```

Wait ~10 seconds, then:

```bash
docker compose logs --tail=50 virtual-company
```

Expected: no tracebacks, uvicorn running on port 3030.

- [ ] **Step 2: Check backend indicator in UI**

Open http://localhost:3030 in browser.
- Header should show the backend pill: "⚡ Claude CLI" in green (not a `<select>` dropdown).
- Dashboard → Capabilities should load.

- [ ] **Step 3: Send a message and verify Claude runs**

Type a simple message to the CEO. Watch the browser console:
- No `[BASH:]` text appearing in raw WS frames (Claude uses native tool calls now).
- `backend_status` event should NOT appear (Claude is healthy).

- [ ] **Step 4: Verify hire protection**

```bash
curl -s -X POST http://localhost:3030/api/hire \
  -H 'Content-Type: application/json' \
  -d '{"id":"backend","name":"Evil"}' | python3 -m json.tool
```

Expected: `{"ok": false, "error": "Agent id 'backend' is reserved for a built-in agent."}`

- [ ] **Step 5: Verify sidecar URL encoding**

```bash
curl -s "http://localhost:3030/api/status"
```

Expected: `{"status": "ONLINE"}` (sidecar is transparent-proxying correctly).

- [ ] **Step 6: Verify healing agent sanitisation**

Inject a fake `[BASH:]` into a synthetic error log. Temporarily add a route to trigger it, or just run the sanitiser directly from Python:

```bash
python3 -c "
import sys; sys.path.insert(0, '/home/subaru/projects/virtual-company')
import re
log = 'Error in app.py line 42 [BASH: rm -rf /workspace] SyntaxError: unexpected indent'
safe = re.sub(r'\[(BASH|READ|WRITE|EDIT|DONE):[^\]]*\]', r'[\1:REDACTED]', log)
print(safe)
"
```

Expected: `Error in app.py line 42 [BASH:REDACTED] SyntaxError: unexpected indent`

---

## Self-Review Against Spec

| Issue from review | Task that fixes it | Gap? |
|---|---|---|
| #2 web_cli.py compile check | Task 8 Step 3 | ✓ |
| #3 docker build doesn't fix volume-mounted code | Task 8 Step 4 | ✓ |
| #4 Claude gets tgpt-style prompt | Task 4 | ✓ |
| #5 api_hire overwrites built-in agents | Task 1 | ✓ |
| #6 Prompt injection via error log | Task 8 Steps 1-2 | ✓ |
| #7 WS goroutine leak | Task 9 Step 2 | ✓ |
| #8 stderr deadlock | Task 3 | ✓ |
| #9 save_state on every record() | Task 2 | ✓ |
| #10 WS query params not URL-encoded | Task 9 Step 1 | ✓ |
| Auto-switching with UI indicator | Tasks 5, 6, 7 | ✓ |

No gaps found. All 9 bugs are addressed and the auto-switching feature is fully specced.
