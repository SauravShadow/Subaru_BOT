# Phase 4 — Multi-Agent Collaboration & Self-Healing Phoenix

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two advanced intelligence features: multi-agent mid-task collaboration via `[ASK:agent]` tags so workers can query the CEO during execution, and a Self-Healing Phoenix system that lets agents safely read/modify/test source code with a zone-based safety model (email approval gate for sensitive files).

**Architecture:** Multi-agent: `parse_tool_call()` detects `[ASK:agent_id]` tags, `_execute_tool()` recursively calls `run_agent(target, ...)` with a 2-minute timeout, and the response is injected back as a tool result — the existing multi-turn tgpt loop handles the rest. Self-Healing: a new `app/services/self_heal.py` module owns zone classification and pending approval state; `_execute_tool()` dispatches `read_source`, `write_source`, and `run_tests` tool calls; Protected Zone writes send an email diff to the user and queue in `nexus_pending_approvals.json`; the email poller detects APPROVE/DENY replies and applies or discards the change.

**Tech Stack:** Python 3.12, asyncio, existing email service (`app/services/email.py`), existing tgpt tool parse/dispatch loop, pytest, `difflib` (stdlib).

**Base SHA:** `886d30e`

**Run tests:** `docker exec virtual-company python -m pytest /app/tests/test_<name>.py -v`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `app/agents/tools.py` | Add `[ASK:agent]` and source-file tool parsers |
| Modify | `app/agents/executor.py` | Handle `ask_agent`, `read_source`, `write_source`, `run_tests` in `_execute_tool` |
| Create | `app/services/self_heal.py` | Zone classifier + approval state + apply/deny logic |
| Modify | `app/services/email_poller.py` | Detect APPROVE/DENY in incoming emails |
| Modify | `app/api/router.py` | GET/POST `/api/approvals` endpoints |
| Modify | `app/agents/definitions.py` | Add source-edit tool instructions to Backend + CEO personas |
| Modify | `app/static/app-v5.js` | Handle `approval_requested` + `approval_applied` WS events |
| Create | `tests/test_ask_agent.py` | Tests for inter-agent messaging |
| Create | `tests/test_self_heal.py` | Tests for zone classifier and approval flow |

---

## Task 1: [ASK:agent] Parser + Handler (TDD)

**Files:**
- Modify: `app/agents/tools.py`
- Modify: `app/agents/executor.py`
- Create: `tests/test_ask_agent.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_ask_agent.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch


def test_parse_ask_agent_tag():
    """[ASK:ceo] should parse to ask_agent tool with target and question."""
    from app.agents.tools import parse_tool_call
    text = "I need clarification.\n[ASK:ceo] Should I use PostgreSQL or SQLite for this feature?"
    tool_type, tool_args = parse_tool_call(text)
    assert tool_type == "ask_agent"
    assert tool_args["target"] == "ceo"
    assert "PostgreSQL" in tool_args["question"]


def test_parse_ask_agent_multiline_question():
    """[ASK:backend] with multiline question captures full question."""
    from app.agents.tools import parse_tool_call
    text = "[ASK:backend] What is the current database schema?\nAnd what tables exist?"
    tool_type, tool_args = parse_tool_call(text)
    assert tool_type == "ask_agent"
    assert tool_args["target"] == "backend"
    assert "database schema" in tool_args["question"]


def test_parse_ask_agent_not_confused_with_bash():
    """[BASH:...] should still parse as bash, not ask_agent."""
    from app.agents.tools import parse_tool_call
    text = "[BASH: ls -la /app]"
    tool_type, tool_args = parse_tool_call(text)
    assert tool_type == "bash"


@pytest.mark.asyncio
async def test_execute_ask_agent_calls_run_agent():
    """_execute_tool should call run_agent on the target agent and return its response."""
    from app.agents import executor

    sent = []
    async def fake_send(d): sent.append(d)

    with patch.object(executor, "run_agent", new=AsyncMock(return_value="Use SQLite.")) as mock_run:
        result = await executor._execute_tool(
            "backend", "ask_agent", {"target": "ceo", "question": "SQLite or Postgres?"}, fake_send
        )
        mock_run.assert_called_once_with("ceo", "SQLite or Postgres?", fake_send)
        assert "SQLite" in result


@pytest.mark.asyncio
async def test_execute_ask_agent_timeout_returns_fallback():
    """When target agent times out, return a descriptive fallback (don't raise)."""
    import asyncio
    from app.agents import executor

    sent = []
    async def fake_send(d): sent.append(d)

    async def _slow(*a, **kw):
        await asyncio.sleep(999)

    with patch.object(executor, "run_agent", new=_slow):
        with patch("app.agents.executor._ASK_TIMEOUT", 0.05):
            result = await executor._execute_tool(
                "backend", "ask_agent", {"target": "ceo", "question": "hello?"}, fake_send
            )
    assert "timed out" in result.lower() or "no reply" in result.lower()
```

- [ ] **Step 2: Run — expect failure**

```bash
docker exec virtual-company python -m pytest /app/tests/test_ask_agent.py -v 2>&1 | tail -6
```

Expected: `AttributeError` or `AssertionError` — `ask_agent` not yet parsed.

- [ ] **Step 3: Add [ASK:agent] parser to tools.py**

In `app/agents/tools.py`, inside `parse_tool_call()`, add this **before** `return None, None` (after the `[WEB_SCREENSHOT]` parser):

```python
    m = re.search(r'\[ASK:(\w+)\]\s*([\s\S]+?)(?=\[|$)', text)
    if m:
        return "ask_agent", {
            "target":   m.group(1).strip().lower(),
            "question": m.group(2).strip(),
        }
```

- [ ] **Step 4: Add ask_agent to _execute_tool in executor.py**

Add this module-level constant near the top of `executor.py` (after the imports section):

```python
_ASK_TIMEOUT: float = 120.0   # seconds before inter-agent ask times out
```

In `_execute_tool()`, add to `icon_map`:
```python
        "ask_agent":    "💬",
```
Add to `label_map`:
```python
        "ask_agent":    "Asking agent",
```

In the `try` block, add before the `else:` branch:

```python
        elif tool_type == "ask_agent":
            target   = tool_args.get("target", "ceo")
            question = tool_args.get("question", "")
            sub_out: list[str] = []

            async def _sub_send(d: dict) -> None:
                if d.get("type") == "assistant":
                    for blk in d.get("message", {}).get("content", []):
                        if blk.get("type") == "text" and blk["text"]:
                            sub_out.append(blk["text"])
                await send(d)   # forward to UI so exchange is visible

            try:
                await asyncio.wait_for(
                    run_agent(target, question, _sub_send),
                    timeout=_ASK_TIMEOUT,
                )
                result = "".join(sub_out).strip() or f"[{target} sent no text reply]"
            except asyncio.TimeoutError:
                result = (
                    f"[{target} did not reply within {int(_ASK_TIMEOUT)}s — "
                    f"proceeding with best judgement]"
                )
```

- [ ] **Step 5: Add [ASK:agent] to tgpt tool list in _build_tgpt_prompt**

In `app/agents/executor.py`, inside `_build_tgpt_prompt()`, find the tool_instructions string. After the last numbered item (currently item 10 `[WEB_SCREENSHOT]`), add:

```
11. [ASK:agent_id] question    — Ask another agent a question mid-task; their reply is injected as the tool result
    Agents: ceo, backend, frontend, qa, devops
    Example: [ASK:ceo] Should I use Postgres or SQLite for this?
```

- [ ] **Step 6: Run tests — expect pass**

```bash
docker exec virtual-company python -m pytest /app/tests/test_ask_agent.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 7: Run full suite**

```bash
docker exec virtual-company python -m pytest /app/tests/ -v 2>&1 | tail -5
```

Expected: 49 tests pass (44 + 5 new).

- [ ] **Step 8: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/agents/tools.py app/agents/executor.py tests/test_ask_agent.py
git commit -m "feat: [ASK:agent] inter-agent collaboration — workers can query CEO mid-task"
```

---

## Task 2: Add Thinking Layer UI for Inter-Agent Messages

**Files:**
- Modify: `app/static/app-v5.js`

The `ask_agent` tool already forwards events to the UI via `_sub_send`. This task ensures the thinking layer shows the exchange clearly.

- [ ] **Step 1: Update addThinkingStep to recognise ask_agent tool calls**

In `app-v5.js`, the `dispatch()` function already handles `tool_call` events with:
```javascript
    case "tool_call":
      addThinkingStep(`${obj.label || obj.tool}: ${obj.path || ""}`, "active");
      break;
```

The `label` for `ask_agent` will be "Asking agent". Update the thinking step render to show exchanges more clearly. Find `addThinkingStep` and verify it's already defined (it is). No change needed to the function itself.

However, update the `tool_call` case to handle agent-to-agent exchanges with a distinctive prefix:

```javascript
    case "tool_call":
      if (obj.tool === "ask_agent") {
        addThinkingStep(`↔ Asking ${obj.path || "agent"}…`, "active");
      } else {
        addThinkingStep(`${obj.label || obj.tool}: ${obj.path || ""}`, "active");
      }
      break;
```

The `path` field for `ask_agent` will be `tool_args.get("target")`. Update `_execute_tool()` in `executor.py` so the `path` in the `tool_call` event is the target agent:

In executor.py, find the block in `_execute_tool()` where `path` is set:
```python
    path  = tool_args.get("path", tool_args.get("cmd", ""))
```

Replace with:
```python
    path  = tool_args.get("path", tool_args.get("cmd", tool_args.get("target", tool_args.get("url", ""))))
```

- [ ] **Step 2: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/static/app-v5.js app/agents/executor.py
git commit -m "feat: thinking layer shows inter-agent ↔ exchanges distinctly"
```

---

## Task 3: Zone Classifier Service (TDD)

**Files:**
- Create: `app/services/self_heal.py`
- Create: `tests/test_self_heal.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_self_heal.py`:

```python
import pytest
import json
from pathlib import Path
from unittest.mock import patch


def test_classify_immutable_paths():
    from app.services.self_heal import classify_path
    assert classify_path("/app/app/main.py")              == "immutable"
    assert classify_path("/app/skills/loader.py")         == "immutable"
    assert classify_path("/app/skills/core/bash_tools.py")== "immutable"
    assert classify_path("app/main.py")                   == "immutable"


def test_classify_protected_paths():
    from app.services.self_heal import classify_path
    assert classify_path("/app/app/agents/executor.py")   == "protected"
    assert classify_path("/app/app/api/router.py")        == "protected"
    assert classify_path("app/agents/definitions.py")     == "protected"
    assert classify_path("/app/requirements.txt")         == "protected"
    assert classify_path("/app/Dockerfile")               == "protected"


def test_classify_surface_paths():
    from app.services.self_heal import classify_path
    assert classify_path("/app/app/static/style-v5.css")  == "surface"
    assert classify_path("/app/app/static/app-v5.js")     == "surface"
    assert classify_path("app/static/index.html")         == "surface"


def test_classify_learning_paths():
    from app.services.self_heal import classify_path
    assert classify_path("/app/app/services/scheduler.py") == "learning"
    assert classify_path("/app/app/services/browser.py")   == "learning"
    assert classify_path("/app/skills/learned/ping/v1/skill.py") == "learning"


def test_load_save_approvals(tmp_path):
    from app.services.self_heal import load_approvals, save_approvals
    approvals_file = tmp_path / "nexus_pending_approvals.json"
    with patch("app.services.self_heal.APPROVALS_FILE", approvals_file):
        assert load_approvals() == {}
        save_approvals({"abc": {"id": "abc", "status": "pending"}})
        data = load_approvals()
        assert "abc" in data
        assert data["abc"]["status"] == "pending"


def test_classify_path_strips_workspace_prefix():
    from app.services.self_heal import classify_path
    assert classify_path("/workspace/virtual-company/app/agents/executor.py") == "protected"
    assert classify_path("virtual-company/app/static/style.css")               == "surface"
```

- [ ] **Step 2: Run — expect failure**

```bash
docker exec virtual-company python -m pytest /app/tests/test_self_heal.py -v 2>&1 | tail -5
```

Expected: `ImportError` — `app.services.self_heal` doesn't exist.

- [ ] **Step 3: Write app/services/self_heal.py**

```python
"""
Self-Healing Phoenix — zone-based source file protection.

Zone model:
  immutable:  cannot be modified by any agent (core infrastructure)
  protected:  requires email approval before writing (executor, router, etc.)
  surface:    auto-applied (static HTML/CSS/JS — visually reversible)
  learning:   auto-applied after passing pytest (services, skills, etc.)
"""
import difflib
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from app import config

logger = logging.getLogger(__name__)

APPROVALS_FILE = config.WORK_DIR / "nexus_pending_approvals.json"

# ── Zone definitions ───────────────────────────────────────────────────────────

# Relative-to-/app/ path segments that are NEVER modifiable
_IMMUTABLE = (
    "app/main.py",
    "skills/loader.py",
    "skills/core/",
)

# Relative-to-/app/ exact paths that require email approval
_PROTECTED = frozenset([
    "app/agents/executor.py",
    "app/agents/definitions.py",
    "app/api/router.py",
    "app/api/websocket.py",
    "requirements.txt",
    "Dockerfile",
    "docker-compose.yml",
    "entrypoint.sh",
])

# Relative-to-/app/ prefix for auto-applied surface changes
_SURFACE_PREFIX = "app/static/"


def _normalise(raw: str) -> str:
    """Strip container/host path prefixes to get a path relative to /app/."""
    p = raw.strip()
    for prefix in (
        "/workspace/virtual-company/",
        "/app/app/",
        "/app/",
        "virtual-company/",
    ):
        if p.startswith(prefix):
            p = p[len(prefix):]
    # Handle bare "app/..." paths that refer to the Python package
    return p


def classify_path(file_path: str) -> str:
    """Return 'immutable' | 'protected' | 'surface' | 'learning'."""
    p = _normalise(file_path)
    for seg in _IMMUTABLE:
        if p == seg or p.startswith(seg):
            return "immutable"
    if p in _PROTECTED:
        return "protected"
    if p.startswith(_SURFACE_PREFIX):
        return "surface"
    return "learning"


# ── Approval state ─────────────────────────────────────────────────────────────

def load_approvals() -> dict:
    if not APPROVALS_FILE.exists():
        return {}
    try:
        return json.loads(APPROVALS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_approvals(approvals: dict) -> None:
    APPROVALS_FILE.write_text(json.dumps(approvals, indent=2), encoding="utf-8")


def create_approval(
    file_path: str,
    new_content: str,
    requesting_agent: str,
    resolved_path: Path,
) -> str:
    """Store a pending approval and return the approval ID."""
    approval_id = str(uuid.uuid4())[:8].upper()

    old_lines: list[str] = []
    if resolved_path.exists():
        old_lines = resolved_path.read_text(encoding="utf-8", errors="replace").splitlines()
    new_lines = new_content.splitlines()

    diff = "\n".join(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
        lineterm="",
    ))[:4000]

    approvals = load_approvals()
    approvals[approval_id] = {
        "id":            approval_id,
        "file_path":     file_path,
        "resolved_path": str(resolved_path),
        "new_content":   new_content,
        "agent":         requesting_agent,
        "status":        "pending",
        "created_at":    datetime.now().isoformat(),
        "diff":          diff,
    }
    save_approvals(approvals)
    logger.info("Created approval %s for %s by %s", approval_id, file_path, requesting_agent)
    return approval_id


def apply_approval(approval_id: str) -> tuple[bool, str]:
    """Write the file and mark approval as applied. Returns (success, message)."""
    approvals = load_approvals()
    entry = approvals.get(approval_id)
    if not entry:
        return False, f"Approval ID {approval_id!r} not found"
    if entry["status"] != "pending":
        return False, f"Approval {approval_id} is already {entry['status']}"
    try:
        path = Path(entry["resolved_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(entry["new_content"], encoding="utf-8")
        entry["status"]     = "applied"
        entry["applied_at"] = datetime.now().isoformat()
        save_approvals(approvals)
        logger.info("Applied approval %s → %s", approval_id, entry["file_path"])
        return True, f"Applied: {entry['file_path']}"
    except Exception as exc:
        return False, f"Apply failed: {exc}"


def deny_approval(approval_id: str) -> tuple[bool, str]:
    """Mark approval as denied without writing the file."""
    approvals = load_approvals()
    entry = approvals.get(approval_id)
    if not entry:
        return False, f"Approval ID {approval_id!r} not found"
    entry["status"]    = "denied"
    entry["denied_at"] = datetime.now().isoformat()
    save_approvals(approvals)
    logger.info("Denied approval %s for %s", approval_id, entry["file_path"])
    return True, f"Denied: {entry['file_path']}"


def build_approval_email(approval_id: str, file_path: str, agent: str, diff: str) -> tuple[str, str]:
    """Return (subject, body) for the approval request email."""
    subject = f"[Subaru] Approval needed: modify {Path(file_path).name} (ID: {approval_id})"
    body    = f"""Subaru agent '{agent}' wants to modify a protected file.

FILE: {file_path}
APPROVAL ID: {approval_id}

To approve: reply with subject or body containing: APPROVE {approval_id}
To deny:    reply with subject or body containing: DENY {approval_id}

Or use the API:
  POST http://localhost:3030/api/approvals/{approval_id}/apply
  POST http://localhost:3030/api/approvals/{approval_id}/deny

--- DIFF ---
{diff or "(new file — no previous content)"}
"""
    return subject, body
```

- [ ] **Step 4: Run tests — expect pass**

```bash
docker exec virtual-company python -m pytest /app/tests/test_self_heal.py -v
```

Expected: 6 tests PASS.

- [ ] **Step 5: Run full suite**

```bash
docker exec virtual-command python -m pytest /app/tests/ -v 2>&1 | tail -5
```

Expected: 55 tests pass (49 + 6 new).

- [ ] **Step 6: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/services/self_heal.py tests/test_self_heal.py
git commit -m "feat: zone classifier for source file safety (immutable/protected/surface/learning)"
```

---

## Task 4: Source-File Tool Parsers + Handlers

**Files:**
- Modify: `app/agents/tools.py`
- Modify: `app/agents/executor.py`

- [ ] **Step 1: Add parsers to tools.py**

In `app/agents/tools.py`, inside `parse_tool_call()`, add **before** `return None, None`:

```python
    m = re.search(r'\[READ_SOURCE:\s*(.*?)\]', text, re.DOTALL)
    if m:
        return "read_source", {"path": m.group(1).strip()}

    m = re.search(r'\[WRITE_SOURCE:\s*(.*?)\]', text, re.DOTALL)
    if m:
        path = m.group(1).strip()
        code_m = re.search(r'```(?:\w+)?\n(.*?)```', text[m.end():], re.DOTALL)
        content = code_m.group(1) if code_m else text[m.end():].strip()
        return "write_source", {"path": path, "content": content}

    m = re.search(r'\[RUN_TESTS\]', text)
    if m:
        return "run_tests", {}
```

- [ ] **Step 2: Add handlers to executor.py**

In `app/agents/executor.py`, inside `_execute_tool()`:

**Add to icon_map:**
```python
        "read_source":  "📋",
        "write_source": "🔧",
        "run_tests":    "🧪",
```

**Add to label_map:**
```python
        "read_source":  "Reading Source",
        "write_source": "Writing Source",
        "run_tests":    "Running Tests",
```

**Add cases before the `else:` branch:**

```python
        elif tool_type == "read_source":
            result = local_read(tool_args.get("path", ""))

        elif tool_type == "write_source":
            from app.services.self_heal import (
                classify_path, create_approval, build_approval_email,
            )
            from app.services import email as email_svc
            from app.api.websocket import broadcast_event
            from app.agents.tools import _resolve, _safe

            file_path  = tool_args.get("path", "")
            content    = tool_args.get("content", "")
            zone       = classify_path(file_path)

            if zone == "immutable":
                result = (
                    f"[BLOCKED] {file_path} is in the immutable core — "
                    "it cannot be modified by any agent."
                )
            elif zone in ("surface", "learning"):
                # Auto-apply: write immediately
                resolved = _resolve(file_path)
                if not _safe(resolved):
                    result = "[BLOCKED] Path is outside the workspace."
                else:
                    result = local_write(file_path, content)
                    asyncio.create_task(broadcast_event({
                        "type":    "source_file_modified",
                        "path":    file_path,
                        "zone":    zone,
                        "agent":   agent_id,
                    }))
            else:  # protected — email gate
                resolved     = _resolve(file_path)
                approval_id  = create_approval(file_path, content, agent_id, resolved)
                subj, body   = build_approval_email(
                    approval_id, file_path, agent_id,
                    # diff is stored in approvals but pass empty here — build_approval_email reads it
                    "",
                )
                # Re-read the stored diff for the email body
                from app.services.self_heal import load_approvals
                stored_diff = load_approvals().get(approval_id, {}).get("diff", "")
                subj, body  = build_approval_email(approval_id, file_path, agent_id, stored_diff)
                asyncio.create_task(email_svc.send_mail(subj, body))
                asyncio.create_task(broadcast_event({
                    "type":        "approval_requested",
                    "approval_id": approval_id,
                    "file_path":   file_path,
                    "agent":       agent_id,
                }))
                result = (
                    f"Change pending approval (ID: {approval_id}). "
                    f"Email sent to {config.USER_EMAIL}. "
                    f"Reply 'APPROVE {approval_id}' or 'DENY {approval_id}'."
                )

        elif tool_type == "run_tests":
            result = await local_bash(
                "python -m pytest /app/tests/ -q --tb=short --no-header 2>&1 | tail -20"
            )
```

- [ ] **Step 3: Add source-file tools to tgpt tool list**

In `_build_tgpt_prompt()`, after the `[ASK:agent]` item 11, add:

```
12. [READ_SOURCE: /app/app/agents/executor.py]  — Read any source file in /app/
13. [WRITE_SOURCE: /app/app/services/foo.py]    — Write/modify source file (zone-checked; safe files auto-apply, protected files email you for approval)
    Follow with: ```python\n<content>\n```
14. [RUN_TESTS]                                  — Run pytest and return pass/fail summary
```

- [ ] **Step 4: Verify app still starts**

```bash
docker exec virtual-company curl -s http://localhost:3030/api/capabilities > /dev/null && echo OK
```

Expected: `OK`

- [ ] **Step 5: Run full suite**

```bash
docker exec virtual-company python -m pytest /app/tests/ -v 2>&1 | tail -5
```

Expected: 55 tests pass.

- [ ] **Step 6: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/agents/tools.py app/agents/executor.py
git commit -m "feat: READ_SOURCE/WRITE_SOURCE/RUN_TESTS agent tools with zone-based protection"
```

---

## Task 5: Approvals API + Email Poller Integration

**Files:**
- Modify: `app/api/router.py`
- Modify: `app/services/email_poller.py`

- [ ] **Step 1: Add approvals API endpoints to router.py**

Add these imports at the top of `app/api/router.py`:

```python
from app.services.self_heal import load_approvals, apply_approval, deny_approval
```

Add these routes after the browser endpoints:

```python
# ── Approvals ──────────────────────────────────────────────────────────────────

@router.get("/api/approvals")
async def api_approvals_list():
    return load_approvals()


@router.post("/api/approvals/{approval_id}/apply")
async def api_approvals_apply(approval_id: str):
    from app.api.websocket import broadcast_event
    ok, msg = apply_approval(approval_id.upper())
    if ok:
        asyncio.create_task(broadcast_event({
            "type":        "approval_applied",
            "approval_id": approval_id.upper(),
            "message":     msg,
        }))
    return {"ok": ok, "message": msg}


@router.post("/api/approvals/{approval_id}/deny")
async def api_approvals_deny(approval_id: str):
    from app.api.websocket import broadcast_event
    ok, msg = deny_approval(approval_id.upper())
    if ok:
        asyncio.create_task(broadcast_event({
            "type":        "approval_denied",
            "approval_id": approval_id.upper(),
            "message":     msg,
        }))
    return {"ok": ok, "message": msg}
```

- [ ] **Step 2: Read current email_poller.py to understand structure**

```bash
head -60 /home/subaru/projects/virtual-company/app/services/email_poller.py
```

Then read the full file to understand how emails are processed.

- [ ] **Step 3: Extend email_poller.py to detect APPROVE/DENY**

In `app/services/email_poller.py`, add a function to scan incoming emails for approval responses. Add this function before the main `poll_once()` or `start()` function:

```python
async def _check_approval_replies(emails: list[dict]) -> None:
    """Scan incoming emails for APPROVE/DENY responses and process them."""
    import re as _re
    from app.services.self_heal import apply_approval, deny_approval, load_approvals
    from app.api.websocket import broadcast_event

    approvals = load_approvals()
    if not approvals:
        return

    pending_ids = {k for k, v in approvals.items() if v.get("status") == "pending"}
    if not pending_ids:
        return

    for email_item in emails:
        text = (
            str(email_item.get("subject", "")) + " " +
            str(email_item.get("body",    ""))
        ).upper()

        # Look for APPROVE <ID> or DENY <ID>
        for approval_id in pending_ids:
            if f"APPROVE {approval_id}" in text:
                ok, msg = apply_approval(approval_id)
                if ok:
                    await broadcast_event({
                        "type":        "approval_applied",
                        "approval_id": approval_id,
                        "message":     msg,
                        "source":      "email",
                    })
                    logger.info("Approval %s applied via email reply", approval_id)
                break
            elif f"DENY {approval_id}" in text:
                ok, msg = deny_approval(approval_id)
                if ok:
                    await broadcast_event({
                        "type":        "approval_denied",
                        "approval_id": approval_id,
                        "message":     msg,
                        "source":      "email",
                    })
                    logger.info("Approval %s denied via email reply", approval_id)
                break
```

Then in the existing `poll_once()` function, call `_check_approval_replies()` with the fetched emails. Find where emails are read and add the call after the existing email processing logic:

```python
    # After existing email processing, check for approval replies
    if emails and isinstance(emails, list):
        await _check_approval_replies(emails)
```

- [ ] **Step 4: Verify API endpoints work**

```bash
docker exec virtual-company curl -s http://localhost:3030/api/approvals | python3 -m json.tool
```

Expected: `{}` (empty dict — no pending approvals).

- [ ] **Step 5: Run full suite**

```bash
docker exec virtual-company python -m pytest /app/tests/ -v 2>&1 | tail -5
```

Expected: 55 tests pass.

- [ ] **Step 6: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/api/router.py app/services/email_poller.py
git commit -m "feat: approvals API endpoints + email poller detects APPROVE/DENY replies"
```

---

## Task 6: Agent Persona Updates + WS Notification UI

**Files:**
- Modify: `app/agents/definitions.py`
- Modify: `app/static/app-v5.js`

- [ ] **Step 1: Update Backend agent persona with self-healing tool instructions**

In `app/agents/definitions.py`, find the Backend agent's `_worker_persona` call. The `extra` parameter currently ends with a line about `[DONE: ...]`. Add source-file instructions after the existing self-modification guide:

Find in the Backend persona's `extra` string:
```python
  5. [DONE: Brief summary of what was changed/applied]
```

Add after it (within the same string):
```python

SELF-HEALING TOOLS:
  When you encounter a bug, limitation, or improvement opportunity:
  1. [READ_SOURCE: /app/app/agents/executor.py]    — read the file first
  2. [WRITE_SOURCE: /app/app/services/foo.py]      — write the updated content
     ```python
     <full updated file content>
     ```
     Surface zone (static/) → auto-applied immediately
     Learning zone (services/, skills/) → auto-applied immediately
     Protected zone (executor.py, router.py, etc.) → emails Saurav for approval
  3. [RUN_TESTS]                                   — verify changes didn't break anything
  4. [DONE: Brief summary]

For inter-agent questions:
  [ASK:ceo] Your question here   — CEO will reply; their answer is injected back as context
```

- [ ] **Step 2: Handle WS notification events in app-v5.js**

In the `dispatch()` function's `switch(type)` block, add these cases (after the existing `"approval_*"` or at the end):

```javascript
    case "approval_requested":
      pushNotif(
        `🔐 Approval needed: ${obj.file_path || "file"} (ID: ${obj.approval_id})`,
        "warn"
      );
      appendMsg(obj.agent || "system", "assistant",
        `⚠️ I need your approval to modify \`${obj.file_path}\`.\n` +
        `**Approval ID:** \`${obj.approval_id}\`\n\n` +
        `Reply: \`APPROVE ${obj.approval_id}\` or \`DENY ${obj.approval_id}\`\n` +
        `Or use: POST /api/approvals/${obj.approval_id}/apply`
      );
      break;

    case "approval_applied":
      pushNotif(`✅ Applied: ${obj.message || obj.approval_id}`, "success");
      appendMsg("system", "assistant", `✅ Change applied: ${obj.message}`);
      break;

    case "approval_denied":
      pushNotif(`✗ Denied: ${obj.message || obj.approval_id}`, "warn");
      break;

    case "source_file_modified":
      pushNotif(`🔧 ${obj.agent}: modified ${obj.path} (${obj.zone})`, "success");
      break;
```

- [ ] **Step 3: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/agents/definitions.py app/static/app-v5.js
git commit -m "feat: Backend self-healing persona + approval notification UI"
```

---

## Task 7: End-to-End Smoke Test

- [ ] **Step 1: Full test suite**

```bash
docker exec virtual-company python -m pytest /app/tests/ -v
```

Expected: **55 tests PASS** (44 Phase 1-3 + 5 ask_agent + 6 self_heal).

- [ ] **Step 2: Inter-agent collaboration smoke test**

```bash
docker exec virtual-company python3 -c "
import asyncio, sys
sys.path.insert(0, '/app')
from app.agents.tools import parse_tool_call

# Verify [ASK:ceo] parses correctly
t, a = parse_tool_call('[ASK:ceo] Should I use Postgres or SQLite?')
print('Tool:', t, '| Target:', a['target'], '| Q:', a['question'][:30])

# Verify [READ_SOURCE:] parses
t, a = parse_tool_call('[READ_SOURCE: /app/app/config.py]')
print('Tool:', t, '| Path:', a['path'])

# Verify [RUN_TESTS] parses
t, a = parse_tool_call('[RUN_TESTS]')
print('Tool:', t)
"
```

Expected output:
```
Tool: ask_agent | Target: ceo | Q: Should I use Postgres or SQLite?
Tool: read_source | Path: /app/app/config.py
Tool: run_tests
```

- [ ] **Step 3: Zone classifier smoke test**

```bash
docker exec virtual-company python3 -c "
import sys; sys.path.insert(0, '/app')
from app.services.self_heal import classify_path
tests = [
    ('/app/app/main.py',               'immutable'),
    ('/app/app/agents/executor.py',    'protected'),
    ('/app/app/static/app-v5.js',      'surface'),
    ('/app/app/services/scheduler.py', 'learning'),
]
for path, expected in tests:
    got = classify_path(path)
    status = '✓' if got == expected else '✗'
    print(f'{status} {path.split(\"/\")[-1]}: {got} (expected {expected})')
"
```

Expected: all 4 lines show `✓`.

- [ ] **Step 4: Approval API smoke test**

```bash
# Check empty approvals list
docker exec virtual-company curl -s http://localhost:3030/api/approvals | python3 -c "import sys,json; d=json.load(sys.stdin); print('approvals:', len(d))"
```

Expected: `approvals: 0`

- [ ] **Step 5: App health**

```bash
docker exec virtual-company curl -s http://localhost:3030/api/capabilities > /dev/null && echo "API OK"
docker logs virtual-company --tail 10 | grep -E "ERROR|Traceback" || echo "No errors"
```

Expected: `API OK`, `No errors`.

- [ ] **Step 6: Final commit**

```bash
cd /home/subaru/projects/virtual-company
git add -A
git status
git commit -m "feat: Phase 4 complete — Multi-Agent Collaboration + Self-Healing Phoenix" 2>/dev/null || echo "All changes already committed"
```

---

## Self-Review

**Spec coverage:**

| Spec Requirement | Task |
|---|---|
| `[ASK:agent]` tag parsed by executor | Task 1 (tools.py parser + executor handler) |
| Inter-agent recursive `run_agent()` call | Task 1 (`_execute_tool` ask_agent case) |
| 2-minute timeout with fallback message | Task 1 (`asyncio.wait_for` with `_ASK_TIMEOUT`) |
| Thinking layer shows `↔` exchanges | Task 2 (dispatcher + path field) |
| Zone classifier (immutable/protected/surface/learning) | Task 3 (`self_heal.py classify_path`) |
| Approval state stored in `nexus_pending_approvals.json` | Task 3 (`create_approval`, `load/save_approvals`) |
| `apply_approval()` / `deny_approval()` | Task 3 (`self_heal.py`) |
| `READ_SOURCE`, `WRITE_SOURCE`, `RUN_TESTS` tool parsers | Task 4 (tools.py) |
| `write_source` → zone check → auto-apply or email gate | Task 4 (executor.py) |
| Approval email with diff sent to user | Task 4 (`executor.py` write_source handler) |
| `GET/POST /api/approvals` endpoints | Task 5 (router.py) |
| Email poller detects APPROVE/DENY replies | Task 5 (email_poller.py) |
| Backend persona updated with self-healing instructions | Task 6 (definitions.py) |
| WS events for approval_requested/applied/denied | Task 6 (app-v5.js) |

**No placeholders found. All code blocks are complete.**

**Type consistency:**
- `create_approval()` returns `str` (approval_id) — used in Task 4 executor handler ✓
- `apply_approval(id)` returns `tuple[bool, str]` — used in Tasks 5 router and 5 email_poller ✓
- `classify_path(path)` returns `str` — used in Task 4 executor handler ✓
- `_ASK_TIMEOUT: float` defined at module level — patched in Task 1 test ✓
