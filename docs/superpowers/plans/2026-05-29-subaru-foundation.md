# Subaru Command Center — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform Shadow Garden into the Subaru Command Center: 3-tier AI router (Claude Sonnet → Gemini → tgpt), hot-loadable Skill Registry, SQLite FTS5 long-term memory, and Ambient UI shell with arc reactor, agent orbs, skills panel, and command palette.

**Architecture:** Option B — infrastructure first. AI Router and Skill Registry are pure backend modules. Memory wires into executor context injection. Ambient UI consumes the new `/api/skills` endpoint and updated WebSocket `init` event. Learned skills extend `_execute_tool()` without touching existing core tool dispatch. Each task produces deployable, testable output.

**Tech Stack:** Python 3.12, FastAPI, asyncio, `google-genai` SDK, SQLite FTS5 (stdlib), `watchfiles`, `pytest`, `pytest-asyncio`, vanilla JS, CSS custom properties, Docker (volume-mounted `/app`).

**Run tests inside container:**
```bash
docker exec virtual-company python -m pytest /app/tests/test_<name>.py -v
```

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `app/config.py` | Add GEMINI_API_KEY, model constants, MEMORY_DB, SKILLS_DIR |
| Modify | `requirements.txt` | Add google-genai, watchfiles, pytest, pytest-asyncio |
| Modify | `app/agents/backend_state.py` | 3-tier state: claude / gemini / tgpt |
| Modify | `app/agents/executor.py` | run_gemini_agent(), 3-tier run_agent(), skill fallback in _execute_tool(), context injection |
| Create | `app/skills/__init__.py` | Module init + module-level skill_loader singleton |
| Create | `app/skills/loader.py` | SkillLoader: loads learned skills, register_skill(), rollback() |
| Create | `app/skills/registry.json` | Live manifest index (starts empty) |
| Create | `app/skills/core/bash_tools.py` | Core tool metadata (TOOLS list only — no handlers) |
| Create | `app/skills/core/file_tools.py` | Core tool metadata |
| Create | `app/skills/core/email_tools.py` | Core tool metadata |
| Create | `app/services/memory.py` | init_db(), save_memory(), get_relevant_memories(), decay_old_memories() |
| Modify | `app/api/router.py` | GET/POST/DELETE /api/skills endpoints |
| Modify | `app/api/websocket.py` | skills list in init event, backend_switch event type |
| Modify | `app/main.py` | Initialize SkillLoader + Memory DB on startup |
| Modify | `app/static/index.html` | Ambient surface: arc reactor, orbs, skills panel, palette shell |
| Modify | `app/static/style-v5.css` | Full design system rebuild |
| Modify | `app/static/app-v5.js` | Orb logic, arc reactor, skills panel fetch, palette skeleton |
| Create | `tests/__init__.py` | Empty |
| Create | `tests/test_backend_state.py` | 3-tier state tests |
| Create | `tests/test_skill_loader.py` | SkillLoader tests |
| Create | `tests/test_memory.py` | Memory FTS5 tests |

---

## Task 1: Add config vars + test dependencies

**Files:**
- Modify: `app/config.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Update config.py**

Replace the entire `app/config.py` with:

```python
"""Centralised configuration — reads all env vars once at import time."""
import os
from pathlib import Path

# Workspace
WORK_DIR = Path(os.environ.get("WORK_DIR", Path(__file__).parent.parent))

# Claude CLI
CLAUDE_BIN    = os.environ.get("CLAUDE_BIN", "claude")
ALLOWED_TOOLS = os.environ.get(
    "CLAUDE_ALLOWED_TOOLS",
    "Bash,Read,Write,Edit,Glob,Grep,LS,WebFetch,WebSearch",
)

# tgpt binary
TGPT_BIN = str(WORK_DIR / "virtual-company" / "tgpt")
if not Path(TGPT_BIN).exists():
    TGPT_BIN = str(WORK_DIR / "tgpt")

# Model constants
DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "claude-sonnet-4-6")
HAIKU_MODEL   = os.environ.get("HAIKU_MODEL",   "claude-haiku-4-5-20251001")
OPUS_MODEL    = os.environ.get("OPUS_MODEL",    "claude-opus-4-7")

# Gemini
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Email / SMTP
SMTP_HOST     = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT_NUM = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER     = os.environ.get("SMTP_USER", "cid.subaru.ai@gmail.com")
SMTP_PASS     = os.environ.get("SMTP_PASS", "")

# IMAP
IMAP_HOST     = os.environ.get("IMAP_HOST", "imap.gmail.com")
IMAP_PORT_NUM = int(os.environ.get("IMAP_PORT", "993"))
IMAP_USER     = os.environ.get("IMAP_USER", SMTP_USER)
IMAP_PASS     = os.environ.get("IMAP_PASS", SMTP_PASS)

# Runtime
USER_EMAIL  = os.environ.get("USER_EMAIL", "sauravsubaru@gmail.com")
MAX_STORAGE = float(os.environ.get("MAX_STORAGE_GB", "10"))
MAX_HISTORY = 30

# Paths
STATE_FILE     = WORK_DIR / "nexus_state.json"
PROJECTS_FILE  = WORK_DIR / "nexus_projects.json"
CHANGELOG_FILE = WORK_DIR / "nexus_changelog.json"
MEMORY_DB      = WORK_DIR / "nexus_memory.db"
SKILLS_DIR     = Path("/app/skills")
```

- [ ] **Step 2: Update requirements.txt**

```
anthropic>=0.50.0
python-dotenv>=1.0.0
rich>=13.0.0
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
httpx>=0.27.0
google-genai>=1.0.0
watchfiles>=0.21.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

- [ ] **Step 3: Add GEMINI_API_KEY to docker-compose.yml**

In `docker-compose.yml`, add to the `environment` block:

```yaml
      - GEMINI_API_KEY=your_key_here
```

Replace `your_key_here` with your actual key.

- [ ] **Step 4: Create tests directory**

```bash
mkdir -p /home/subaru/projects/virtual-company/tests
touch /home/subaru/projects/virtual-company/tests/__init__.py
```

- [ ] **Step 5: Create tests/conftest.py**

```python
import pytest
import sys
from pathlib import Path

# Ensure /app is importable when running tests inside the container
sys.path.insert(0, "/app")
```

- [ ] **Step 6: Rebuild container to install new packages**

```bash
cd /home/subaru/projects/virtual-company
docker compose build --no-cache && docker compose up -d
```

Expected: container restarts cleanly, `docker logs virtual-company --tail 20` shows uvicorn started on port 3030.

- [ ] **Step 7: Commit**

```bash
git add app/config.py requirements.txt docker-compose.yml tests/__init__.py tests/conftest.py
git commit -m "feat: add model constants, GEMINI_API_KEY, test infrastructure"
```

---

## Task 2: 3-Tier Backend State

**Files:**
- Modify: `app/agents/backend_state.py`
- Create: `tests/test_backend_state.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_backend_state.py`:

```python
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch


def _fresh():
    """Return a fresh module with reset globals."""
    import importlib
    import app.agents.backend_state as m
    m._quota_exhausted_at = None
    m._gemini_failed_at   = None
    m._current_backend    = "claude"
    return m


def test_initial_state_uses_claude():
    m = _fresh()
    assert m.get_current_backend() == "claude"
    assert m.should_use_claude() is True
    assert m.should_use_gemini() is False


def test_mark_quota_exhausted_switches_to_gemini():
    m = _fresh()
    changed = m.mark_quota_exhausted()
    assert changed is True
    assert m.get_current_backend() == "gemini"
    assert m.should_use_claude() is False
    assert m.should_use_gemini() is True


def test_mark_gemini_failed_switches_to_tgpt():
    m = _fresh()
    m.mark_quota_exhausted()
    changed = m.mark_gemini_failed()
    assert changed is True
    assert m.get_current_backend() == "tgpt"
    assert m.should_use_gemini() is False


def test_claude_recovery_clears_gemini_too():
    m = _fresh()
    m.mark_quota_exhausted()
    m.mark_gemini_failed()
    changed = m.mark_claude_recovered()
    assert changed is True
    assert m.get_current_backend() == "claude"
    assert m.should_use_claude() is True
    assert m.should_use_gemini() is False


def test_no_duplicate_change_events():
    m = _fresh()
    m.mark_quota_exhausted()
    changed = m.mark_quota_exhausted()  # second call
    assert changed is False


def test_gemini_retry_window():
    m = _fresh()
    m.mark_quota_exhausted()
    m.mark_gemini_failed()
    # Fake gemini_failed_at to be old enough
    m._gemini_failed_at = datetime.now() - timedelta(minutes=m.GEMINI_RETRY_MINUTES + 1)
    assert m.should_use_gemini() is True


def test_status_dict_includes_all_tiers():
    m = _fresh()
    d = m.status_dict()
    assert "backend" in d
    assert "quota_ok" in d
    assert "gemini_ok" in d
```

- [ ] **Step 2: Run tests — expect failure**

```bash
docker exec virtual-company python -m pytest /app/tests/test_backend_state.py -v
```

Expected: `AttributeError` or `AssertionError` — `should_use_gemini`, `mark_gemini_failed`, etc. don't exist yet.

- [ ] **Step 3: Rewrite backend_state.py**

Replace entire `app/agents/backend_state.py`:

```python
"""
backend_state.py — 3-tier backend switching: Claude CLI → Gemini API → tgpt.

Claude Sonnet is preferred. On quota exhaustion, falls to Gemini API.
On Gemini error, falls to tgpt. Each tier has its own retry window.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

CLAUDE_RETRY_MINUTES: int = 30
GEMINI_RETRY_MINUTES: int = 5

_quota_exhausted_at:  Optional[datetime] = None
_gemini_failed_at:    Optional[datetime] = None
_current_backend:     str = "claude"   # "claude" | "gemini" | "tgpt"

QUOTA_KEYWORDS = [
    "quota exceeded", "out of tokens", "session limit",
    "too many requests", "rate limit", "token limit",
]


def get_current_backend() -> str:
    return _current_backend


def should_use_claude() -> bool:
    if _quota_exhausted_at is None:
        return True
    return datetime.now() >= _quota_exhausted_at + timedelta(minutes=CLAUDE_RETRY_MINUTES)


def should_use_gemini() -> bool:
    """True when Claude is exhausted but Gemini is still healthy (or retry window passed)."""
    if should_use_claude():
        return False
    if _gemini_failed_at is None:
        return True
    return datetime.now() >= _gemini_failed_at + timedelta(minutes=GEMINI_RETRY_MINUTES)


def retry_due_at() -> Optional[datetime]:
    if _quota_exhausted_at is None:
        return None
    return _quota_exhausted_at + timedelta(minutes=CLAUDE_RETRY_MINUTES)


def mark_quota_exhausted() -> bool:
    global _quota_exhausted_at, _current_backend
    _quota_exhausted_at = datetime.now()
    changed = _current_backend != "gemini"
    _current_backend = "gemini"
    if changed:
        logger.warning("Claude quota exhausted — switching to Gemini.")
    return changed


def mark_gemini_failed() -> bool:
    global _gemini_failed_at, _current_backend
    _gemini_failed_at = datetime.now()
    changed = _current_backend != "tgpt"
    _current_backend = "tgpt"
    if changed:
        logger.warning("Gemini API failed — switching to tgpt.")
    return changed


def mark_claude_recovered() -> bool:
    global _quota_exhausted_at, _gemini_failed_at, _current_backend
    _quota_exhausted_at = None
    _gemini_failed_at   = None
    changed = _current_backend != "claude"
    _current_backend = "claude"
    if changed:
        logger.info("Claude recovered — switching back from fallback.")
    return changed


def is_quota_error(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in QUOTA_KEYWORDS)


def status_dict() -> dict:
    due = retry_due_at()
    return {
        "backend":    _current_backend,
        "quota_ok":   _quota_exhausted_at is None,
        "gemini_ok":  _gemini_failed_at is None,
        "retry_at":   due.strftime("%H:%M") if due else None,
        "exhausted_at": _quota_exhausted_at.isoformat() if _quota_exhausted_at else None,
    }
```

- [ ] **Step 4: Run tests — expect pass**

```bash
docker exec virtual-company python -m pytest /app/tests/test_backend_state.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/agents/backend_state.py tests/test_backend_state.py
git commit -m "feat: 3-tier backend state (claude → gemini → tgpt)"
```

---

## Task 3: Gemini Runner + Updated Dispatcher

**Files:**
- Modify: `app/agents/executor.py`
- Create: `tests/test_executor_gemini.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_executor_gemini.py`:

```python
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_run_agent_uses_gemini_when_claude_exhausted():
    """When Claude is exhausted, run_agent routes to run_gemini_agent."""
    import app.agents.backend_state as bs
    bs._quota_exhausted_at = None
    bs._gemini_failed_at   = None
    bs._current_backend    = "claude"
    bs.mark_quota_exhausted()   # Claude → exhausted, backend = "gemini"

    from app.agents import executor
    sent = []
    async def fake_send(d): sent.append(d)

    with patch.object(executor, "run_gemini_agent", new=AsyncMock(return_value="gemini reply")) as mock_g:
        result = await executor.run_agent("ceo", "hello", fake_send)
        mock_g.assert_called_once()
        assert result == "gemini reply"

    # reset
    bs.mark_claude_recovered()


@pytest.mark.asyncio
async def test_run_gemini_agent_falls_back_on_error():
    """When Gemini raises, it falls back to tgpt and marks gemini failed."""
    import app.agents.backend_state as bs
    bs._quota_exhausted_at = None
    bs._gemini_failed_at   = None
    bs._current_backend    = "claude"
    bs.mark_quota_exhausted()

    from app.agents import executor
    sent = []
    async def fake_send(d): sent.append(d)

    with patch("google.genai.Client") as mock_client:
        mock_client.return_value.models.generate_content.side_effect = Exception("api error")
        with patch.object(executor, "run_tgpt_agent", new=AsyncMock(return_value="tgpt reply")):
            result = await executor.run_gemini_agent("ceo", "hello", fake_send)
            assert result == "tgpt reply"
            assert bs.get_current_backend() == "tgpt"

    bs.mark_claude_recovered()
```

- [ ] **Step 2: Run — expect failure**

```bash
docker exec virtual-company python -m pytest /app/tests/test_executor_gemini.py -v
```

Expected: `ImportError` or `AttributeError` — `run_gemini_agent` not defined yet.

- [ ] **Step 3: Add run_gemini_agent to executor.py**

Add this function to `app/agents/executor.py` **after** `run_claude_agent` and **before** `run_agent`:

```python
async def run_gemini_agent(
    agent_id: str,
    prompt: str,
    send: Sender,
) -> str:
    """Single Gemini API turn via google-genai SDK. Falls back to tgpt on any error."""
    try:
        import google.genai as genai
        client = genai.Client(api_key=config.GEMINI_API_KEY)
        full_prompt = _build_tgpt_prompt(agent_id, prompt)
        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.0-flash",
            contents=full_prompt,
        )
        text = (response.text or "").strip()
        if not text:
            raise ValueError("Empty Gemini response")
        await send({
            "type":    "assistant",
            "agent":   agent_id,
            "message": {"content": [{"type": "text", "text": text}]},
        })
        return text
    except Exception as exc:
        logger.warning("Gemini API error (%s) — falling back to tgpt", exc)
        changed = backend_state.mark_gemini_failed()
        if changed:
            await send({"type": "backend_switch", "agent": agent_id,
                        **backend_state.status_dict()})
        return await run_tgpt_agent(agent_id, prompt, send, "pollinations")
```

- [ ] **Step 4: Update run_agent dispatcher in executor.py**

Replace the existing `run_agent` function:

```python
async def run_agent(
    agent_id: str,
    prompt: str,
    send: Sender,
    model: str = "claude",
) -> str:
    """Route to the correct backend using 3-tier auto-switching."""
    if model == "chatgpt":
        return await run_tgpt_agent(agent_id, prompt, send, "sky")
    if model == "gemini":
        return await run_gemini_agent(agent_id, prompt, send)

    # Auto-switching
    if backend_state.should_use_claude():
        return await run_claude_agent(agent_id, prompt, send)
    if backend_state.should_use_gemini():
        return await run_gemini_agent(agent_id, prompt, send)
    return await run_tgpt_agent(agent_id, prompt, send, "pollinations")
```

Also update the failover message in `run_claude_agent` — find this line:

```python
            await send({
                "type": "failover", "agent": agent_id,
                "message": (
                    f"Claude CLI quota/rate-limit hit — switching to Gemini. "
                    f"Will retry Claude at {backend_state.retry_due_at().strftime('%H:%M')}."
                ),
            })
            full_resp = await run_tgpt_agent(agent_id, prompt, send, "pollinations")
```

Replace with:

```python
            await send({
                "type": "backend_switch", "agent": agent_id,
                **backend_state.status_dict(),
                "message": f"Claude quota hit — switching to Gemini. Retry at {backend_state.retry_due_at().strftime('%H:%M')}.",
            })
            full_resp = await run_gemini_agent(agent_id, prompt, send)
```

- [ ] **Step 5: Run tests — expect pass**

```bash
docker exec virtual-company python -m pytest /app/tests/test_executor_gemini.py -v
```

Expected: 2 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add app/agents/executor.py tests/test_executor_gemini.py
git commit -m "feat: add Gemini API runner + 3-tier run_agent dispatcher"
```

---

## Task 4: Skill Registry — SkillLoader

**Files:**
- Create: `app/skills/__init__.py`
- Create: `app/skills/loader.py`
- Create: `app/skills/registry.json`
- Create: `app/skills/core/bash_tools.py`, `file_tools.py`, `email_tools.py`
- Create: `tests/test_skill_loader.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p /home/subaru/projects/virtual-company/app/skills/core
mkdir -p /home/subaru/projects/virtual-company/app/skills/learned
touch /home/subaru/projects/virtual-company/app/skills/__init__.py
touch /home/subaru/projects/virtual-company/app/skills/core/__init__.py
```

- [ ] **Step 2: Create app/skills/registry.json**

```json
{
  "learned": []
}
```

- [ ] **Step 3: Create core metadata files**

`app/skills/core/bash_tools.py`:
```python
TOOLS = [
    {"name": "bash", "description": "Execute any shell command in the workspace"},
]
```

`app/skills/core/file_tools.py`:
```python
TOOLS = [
    {"name": "read",  "description": "Read a file from the workspace"},
    {"name": "write", "description": "Write content to a file in the workspace"},
    {"name": "edit",  "description": "Replace a block of text in a file"},
]
```

`app/skills/core/email_tools.py`:
```python
TOOLS = [
    {"name": "read_inbox", "description": "Read recent unread emails from the inbox"},
]
```

- [ ] **Step 4: Write failing tests**

Create `tests/test_skill_loader.py`:

```python
import pytest
import json
import importlib
from pathlib import Path


@pytest.fixture
def tmp_skills(tmp_path):
    """Create a minimal skills directory for testing."""
    core = tmp_path / "core"
    core.mkdir()
    (core / "__init__.py").touch()
    (core / "bash_tools.py").write_text('TOOLS = [{"name": "bash", "description": "run bash"}]')
    (tmp_path / "learned").mkdir()
    (tmp_path / "registry.json").write_text('{"learned": []}')
    return tmp_path


def test_loader_lists_core_tools(tmp_skills):
    from app.skills.loader import SkillLoader
    loader = SkillLoader(tmp_skills)
    loader.load_all()
    tools = loader.list_tools()
    names = [t["name"] for t in tools]
    assert "bash" in names


def test_loader_get_tool_returns_none_for_core(tmp_skills):
    """Core tools have no handler — they're dispatched by tools.py."""
    from app.skills.loader import SkillLoader
    loader = SkillLoader(tmp_skills)
    loader.load_all()
    assert loader.get_tool("bash") is None


def test_register_learned_skill(tmp_skills):
    from app.skills.loader import SkillLoader
    loader = SkillLoader(tmp_skills)
    loader.load_all()

    skill_code = """
TOOLS = [{"name": "greet", "description": "Say hello"}]

async def handle_greet(args):
    return f"Hello, {args.get('name', 'world')}!"
"""
    test_code = """
import pytest

@pytest.mark.asyncio
async def test_greet():
    from app.skills.learned.test_greet.v1.skill import handle_greet
    result = await handle_greet({"name": "Subaru"})
    assert result == "Hello, Subaru!"
"""
    manifest = {
        "id": "test_greet",
        "name": "Greeting",
        "active_version": "1",
        "description": "Says hello",
        "tools": ["greet"],
        "available_to": ["ceo"],
        "safety_zone": "medium",
        "author": "test",
    }
    # Override learned dir to tmp_path
    loader._dir = tmp_skills
    result = loader.register_skill(manifest, skill_code, test_code)
    assert result["id"] == "test_greet"
    assert loader.get_tool("greet") is not None


@pytest.mark.asyncio
async def test_registered_skill_handler_runs(tmp_skills):
    from app.skills.loader import SkillLoader
    loader = SkillLoader(tmp_skills)
    loader.load_all()
    skill_code = 'TOOLS = [{"name": "ping", "description": "ping"}]\nasync def handle_ping(args): return "pong"'
    test_code  = 'import pytest\n@pytest.mark.asyncio\nasync def test_ping():\n    from app.skills.learned.ping.v1.skill import handle_ping\n    assert await handle_ping({}) == "pong"'
    manifest = {"id": "ping", "name": "Ping", "active_version": "1", "description": "ping",
                "tools": ["ping"], "available_to": ["all"], "safety_zone": "low", "author": "test"}
    loader.register_skill(manifest, skill_code, test_code)
    handler = loader.get_tool("ping")
    result = await handler({})
    assert result == "pong"


def test_rollback_reverts_active_version(tmp_skills):
    from app.skills.loader import SkillLoader
    loader = SkillLoader(tmp_skills)
    loader.load_all()

    v1_code   = 'TOOLS=[{"name":"ver","description":"v"}]\nasync def handle_ver(a): return "v1"'
    v2_code   = 'TOOLS=[{"name":"ver","description":"v"}]\nasync def handle_ver(a): return "v2"'
    test_code = 'import pytest\n@pytest.mark.asyncio\nasync def test_ver(): pass'
    m1 = {"id": "ver", "name": "Ver", "active_version": "1", "description": "v",
          "tools": ["ver"], "available_to": ["all"], "safety_zone": "low", "author": "t"}
    loader.register_skill(m1, v1_code, test_code)

    m2 = {**m1, "active_version": "2", "rollback_to": "1"}
    loader.register_skill(m2, v2_code, test_code)
    assert loader.get_tool("ver") is not None

    ok = loader.rollback("ver")
    assert ok is True
    # After rollback, handler returns v1
    # (re-load to pick up manifest change)
    loader.load_all()
```

- [ ] **Step 5: Run tests — expect failure**

```bash
docker exec virtual-company python -m pytest /app/tests/test_skill_loader.py -v
```

Expected: `ImportError` — `app.skills.loader` doesn't exist.

- [ ] **Step 6: Write app/skills/loader.py**

```python
"""
SkillLoader — hot-loadable skill registry.

Core tools (bash, read, write, edit, read_inbox) are metadata-only: their
handlers live in app/agents/tools.py and are dispatched by executor.py.
Learned skills are independent modules with async handle_<name>() functions.
"""
import importlib.util
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class SkillLoader:
    def __init__(self, skills_dir: Path):
        self._dir     = skills_dir
        self._tools: dict[str, callable] = {}    # tool_name → async handler (learned only)
        self._meta:  list[dict]           = []   # all tool metadata (core + learned)

    # ── Loading ────────────────────────────────────────────────────────────────

    def load_all(self) -> None:
        self._tools.clear()
        self._meta.clear()
        self._load_core()
        self._load_learned()

    def _load_core(self) -> None:
        core_dir = self._dir / "core"
        if not core_dir.exists():
            return
        for py in sorted(core_dir.glob("*.py")):
            if py.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(f"skills_core_{py.stem}", py)
                mod  = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                for tool in getattr(mod, "TOOLS", []):
                    self._meta.append({**tool, "zone": "core"})
            except Exception as exc:
                logger.error("Failed loading core skill %s: %s", py.name, exc)

    def _load_learned(self) -> None:
        learned_dir = self._dir / "learned"
        if not learned_dir.exists():
            return
        for manifest_path in sorted(learned_dir.glob("*/manifest.json")):
            try:
                self._load_from_manifest(manifest_path)
            except Exception as exc:
                logger.error("Failed loading learned skill %s: %s", manifest_path.parent.name, exc)

    def _load_from_manifest(self, manifest_path: Path) -> None:
        manifest = json.loads(manifest_path.read_text())
        sid      = manifest["id"]
        version  = str(manifest.get("active_version", "1"))
        skill_py = manifest_path.parent / f"v{version}" / "skill.py"

        if not skill_py.exists():
            logger.warning("Skill %s v%s skill.py not found", sid, version)
            return

        mod_name = f"learned_skill_{sid}_v{version}"
        spec = importlib.util.spec_from_file_location(mod_name, skill_py)
        mod  = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)

        for tool in getattr(mod, "TOOLS", []):
            name    = tool["name"]
            handler = getattr(mod, f"handle_{name}", None)
            if handler:
                self._tools[name] = handler
                self._meta.append({**tool, "zone": "learned",
                                   "skill_id": sid, "version": version})

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_tool(self, name: str) -> Optional[callable]:
        """Return the async handler for a learned skill tool, or None for core tools."""
        return self._tools.get(name)

    def list_tools(self) -> list[dict]:
        """All tool metadata (core + learned) for the Skills Panel."""
        return list(self._meta)

    def list_manifests(self) -> list[dict]:
        learned_dir = self._dir / "learned"
        if not learned_dir.exists():
            return []
        result = []
        for p in sorted(learned_dir.glob("*/manifest.json")):
            try:
                result.append(json.loads(p.read_text()))
            except Exception:
                pass
        return result

    # ── Skill installation ─────────────────────────────────────────────────────

    def register_skill(self, manifest: dict, skill_code: str, test_code: str) -> dict:
        """Write skill files, run pytest, register on pass. Raises ValueError on test failure."""
        sid      = manifest["id"]
        version  = str(manifest.get("active_version", "1"))
        skill_dir   = self._dir / "learned" / sid
        version_dir = skill_dir / f"v{version}"
        version_dir.mkdir(parents=True, exist_ok=True)

        (version_dir / "skill.py").write_text(skill_code, encoding="utf-8")
        (version_dir / "test_skill.py").write_text(test_code, encoding="utf-8")

        # Ensure __init__.py files exist for import
        (skill_dir / "__init__.py").touch(exist_ok=True)
        (version_dir / "__init__.py").touch(exist_ok=True)

        (skill_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

        # Run tests in isolation
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(version_dir / "test_skill.py"),
             "-q", "--tb=short", "--no-header"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            raise ValueError(
                f"Skill '{sid}' tests failed:\n{result.stdout}\n{result.stderr}"
            )

        # Hot-reload
        self._load_from_manifest(skill_dir / "manifest.json")
        logger.info("Skill '%s' v%s registered and loaded.", sid, version)
        return manifest

    def rollback(self, skill_id: str) -> bool:
        """Revert skill to the previous version listed in manifest.rollback_to."""
        manifest_path = self._dir / "learned" / skill_id / "manifest.json"
        if not manifest_path.exists():
            return False
        manifest     = json.loads(manifest_path.read_text())
        rollback_to  = manifest.get("rollback_to")
        if not rollback_to:
            return False
        manifest["rollback_to"]     = manifest["active_version"]
        manifest["active_version"]  = str(rollback_to)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        self._load_from_manifest(manifest_path)
        return True
```

- [ ] **Step 7: Write app/skills/__init__.py**

```python
from pathlib import Path
from app.skills.loader import SkillLoader
from app import config

skill_loader = SkillLoader(config.SKILLS_DIR)
```

- [ ] **Step 8: Run tests — expect pass**

```bash
docker exec virtual-company python -m pytest /app/tests/test_skill_loader.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 9: Commit**

```bash
git add app/skills/ tests/test_skill_loader.py
git commit -m "feat: SkillLoader with hot-loadable learned skills and rollback"
```

---

## Task 5: Wire SkillLoader into _execute_tool

**Files:**
- Modify: `app/agents/executor.py`

No new tests needed — existing tool dispatch is unchanged; we're only adding a fallback path.

- [ ] **Step 1: Import skill_loader in executor.py**

At the top of `app/agents/executor.py`, add after existing imports:

```python
from app.skills import skill_loader
```

- [ ] **Step 2: Add learned skill fallback to _execute_tool**

In `_execute_tool()`, find the final `else` branch:

```python
        else:
            result = f"[Unknown tool: {tool_type}]"
```

Replace with:

```python
        else:
            handler = skill_loader.get_tool(tool_type)
            if handler:
                result = await handler(tool_args)
            else:
                result = f"[Unknown tool: {tool_type}]"
```

- [ ] **Step 3: Load skills at module import time**

At the bottom of the imports section in `executor.py`, after the `skill_loader` import, add:

```python
skill_loader.load_all()
```

- [ ] **Step 4: Manual verification**

```bash
docker exec virtual-company curl -s http://localhost:3030/api/capabilities
```

Expected: JSON with `"skills"` list — app still loads cleanly.

- [ ] **Step 5: Commit**

```bash
git add app/agents/executor.py
git commit -m "feat: learned skill fallback in _execute_tool via SkillLoader"
```

---

## Task 6: Long-Term Memory Service (SQLite FTS5)

**Files:**
- Create: `app/services/memory.py`
- Create: `tests/test_memory.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_memory.py`:

```python
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch


@pytest.fixture
def mem(tmp_path):
    db = tmp_path / "test_memory.db"
    with patch("app.services.memory.DB_PATH", db):
        import app.services.memory as m
        m.DB_PATH = db
        m.init_db()
        yield m


def test_save_and_retrieve_memory(mem):
    mem.save_memory("ceo", "The user prefers Python over JavaScript")
    results = mem.get_relevant_memories("ceo", "Python preference")
    assert any("Python" in r for r in results)


def test_fts_relevance_ranking(mem):
    mem.save_memory("ceo", "Project Alpha uses FastAPI", importance=0.3)
    mem.save_memory("ceo", "FastAPI is the primary web framework", importance=0.9)
    results = mem.get_relevant_memories("ceo", "FastAPI framework")
    # Higher importance should rank first
    assert "primary" in results[0]


def test_agent_isolation(mem):
    mem.save_memory("ceo",     "CEO memory: executive strategy")
    mem.save_memory("backend", "Backend memory: database schema")
    ceo_results     = mem.get_relevant_memories("ceo",     "memory")
    backend_results = mem.get_relevant_memories("backend", "memory")
    assert any("executive" in r for r in ceo_results)
    assert not any("executive" in r for r in backend_results)


def test_shared_memories_visible_to_all(mem):
    mem.save_memory("shared", "Global config: port 3030")
    results = mem.get_relevant_memories("ceo", "port config")
    assert any("3030" in r for r in results)


def test_empty_query_returns_empty(mem):
    mem.save_memory("ceo", "some content")
    assert mem.get_relevant_memories("ceo", "") == []


def test_save_and_get_preference(mem):
    mem.save_preference("theme", "dark")
    assert mem.get_preference("theme") == "dark"
    assert mem.get_preference("missing", "default") == "default"


def test_decay_old_memories(mem):
    from datetime import datetime, timedelta
    mem.save_memory("ceo", "Old news")
    # Manually backdate last_hit_at
    import sqlite3
    conn = sqlite3.connect(str(mem.DB_PATH))
    old_date = (datetime.now() - timedelta(days=10)).isoformat()
    conn.execute("UPDATE memories SET last_hit_at=?", (old_date,))
    conn.commit()
    conn.close()
    count = mem.decay_old_memories(days_threshold=7, decay_amount=0.1)
    assert count >= 1
```

- [ ] **Step 2: Run — expect failure**

```bash
docker exec virtual-company python -m pytest /app/tests/test_memory.py -v
```

Expected: `ModuleNotFoundError` — `app.services.memory` doesn't exist.

- [ ] **Step 3: Write app/services/memory.py**

```python
"""Long-term memory via SQLite FTS5 with importance-weighted retrieval."""
import sqlite3
import logging
from datetime import datetime
from pathlib import Path

from app import config

logger  = logging.getLogger(__name__)
DB_PATH = config.MEMORY_DB


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id    TEXT    NOT NULL,
                mem_type    TEXT    NOT NULL DEFAULT 'conversation',
                content     TEXT    NOT NULL,
                importance  REAL    NOT NULL DEFAULT 0.5,
                created_at  TEXT    NOT NULL,
                last_hit_at TEXT
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                content,
                agent_id UNINDEXED,
                tokenize='porter unicode61'
            );
            CREATE TABLE IF NOT EXISTS user_preferences (
                key        TEXT PRIMARY KEY,
                value      TEXT,
                updated_at TEXT
            );
        """)


def save_memory(
    agent_id: str,
    content: str,
    mem_type: str = "conversation",
    importance: float = 0.5,
) -> None:
    now = datetime.now().isoformat()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO memories (agent_id, mem_type, content, importance, created_at)"
            " VALUES (?,?,?,?,?)",
            (agent_id, mem_type, content, importance, now),
        )
        c.execute(
            "INSERT INTO memories_fts (rowid, content, agent_id) VALUES (?,?,?)",
            (cur.lastrowid, content, agent_id),
        )


def get_relevant_memories(agent_id: str, query: str, limit: int = 5) -> list[str]:
    if not query.strip():
        return []
    try:
        with _conn() as c:
            rows = c.execute("""
                SELECT m.id, m.content
                FROM   memories_fts f
                JOIN   memories m ON m.id = f.rowid
                WHERE  memories_fts MATCH ?
                  AND  m.agent_id IN (?, 'shared')
                ORDER  BY rank * m.importance
                LIMIT  ?
            """, (query, agent_id, limit)).fetchall()
            if rows:
                now = datetime.now().isoformat()
                ids = [r["id"] for r in rows]
                c.execute(
                    f"UPDATE memories SET last_hit_at=? WHERE id IN ({','.join('?'*len(ids))})",
                    [now] + ids,
                )
            return [r["content"] for r in rows]
    except sqlite3.OperationalError as exc:
        logger.warning("memory query failed: %s", exc)
        return []


def save_preference(key: str, value: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO user_preferences (key, value, updated_at) VALUES (?,?,?)",
            (key, value, datetime.now().isoformat()),
        )


def get_preference(key: str, default: str = "") -> str:
    with _conn() as c:
        row = c.execute("SELECT value FROM user_preferences WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def decay_old_memories(days_threshold: int = 7, decay_amount: float = 0.05) -> int:
    with _conn() as c:
        result = c.execute("""
            UPDATE memories
               SET importance = MAX(0.05, importance - ?)
             WHERE (last_hit_at IS NULL OR last_hit_at < date('now', ?))
               AND importance > 0.05
        """, (decay_amount, f"-{days_threshold} days"))
        return result.rowcount
```

- [ ] **Step 4: Run tests — expect pass**

```bash
docker exec virtual-company python -m pytest /app/tests/test_memory.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/memory.py tests/test_memory.py
git commit -m "feat: SQLite FTS5 long-term memory with importance decay"
```

---

## Task 7: Context Pre-Injection into Executor

**Files:**
- Modify: `app/agents/executor.py`

- [ ] **Step 1: Add imports at top of executor.py**

Add after existing imports:

```python
from app.services import memory as mem_svc
import pytz as _pytz
```

Then add this helper function right after `_get_ceo_context()`:

```python
_IST = _pytz.timezone("Asia/Kolkata")

def _build_context_block(agent_id: str, user_query: str) -> str:
    """Live context injected into every agent prompt."""
    try:
        memories  = mem_svc.get_relevant_memories(agent_id, user_query, limit=5)
        queue     = [i for i in state.work_queue if i.get("status") != "completed"][-3:]
        now_str   = __import__("datetime").datetime.now(_IST).strftime("%A %d %B %Y, %H:%M IST")
        mem_lines = "\n".join(f"  - {m}" for m in memories) or "  (none yet)"
        queue_str = json.dumps(queue, indent=2) if queue else "  []"
        return (
            f"\nLIVE CONTEXT [{now_str}]:\n"
            f"Active tasks:\n{queue_str}\n"
            f"Relevant memories:\n{mem_lines}\n"
        )
    except Exception:
        return ""
```

- [ ] **Step 2: Inject context into both prompt builders**

In `_build_tgpt_prompt`, find the return statement:

```python
    return (
        f"{persona}\n{tool_instructions}\n"
        f"{context}"
        f"Conversation History:\n{hist_str}\n\n"
        f"User: {user_msg}\n\n{agent['name']}:"
    )
```

Replace with:

```python
    live_ctx = _build_context_block(agent_id, user_msg)
    return (
        f"{persona}\n{tool_instructions}\n"
        f"{context}{live_ctx}"
        f"Conversation History:\n{hist_str}\n\n"
        f"User: {user_msg}\n\n{agent['name']}:"
    )
```

In `_build_claude_prompt`, find:

```python
    return (
        f"{persona}\n\n"
        f"Working directory: {config.WORK_DIR}"
        f"{context}\n"
        f"Conversation History:\n{hist_str}\n\n"
        f"User: {user_msg}"
    )
```

Replace with:

```python
    live_ctx = _build_context_block(agent_id, user_msg)
    return (
        f"{persona}\n\n"
        f"Working directory: {config.WORK_DIR}"
        f"{context}{live_ctx}\n"
        f"Conversation History:\n{hist_str}\n\n"
        f"User: {user_msg}"
    )
```

- [ ] **Step 3: Save memories after each agent response**

In `run_tgpt_agent`, after `full_resp += turn_text` at the end of the loop (after the last `if not tool_type: break`), add:

```python
    # Save to long-term memory
    try:
        mem_svc.save_memory(agent_id, prompt, mem_type="user_query", importance=0.4)
        if full_resp.strip():
            mem_svc.save_memory(agent_id, full_resp[:500], mem_type="agent_response", importance=0.3)
    except Exception:
        pass
    return full_resp
```

In `run_claude_agent`, just before `return full_resp`:

```python
    try:
        mem_svc.save_memory(agent_id, prompt, mem_type="user_query", importance=0.4)
        if full_resp.strip():
            mem_svc.save_memory(agent_id, full_resp[:500], mem_type="agent_response", importance=0.3)
    except Exception:
        pass
```

- [ ] **Step 4: Verify app still starts cleanly**

```bash
docker exec virtual-company curl -s http://localhost:3030/api/capabilities | python3 -m json.tool
```

Expected: valid JSON with capabilities list.

- [ ] **Step 5: Add pytz to requirements.txt if missing**

Check:
```bash
docker exec virtual-company python -c "import pytz"
```

If it fails, add `pytz>=2024.1` to `requirements.txt` and rebuild.

- [ ] **Step 6: Commit**

```bash
git add app/agents/executor.py requirements.txt
git commit -m "feat: live context injection (memories + queue + IST time) into all agent prompts"
```

---

## Task 8: /api/skills Endpoints + WebSocket skills in init

**Files:**
- Modify: `app/api/router.py`
- Modify: `app/api/websocket.py`

- [ ] **Step 1: Add /api/skills routes to router.py**

Add these routes to `app/api/router.py`, after the existing imports:

```python
from app.skills import skill_loader
```

Then add routes after the existing `/api/capabilities` endpoint:

```python
@router.get("/api/skills")
async def api_skills_list():
    return {
        "tools":    skill_loader.list_tools(),
        "learned":  skill_loader.list_manifests(),
    }


@router.post("/api/skills/register")
async def api_skills_register(body: dict):
    manifest   = body.get("manifest", {})
    skill_code = body.get("skill_code", "")
    test_code  = body.get("test_code", "")
    if not manifest.get("id"):
        return JSONResponse({"ok": False, "error": "manifest.id required"}, status_code=400)
    try:
        result = skill_loader.register_skill(manifest, skill_code, test_code)
        return {"ok": True, "manifest": result}
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=422)


@router.post("/api/skills/{skill_id}/rollback")
async def api_skills_rollback(skill_id: str):
    ok = skill_loader.rollback(skill_id)
    return {"ok": ok}


@router.delete("/api/skills/{skill_id}")
async def api_skills_delete(skill_id: str):
    import shutil
    skill_dir = skill_loader._dir / "learned" / skill_id
    if not skill_dir.exists():
        return JSONResponse({"ok": False, "error": "Skill not found"}, status_code=404)
    shutil.rmtree(str(skill_dir))
    skill_loader.load_all()
    return {"ok": True}
```

- [ ] **Step 2: Add skills to WS init event in websocket.py**

In `ws_endpoint()`, find the `await session.send({...init...})` block and add `"skills"` to it:

```python
    await session.send({
        "type":         "init",
        "agents":       {k: defs.public_agent_info(k, v) for k, v in agents.items()},
        "workdir":      str(state._get_workdir()),
        "work_queue":   state.work_queue,
        "backend":      backend_state.status_dict(),
        "changelog":    state.load_changelog()[-5:],
        "task_history": list(reversed(state.task_history)),
        "skills":       skill_loader.list_tools(),          # ← add this line
    })
```

Also add the import at the top of websocket.py:

```python
from app.skills import skill_loader
```

- [ ] **Step 3: Verify skills endpoint**

```bash
docker exec virtual-company curl -s http://localhost:3030/api/skills | python3 -m json.tool
```

Expected: `{"tools": [...], "learned": []}` — tools includes bash, read, write, edit, read_inbox.

- [ ] **Step 4: Commit**

```bash
git add app/api/router.py app/api/websocket.py
git commit -m "feat: /api/skills endpoints + skills list in WS init event"
```

---

## Task 9: Startup Wiring (main.py)

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: Initialize memory DB and load skills on startup**

Replace the `on_startup` function in `app/main.py`:

```python
@app.on_event("startup")
async def on_startup():
    global _poller_task
    load_state()

    # Initialize memory database
    from app.services import memory as mem_svc
    mem_svc.init_db()

    # Load all skills (core metadata + learned handlers)
    from app.skills import skill_loader
    skill_loader.load_all()

    # Start email poller
    from app.services import email_poller
    _poller_task = asyncio.create_task(email_poller.start())
```

- [ ] **Step 2: Verify clean startup**

```bash
docker compose restart virtual-company
sleep 5
docker logs virtual-company --tail 30
```

Expected: no tracebacks. Should see uvicorn startup + "Application startup complete."

- [ ] **Step 3: Commit**

```bash
git add app/main.py
git commit -m "feat: initialize memory DB + load skills at startup"
```

---

## Task 10: Ambient UI — HTML Shell

**Files:**
- Modify: `app/static/index.html`

- [ ] **Step 1: Rewrite index.html**

Replace the entire `app/static/index.html`:

```html
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Subaru</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/static/style-v5.css">
</head>
<body>

<!-- ── Header ──────────────────────────────────────────────────── -->
<header class="hdr" id="hdr">
  <div class="hdr-brand">
    <span class="brand-name">SUBARU</span>
  </div>
  <div class="hdr-pills">
    <div class="pill pill-backend" id="backend-pill" title="AI Backend">
      <span class="pill-dot" id="backend-dot">●</span>
      <span id="backend-label">Claude Sonnet</span>
    </div>
    <button class="pill pill-skills" id="skills-pill" title="Skills panel" onclick="toggleSkillsPanel()">
      <span id="skills-count">0</span> Skills
    </button>
    <div class="pill pill-queue" id="queue-pill" style="display:none">
      <span id="queue-count">0</span> Active
    </div>
    <button class="pill pill-icon" id="notif-btn" title="Notifications">🔔</button>
  </div>
</header>

<!-- ── Arc Reactor ─────────────────────────────────────────────── -->
<div class="reactor-wrap" id="reactor-wrap">
  <div class="reactor" id="reactor">
    <div class="reactor-ring reactor-ring-outer"></div>
    <div class="reactor-ring reactor-ring-mid"></div>
    <div class="reactor-core" id="reactor-core">
      <span class="reactor-label">SUBARU</span>
    </div>
  </div>
</div>

<!-- ── Agent Orbs ──────────────────────────────────────────────── -->
<div class="orbs-wrap" id="orbs-wrap">
  <!-- Populated by JS from WS init -->
</div>

<!-- ── Chat Thread ─────────────────────────────────────────────── -->
<main class="chat-main" id="chat-main" style="display:none">
  <div class="chat-thread" id="chat-thread"></div>
</main>

<!-- ── Thinking Layer ──────────────────────────────────────────── -->
<div class="thinking-layer" id="thinking-layer" style="display:none">
  <div class="thinking-steps" id="thinking-steps"></div>
</div>

<!-- ── Command Bar ─────────────────────────────────────────────── -->
<div class="cmdbar-wrap">
  <div class="cmdbar" id="cmdbar">
    <div class="cmdbar-agent-badge" id="cmdbar-badge">CEO</div>
    <textarea
      id="msg-input"
      class="cmdbar-input"
      placeholder="Ask Subaru anything..."
      rows="1"
    ></textarea>
    <label class="cmdbar-btn" title="Attach file or image" for="file-input">📎</label>
    <input type="file" id="file-input" accept="image/*,.pdf,.csv,.txt" style="display:none" multiple>
    <button class="cmdbar-btn" id="voice-btn" title="Voice input (Hey Subaru)">🎤</button>
    <button class="cmdbar-btn cmdbar-palette-btn" onclick="togglePalette()" title="Command palette (⌘K)">⌘</button>
    <button class="cmdbar-btn cmdbar-send" id="send-btn" onclick="sendMsg()">▶</button>
  </div>
  <!-- Attachment preview strip -->
  <div class="attach-strip" id="attach-strip" style="display:none"></div>
</div>

<!-- ── Skills Panel (slide-in) ─────────────────────────────────── -->
<div class="skills-panel" id="skills-panel" style="display:none">
  <div class="skills-panel-header">
    <span>SUBARU SKILLS</span>
    <button onclick="toggleSkillsPanel()">✕</button>
  </div>
  <div class="skills-section">
    <div class="skills-section-title">⚡ INTELLIGENCE</div>
    <div class="skills-grid" id="skills-intel">
      <div class="skill-chip active">Claude Sonnet</div>
      <div class="skill-chip standby">Gemini Flash</div>
      <div class="skill-chip standby">tgpt Fallback</div>
      <div class="skill-chip demand">Opus (on demand)</div>
    </div>
  </div>
  <div class="skills-section">
    <div class="skills-section-title">🛠 CORE TOOLS</div>
    <div class="skills-grid" id="skills-core"></div>
  </div>
  <div class="skills-section">
    <div class="skills-section-title">🧠 LEARNED SKILLS</div>
    <div class="skills-grid" id="skills-learned">
      <div class="skill-chip install" onclick="triggerInstallSkill()">➕ Install New</div>
    </div>
  </div>
  <div class="skills-section">
    <div class="skills-section-title">📊 TODAY</div>
    <div class="skills-stats" id="skills-stats">
      <div class="stat-row"><span>Routines run</span><span id="stat-routines">—</span></div>
      <div class="stat-row"><span>Emails sent</span><span id="stat-emails">—</span></div>
      <div class="stat-row"><span>Memory entries</span><span id="stat-memory">—</span></div>
    </div>
  </div>
</div>

<!-- ── Command Palette ─────────────────────────────────────────── -->
<div class="palette-overlay" id="palette-overlay" style="display:none" onclick="closePalette(event)">
  <div class="palette" id="palette">
    <input class="palette-input" id="palette-input" placeholder="Search or ask..." autocomplete="off">
    <div class="palette-results" id="palette-results"></div>
  </div>
</div>

<!-- ── Notification Stream ─────────────────────────────────────── -->
<div class="notif-island" id="notif-island" style="display:none">
  <div class="notif-list" id="notif-list"></div>
</div>

<!-- ── Floating Islands ───────────────────────────────────────── -->
<div class="island island-design" id="island-design" style="display:none">
  <div class="island-header">Design Preview <button onclick="hideIsland('design')">✕</button></div>
  <iframe id="design-iframe" src="/static/previews/index.html" sandbox="allow-scripts allow-same-origin"></iframe>
</div>

<div class="island island-browser" id="island-browser" style="display:none">
  <div class="island-header">Browser <button onclick="hideIsland('browser')">✕</button></div>
  <img id="browser-screenshot" src="" alt="Browser screenshot">
</div>

<script src="/static/app-v5.js"></script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add app/static/index.html
git commit -m "feat: ambient UI HTML shell with arc reactor, orbs, skills panel, command palette"
```

---

## Task 11: Ambient UI — CSS Design System

**Files:**
- Modify: `app/static/style-v5.css`

- [ ] **Step 1: Replace style-v5.css entirely**

```css
/* ── Reset + Root ──────────────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg:           hsl(220,20%,6%);
  --bg-card:      hsl(220,18%,10%);
  --bg-elevated:  hsl(220,16%,14%);
  --cyan:         hsl(185,100%,50%);
  --purple:       hsl(270,80%,65%);
  --gold:         hsl(42,100%,60%);
  --green:        hsl(140,70%,50%);
  --red:          hsl(0,80%,60%);
  --warn:         hsl(38,100%,55%);
  --text:         hsl(210,30%,90%);
  --muted:        hsl(210,15%,55%);
  --border:       hsl(220,20%,18%);
  --glow-cyan:    0 0 24px hsla(185,100%,50%,.3);
  --glow-gold:    0 0 24px hsla(42,100%,60%,.3);
  --font-brand:   'Orbitron', sans-serif;
  --font-ui:      'Inter', sans-serif;
  --font-code:    'JetBrains Mono', monospace;
  --radius:       10px;
  --transition:   150ms ease;
}

html, body { height: 100%; overflow: hidden; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-ui);
  font-size: 14px;
  display: flex;
  flex-direction: column;
}

/* ── Header ────────────────────────────────────────────────────── */
.hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 20px;
  border-bottom: 1px solid var(--border);
  background: hsla(220,20%,6%,.85);
  backdrop-filter: blur(12px);
  position: fixed; top: 0; left: 0; right: 0;
  z-index: 100;
  height: 52px;
}
.brand-name {
  font-family: var(--font-brand);
  font-size: 16px;
  font-weight: 900;
  letter-spacing: .2em;
  color: var(--gold);
  text-shadow: var(--glow-gold);
}
.hdr-pills { display: flex; gap: 8px; align-items: center; }

/* ── Pills ─────────────────────────────────────────────────────── */
.pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 20px;
  font-size: 12px;
  color: var(--muted);
  cursor: default;
  transition: var(--transition);
}
.pill-backend  { color: var(--green); border-color: hsla(140,70%,50%,.3); }
.pill-backend .pill-dot { font-size: 8px; }
.pill-skills   { cursor: pointer; }
.pill-skills:hover { border-color: var(--cyan); color: var(--cyan); }
.pill-icon     { padding: 4px 8px; cursor: pointer; }
.pill-icon:hover { background: var(--bg-elevated); }
.pill-warn     { color: var(--warn); border-color: hsla(38,100%,55%,.3); }

/* ── Arc Reactor ───────────────────────────────────────────────── */
.reactor-wrap {
  position: fixed;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -60%);
  z-index: 10;
  transition: all .5s cubic-bezier(.4,0,.2,1);
}
.reactor-wrap.active { transform: translate(-50%,-50%) scale(.55); top: 30%; }

.reactor {
  position: relative;
  width: 180px; height: 180px;
  display: flex; align-items: center; justify-content: center;
}
.reactor-ring {
  position: absolute;
  border-radius: 50%;
  border: 2px solid hsla(185,100%,50%,.2);
  animation: reactor-spin 8s linear infinite;
}
.reactor-ring-outer {
  width: 180px; height: 180px;
  border-top-color: var(--cyan);
  box-shadow: 0 0 20px hsla(185,100%,50%,.15);
}
.reactor-ring-mid {
  width: 130px; height: 130px;
  border-right-color: var(--purple);
  animation-direction: reverse;
  animation-duration: 5s;
}
.reactor-core {
  width: 80px; height: 80px;
  border-radius: 50%;
  background: radial-gradient(circle, hsla(185,100%,50%,.15) 0%, transparent 70%);
  border: 1px solid hsla(185,100%,50%,.4);
  display: flex; align-items: center; justify-content: center;
  box-shadow: var(--glow-cyan), inset 0 0 20px hsla(185,100%,50%,.1);
}
.reactor-label {
  font-family: var(--font-brand);
  font-size: 9px;
  letter-spacing: .15em;
  color: var(--cyan);
  opacity: .8;
}
@keyframes reactor-spin {
  to { transform: rotate(360deg); }
}

/* Thinking state — faster, brighter */
body.thinking .reactor-ring-outer { animation-duration: 2s; border-top-color: var(--cyan); box-shadow: var(--glow-cyan); }
body.thinking .reactor-ring-mid   { animation-duration: 1.2s; border-right-color: var(--purple); }
body.thinking .reactor-core       { box-shadow: var(--glow-cyan), inset 0 0 30px hsla(185,100%,50%,.2); }

/* ── Agent Orbs ────────────────────────────────────────────────── */
.orbs-wrap {
  position: fixed;
  bottom: 90px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  gap: 16px;
  z-index: 20;
}
.orb {
  position: relative;
  width: 44px; height: 44px;
  border-radius: 50%;
  background: var(--bg-card);
  border: 2px solid var(--border);
  cursor: pointer;
  transition: all .25s ease;
  display: flex; align-items: center; justify-content: center;
  font-size: 11px;
  font-weight: 600;
  color: var(--muted);
}
.orb:hover { transform: scale(1.15); }
.orb.active {
  border-color: var(--agent-color, var(--cyan));
  box-shadow: 0 0 16px var(--agent-color, var(--cyan));
  color: var(--agent-color, var(--cyan));
}
.orb.thinking { animation: orb-pulse 1s ease-in-out infinite; }
@keyframes orb-pulse {
  0%,100% { box-shadow: 0 0 8px var(--agent-color, var(--cyan)); }
  50%      { box-shadow: 0 0 24px var(--agent-color, var(--cyan)); }
}

/* Orb tooltip */
.orb-tooltip {
  position: absolute;
  bottom: calc(100% + 8px);
  left: 50%;
  transform: translateX(-50%);
  white-space: nowrap;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 8px 12px;
  font-size: 12px;
  pointer-events: none;
  opacity: 0;
  transition: opacity .15s;
  z-index: 200;
}
.orb:hover .orb-tooltip { opacity: 1; }
.orb-tooltip-name  { font-weight: 600; color: var(--text); }
.orb-tooltip-title { color: var(--muted); font-size: 11px; margin-top: 2px; }
.orb-tooltip-task  { color: var(--cyan); font-size: 11px; margin-top: 4px; }

/* ── Chat Thread ───────────────────────────────────────────────── */
.chat-main {
  position: fixed;
  top: 52px; bottom: 80px;
  left: 0; right: 0;
  overflow-y: auto;
  padding: 20px 24px;
  scroll-behavior: smooth;
}
.chat-thread { max-width: 780px; margin: 0 auto; display: flex; flex-direction: column; gap: 16px; }

.msg { display: flex; flex-direction: column; gap: 4px; }
.msg-header { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--muted); }
.msg-avatar {
  width: 26px; height: 26px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 10px; font-weight: 700;
  background: var(--bg-elevated);
}
.msg-body {
  padding: 12px 14px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 0 var(--radius) var(--radius) var(--radius);
  line-height: 1.6;
  max-width: 90%;
}
.msg.user .msg-body {
  background: hsla(185,100%,50%,.06);
  border-color: hsla(185,100%,50%,.15);
  align-self: flex-end;
  border-radius: var(--radius) 0 var(--radius) var(--radius);
}
.msg-body code { font-family: var(--font-code); font-size: 12px; color: var(--cyan); }
.msg-body pre  { background: var(--bg); border: 1px solid var(--border); border-radius: 6px; padding: 10px; overflow-x: auto; margin: 8px 0; }
.msg-body pre code { color: var(--text); }

/* Inline iframe card for HTML output */
.design-card {
  width: 100%; height: 280px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  margin-top: 8px;
  background: white;
}

/* ── Thinking Layer ─────────────────────────────────────────────── */
.thinking-layer {
  position: fixed;
  top: 60px; left: 24px;
  max-width: 320px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px 14px;
  z-index: 50;
  font-size: 12px;
}
.thinking-step {
  display: flex; align-items: center; gap: 8px;
  padding: 3px 0;
  color: var(--muted);
}
.thinking-step.done   { color: var(--green); }
.thinking-step.active { color: var(--cyan); }
.thinking-step-icon { font-size: 10px; }

/* ── Command Bar ───────────────────────────────────────────────── */
.cmdbar-wrap {
  position: fixed;
  bottom: 16px;
  left: 50%;
  transform: translateX(-50%);
  width: min(720px, calc(100% - 32px));
  z-index: 90;
}
.cmdbar {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 28px;
  padding: 8px 12px;
  box-shadow: 0 8px 32px hsla(0,0%,0%,.4), var(--glow-cyan);
  transition: box-shadow .2s;
}
.cmdbar:focus-within { box-shadow: 0 8px 40px hsla(0,0%,0%,.5), 0 0 0 1px var(--cyan), var(--glow-cyan); }

.cmdbar-agent-badge {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 3px 8px;
  font-size: 11px;
  font-weight: 600;
  color: var(--gold);
  white-space: nowrap;
  cursor: pointer;
  min-width: 40px;
  text-align: center;
}
.cmdbar-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: var(--text);
  font-family: var(--font-ui);
  font-size: 14px;
  resize: none;
  max-height: 120px;
  overflow-y: auto;
  line-height: 1.5;
}
.cmdbar-input::placeholder { color: var(--muted); }
.cmdbar-btn {
  background: none;
  border: none;
  color: var(--muted);
  cursor: pointer;
  font-size: 16px;
  padding: 4px 6px;
  border-radius: 8px;
  transition: var(--transition);
  line-height: 1;
}
.cmdbar-btn:hover { color: var(--text); background: var(--bg-elevated); }
.cmdbar-send {
  background: var(--cyan);
  color: var(--bg);
  border-radius: 50%;
  width: 32px; height: 32px;
  display: flex; align-items: center; justify-content: center;
  font-size: 13px;
}
.cmdbar-send:hover { background: hsl(185,100%,60%); color: var(--bg); }

/* Attachment strip */
.attach-strip {
  display: flex;
  gap: 8px;
  padding: 6px 12px 0;
  overflow-x: auto;
}
.attach-thumb {
  width: 56px; height: 56px;
  border-radius: 8px;
  object-fit: cover;
  border: 1px solid var(--border);
  cursor: pointer;
}

/* ── Skills Panel ───────────────────────────────────────────────── */
.skills-panel {
  position: fixed;
  top: 52px; right: 0; bottom: 0;
  width: 300px;
  background: var(--bg-card);
  border-left: 1px solid var(--border);
  padding: 16px;
  overflow-y: auto;
  z-index: 80;
  animation: slide-in-right .2s ease;
}
@keyframes slide-in-right { from { transform: translateX(100%); } }
.skills-panel-header {
  display: flex; justify-content: space-between; align-items: center;
  font-family: var(--font-brand);
  font-size: 12px;
  letter-spacing: .1em;
  color: var(--gold);
  margin-bottom: 16px;
}
.skills-panel-header button { background: none; border: none; color: var(--muted); cursor: pointer; font-size: 14px; }
.skills-section { margin-bottom: 16px; }
.skills-section-title { font-size: 11px; color: var(--muted); letter-spacing: .08em; margin-bottom: 8px; }
.skills-grid { display: flex; flex-wrap: wrap; gap: 6px; }
.skill-chip {
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 11px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  color: var(--muted);
}
.skill-chip.active  { color: var(--green);  border-color: hsla(140,70%,50%,.4); }
.skill-chip.standby { color: var(--muted);  opacity: .6; }
.skill-chip.demand  { color: var(--purple); border-color: hsla(270,80%,65%,.4); }
.skill-chip.tool    { color: var(--cyan);   border-color: hsla(185,100%,50%,.3); }
.skill-chip.learned { color: var(--gold);   border-color: hsla(42,100%,60%,.3); }
.skill-chip.install { color: var(--cyan);   cursor: pointer; border-style: dashed; }
.skill-chip.install:hover { background: hsla(185,100%,50%,.08); }

.skills-stats { display: flex; flex-direction: column; gap: 4px; }
.stat-row { display: flex; justify-content: space-between; font-size: 12px; color: var(--muted); padding: 3px 0; border-bottom: 1px solid var(--border); }
.stat-row span:last-child { color: var(--text); }

/* ── Command Palette ────────────────────────────────────────────── */
.palette-overlay {
  position: fixed; inset: 0;
  background: hsla(0,0%,0%,.6);
  backdrop-filter: blur(4px);
  z-index: 200;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 80px;
}
.palette {
  width: min(560px, calc(100% - 32px));
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 24px 80px hsla(0,0%,0%,.6);
}
.palette-input {
  width: 100%;
  background: transparent;
  border: none;
  border-bottom: 1px solid var(--border);
  padding: 14px 18px;
  color: var(--text);
  font-size: 15px;
  font-family: var(--font-ui);
  outline: none;
}
.palette-results { max-height: 320px; overflow-y: auto; padding: 8px; }
.palette-item {
  display: flex; align-items: center; gap: 10px;
  padding: 9px 12px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text);
  transition: var(--transition);
}
.palette-item:hover, .palette-item.selected { background: hsla(185,100%,50%,.08); color: var(--cyan); }
.palette-item-icon { font-size: 15px; width: 24px; text-align: center; }
.palette-sep { height: 1px; background: var(--border); margin: 4px 0; }

/* ── Notification Island ─────────────────────────────────────────── */
.notif-island {
  position: fixed;
  bottom: 90px; right: 16px;
  width: 280px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  z-index: 70;
  max-height: 320px;
  overflow-y: auto;
}
.notif-item {
  padding: 9px 12px;
  font-size: 12px;
  border-bottom: 1px solid var(--border);
  display: flex; gap: 8px; align-items: flex-start;
}
.notif-item:last-child { border-bottom: none; }
.notif-item.success .notif-dot { color: var(--green); }
.notif-item.warn    .notif-dot { color: var(--warn); }
.notif-item.error   .notif-dot { color: var(--red); }
.notif-dot { font-size: 8px; margin-top: 3px; }
.notif-text { flex: 1; line-height: 1.4; color: var(--muted); }

/* ── Floating Islands ────────────────────────────────────────────── */
.island {
  position: fixed;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  z-index: 60;
  resize: both;
  box-shadow: 0 8px 32px hsla(0,0%,0%,.4);
}
.island-design  { top: 60px; right: 16px; width: 380px; height: 300px; }
.island-browser { top: 60px; left: 16px;  width: 380px; height: 300px; }
.island-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 7px 10px;
  font-size: 11px;
  color: var(--muted);
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border);
  cursor: move;
}
.island-header button { background: none; border: none; color: var(--muted); cursor: pointer; }
.island iframe, .island img { width: 100%; height: calc(100% - 30px); border: none; object-fit: contain; display: block; }

/* ── Tool Call badge ─────────────────────────────────────────────── */
.tool-badge {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 11px; color: var(--muted);
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 2px 8px;
  margin: 2px 0;
  font-family: var(--font-code);
}

/* ── Scrollbar ───────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
```

- [ ] **Step 2: Commit**

```bash
git add app/static/style-v5.css
git commit -m "feat: full ambient design system (arc reactor, orbs, skills panel, palette)"
```

---

## Task 12: Ambient UI — JavaScript

**Files:**
- Modify: `app/static/app-v5.js`

- [ ] **Step 1: Replace app-v5.js**

```javascript
/* ── Subaru Command Center — app-v5.js ─────────────────────────── */

// ── State ──────────────────────────────────────────────────────────
const S = {
  ws:            null,
  agents:        {},
  agentOrder:    [],
  activeAgent:   "ceo",
  backend:       "claude",
  chatLogs:      {},
  statuses:      {},
  workQueue:     [],
  thinkingSteps: [],
  attachments:   [],   // {name, type, dataUrl, base64}
  reconnTimer:   null,
  voiceActive:   false,
  skills:        [],
};

// ── Helpers ────────────────────────────────────────────────────────
const $  = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);
const $id = (id) => document.getElementById(id);

function escHtml(s) {
  return String(s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

function fmtMd(text) {
  // Minimal markdown: code blocks, inline code, bold
  return text
    .replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) =>
      `<pre><code>${escHtml(code)}</code></pre>`)
    .replace(/`([^`]+)`/g, (_, c) => `<code>${escHtml(c)}</code>`)
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>');
}

function pushNotif(text, type = "success") {
  const list = $id("notif-list");
  const item = document.createElement("div");
  item.className = `notif-item ${type}`;
  item.innerHTML = `<span class="notif-dot">●</span><span class="notif-text">${escHtml(text)}</span>`;
  list.prepend(item);
  $id("notif-island").style.display = "block";
  setTimeout(() => item.remove(), 8000);
}

// ── Arc Reactor ────────────────────────────────────────────────────
function setReactorState(state) {
  // state: "idle" | "thinking" | "error"
  document.body.classList.remove("thinking", "error");
  if (state !== "idle") document.body.classList.add(state);
}

function showChatMode() {
  $id("reactor-wrap").classList.add("active");
  $id("chat-main").style.display = "block";
}

function hideChatMode() {
  $id("reactor-wrap").classList.remove("active");
  $id("chat-main").style.display = "none";
}

// ── Agent Orbs ─────────────────────────────────────────────────────
function renderOrbs() {
  const wrap = $id("orbs-wrap");
  wrap.innerHTML = "";
  S.agentOrder.forEach(id => {
    const a   = S.agents[id];
    const orb = document.createElement("div");
    orb.className = "orb" + (id === S.activeAgent ? " active" : "");
    orb.id        = `orb-${id}`;
    orb.style.setProperty("--agent-color", a.color);
    orb.innerHTML = `
      ${escHtml(a.avatar || id.slice(0,2).toUpperCase())}
      <div class="orb-tooltip">
        <div class="orb-tooltip-name">${escHtml(a.name)}</div>
        <div class="orb-tooltip-title">${escHtml(a.title)}</div>
        <div class="orb-tooltip-task" id="orb-task-${id}"></div>
      </div>`;
    orb.onclick = () => switchAgent(id);
    wrap.appendChild(orb);
  });
}

function setOrbState(agentId, state) {
  const orb = $id(`orb-${agentId}`);
  if (!orb) return;
  orb.classList.remove("thinking", "active");
  if (state === "thinking") orb.classList.add("thinking");
  if (agentId === S.activeAgent || state === "thinking") orb.classList.add("active");
}

function switchAgent(id) {
  S.activeAgent = id;
  $id("cmdbar-badge").textContent = S.agents[id]?.avatar || id.toUpperCase().slice(0,3);
  renderOrbs();
  renderChat();
}

// ── Backend Pill ────────────────────────────────────────────────────
function updateBackendPill(b) {
  S.backend = b.backend || "claude";
  const label  = $id("backend-label");
  const dot    = $id("backend-dot");
  const pill   = $id("backend-pill");
  const labels = { claude: "Claude Sonnet", gemini: "Gemini Flash", tgpt: "tgpt Fallback" };
  const colors = { claude: "var(--green)", gemini: "var(--cyan)", tgpt: "var(--warn)" };
  label.textContent    = labels[S.backend] || S.backend;
  dot.style.color      = colors[S.backend] || "var(--muted)";
  pill.style.color     = colors[S.backend] || "var(--muted)";
  if (S.backend !== "claude") {
    pushNotif(`Switched to ${labels[S.backend]}`, S.backend === "tgpt" ? "warn" : "success");
  }
}

// ── Skills Panel ────────────────────────────────────────────────────
async function loadSkills() {
  try {
    const r = await fetch("/api/skills");
    const d = await r.json();
    S.skills = d.tools || [];
    $id("skills-count").textContent = S.skills.length;

    const coreEl    = $id("skills-core");
    const learnedEl = $id("skills-learned");
    coreEl.innerHTML = "";

    S.skills.filter(t => t.zone === "core").forEach(t => {
      const chip = document.createElement("div");
      chip.className   = "skill-chip tool";
      chip.textContent = t.name;
      chip.title       = t.description;
      coreEl.appendChild(chip);
    });

    const learned = d.learned || [];
    // Keep the install button, add learned chips before it
    const installBtn = learnedEl.querySelector(".install");
    learned.forEach(m => {
      const chip = document.createElement("div");
      chip.className   = "skill-chip learned";
      chip.textContent = `${m.name} v${m.active_version}`;
      chip.title       = m.description;
      learnedEl.insertBefore(chip, installBtn);
    });
  } catch(e) { console.error("loadSkills:", e); }
}

function toggleSkillsPanel() {
  const p = $id("skills-panel");
  const showing = p.style.display !== "none";
  p.style.display = showing ? "none" : "block";
  if (!showing) loadSkills();
}

function triggerInstallSkill() {
  const name = prompt("Skill name to install (e.g. 'stripe_payments'):");
  if (!name) return;
  const prompt_text = `Learn and install a new skill called "${name}". Research the API or capability, write the skill module with tests, and register it.`;
  sendMsgText(prompt_text);
  toggleSkillsPanel();
}

// ── Command Palette ─────────────────────────────────────────────────
const PALETTE_COMMANDS = [
  { icon:"💬", label:"Ask CEO",            action: () => switchAgent("ceo") },
  { icon:"🎨", label:"Open Design Preview",action: () => showIsland("design") },
  { icon:"🌐", label:"Open Browser Panel", action: () => showIsland("browser") },
  { icon:"📋", label:"Show Routines",       action: () => sendMsgText("Show me all active routines and their last run status") },
  { icon:"▶",  label:"Run Morning Standup",action: () => fetch("/api/routines/morning_standup/run", {method:"POST"}).then(()=>pushNotif("Standup triggered")) },
  { icon:"🧠", label:"Show Skills Panel",  action: () => toggleSkillsPanel() },
  { icon:"💾", label:"Export Chat",         action: exportChat },
  { icon:"🔍", label:"Search Memory",       action: () => { closePalette(); const q=prompt("Search memory:"); if(q) sendMsgText(`Search your memory for: ${q}`); } },
  { icon:"🗑", label:"Clear Chat",          action: () => { if(confirm("Clear this chat?")) clearChat(); } },
];

let paletteIdx = 0;

function togglePalette() {
  const o = $id("palette-overlay");
  if (o.style.display !== "none") { closePalette(); return; }
  o.style.display = "flex";
  $id("palette-input").value = "";
  renderPaletteResults("");
  requestAnimationFrame(() => $id("palette-input").focus());
}

function closePalette(e) {
  if (e && e.target !== $id("palette-overlay")) return;
  $id("palette-overlay").style.display = "none";
}

function renderPaletteResults(query) {
  const q    = query.toLowerCase();
  const list = PALETTE_COMMANDS.filter(c => !q || c.label.toLowerCase().includes(q));
  const el   = $id("palette-results");
  el.innerHTML = list.map((c,i) =>
    `<div class="palette-item${i===paletteIdx?" selected":""}" onclick="runPaletteCmd(${PALETTE_COMMANDS.indexOf(c)})">
      <span class="palette-item-icon">${c.icon}</span>${escHtml(c.label)}
    </div>`
  ).join("");
}

function runPaletteCmd(idx) {
  closePalette(null);
  PALETTE_COMMANDS[idx]?.action?.();
}

// ── Thinking Layer ──────────────────────────────────────────────────
function addThinkingStep(text, state = "active") {
  const steps = $id("thinking-steps");
  const layer = $id("thinking-layer");
  const el    = document.createElement("div");
  el.className = `thinking-step ${state}`;
  el.innerHTML = `<span class="thinking-step-icon">${state==="done"?"✓":"→"}</span>${escHtml(text)}`;
  steps.appendChild(el);
  layer.style.display = "block";
}

function clearThinking() {
  $id("thinking-steps").innerHTML = "";
  $id("thinking-layer").style.display = "none";
}

// ── Chat ────────────────────────────────────────────────────────────
function renderChat() {
  const thread = $id("chat-thread");
  const logs   = S.chatLogs[S.activeAgent] || [];
  thread.innerHTML = "";
  const agent  = S.agents[S.activeAgent] || {};
  logs.forEach(m => {
    const isUser = m.role === "user";
    const div    = document.createElement("div");
    div.className = `msg ${isUser ? "user" : "agent"}`;
    div.innerHTML = `
      <div class="msg-header">
        <div class="msg-avatar" style="background:${isUser?"var(--bg-elevated)":agent.color||"var(--cyan)"}">
          ${isUser?"ME": escHtml(agent.avatar||"AI")}
        </div>
        <span>${isUser?"You": escHtml(agent.name||S.activeAgent)}</span>
      </div>
      <div class="msg-body">${fmtMd(m.content || "")}</div>`;
    thread.appendChild(div);
  });
  thread.scrollTop = thread.scrollHeight;
  if (logs.length > 0) showChatMode();
}

function appendMsg(agentId, role, content) {
  if (!S.chatLogs[agentId]) S.chatLogs[agentId] = [];
  S.chatLogs[agentId].push({ role, content });
  if (agentId === S.activeAgent) renderChat();
}

// ── File Attachments ────────────────────────────────────────────────
function initFileInput() {
  $id("file-input").addEventListener("change", async (e) => {
    const strip = $id("attach-strip");
    for (const file of e.target.files) {
      const reader = new FileReader();
      reader.onload = (re) => {
        const dataUrl = re.target.result;
        const base64  = dataUrl.split(",")[1];
        S.attachments.push({ name: file.name, type: file.type, dataUrl, base64 });
        if (file.type.startsWith("image/")) {
          strip.innerHTML += `<img class="attach-thumb" src="${dataUrl}" title="${escHtml(file.name)}" onclick="this.remove()">`;
        } else {
          strip.innerHTML += `<div class="skill-chip tool" title="${escHtml(file.name)}" style="cursor:pointer">📄 ${escHtml(file.name)}</div>`;
        }
        strip.style.display = "flex";
      };
      reader.readAsDataURL(file);
    }
  });

  // Drag-drop on body
  document.body.addEventListener("dragover", e => e.preventDefault());
  document.body.addEventListener("drop", e => {
    e.preventDefault();
    const input = $id("file-input");
    input.files = e.dataTransfer.files;
    input.dispatchEvent(new Event("change"));
  });
}

// ── Send ─────────────────────────────────────────────────────────────
function sendMsg() {
  const input = $id("msg-input");
  const text  = input.value.trim();
  if (!text && S.attachments.length === 0) return;
  sendMsgText(text);
  input.value = "";
  input.style.height = "auto";
  S.attachments = [];
  $id("attach-strip").style.display = "none";
  $id("attach-strip").innerHTML = "";
  $id("file-input").value = "";
}

function sendMsgText(text) {
  if (!S.ws || S.ws.readyState !== WebSocket.OPEN) { pushNotif("Not connected","error"); return; }
  const payload = {
    type:   "message",
    agent:  S.activeAgent,
    text,
  };
  if (S.attachments.length > 0) {
    payload.attachments = S.attachments.map(a => ({
      media_type: a.type, data: a.base64, name: a.name,
    }));
  }
  S.ws.send(JSON.stringify(payload));
  appendMsg(S.activeAgent, "user", text + (S.attachments.length ? ` [+${S.attachments.length} file(s)]` : ""));
  showChatMode();
  setReactorState("thinking");
}

function clearChat() {
  if (!S.ws) return;
  S.ws.send(JSON.stringify({ type: "clear", agent: S.activeAgent }));
}

function exportChat() {
  const logs = S.chatLogs[S.activeAgent] || [];
  const txt  = logs.map(m => `[${m.role}] ${m.content}`).join("\n\n");
  const a    = document.createElement("a");
  a.href     = URL.createObjectURL(new Blob([txt], {type:"text/plain"}));
  a.download = `subaru-chat-${S.activeAgent}-${Date.now()}.txt`;
  a.click();
}

// ── Floating Islands ─────────────────────────────────────────────────
function showIsland(name) {
  $id(`island-${name}`).style.display = "block";
}
function hideIsland(name) {
  $id(`island-${name}`).style.display = "none";
}

// Make islands draggable
document.addEventListener("DOMContentLoaded", () => {
  $$(".island").forEach(island => {
    const header = island.querySelector(".island-header");
    if (!header) return;
    let ox=0, oy=0, mx=0, my=0;
    header.onmousedown = (e) => {
      e.preventDefault();
      mx = e.clientX; my = e.clientY;
      document.onmousemove = (e2) => {
        ox = mx - e2.clientX; oy = my - e2.clientY;
        mx = e2.clientX;      my = e2.clientY;
        island.style.top  = (island.offsetTop  - oy) + "px";
        island.style.left = (island.offsetLeft - ox) + "px";
      };
      document.onmouseup = () => {
        document.onmousemove = null;
        document.onmouseup   = null;
      };
    };
  });
});

// ── WebSocket ─────────────────────────────────────────────────────────
function boot() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const url   = `${proto}//${location.host}/ws`;
  S.ws = new WebSocket(url);

  S.ws.onopen = () => {
    clearTimeout(S.reconnTimer);
    pushNotif("Subaru online", "success");
  };

  S.ws.onmessage = ({ data }) => {
    let obj;
    try { obj = JSON.parse(data); } catch { return; }
    dispatch(obj);
  };

  S.ws.onclose = () => {
    pushNotif("Connection lost — reconnecting…", "warn");
    S.reconnTimer = setTimeout(boot, 3000);
  };
}

function dispatch(obj) {
  const type    = obj.type;
  const agentId = obj.agent || "ceo";

  switch (type) {
    case "init":
      S.agents    = obj.agents    || {};
      S.agentOrder= Object.keys(S.agents);
      S.workQueue = obj.work_queue || [];
      S.agentOrder.forEach(id => {
        if (!S.chatLogs[id]) S.chatLogs[id] = [];
      });
      if (obj.skills) {
        S.skills = obj.skills;
        $id("skills-count").textContent = S.skills.length;
      }
      if (obj.backend) updateBackendPill(obj.backend);
      renderOrbs();
      updateQueuePill();
      break;

    case "thinking":
      setOrbState(agentId, "thinking");
      setReactorState("thinking");
      addThinkingStep(`${S.agents[agentId]?.name || agentId} thinking…`);
      break;

    case "assistant":
      const blocks = obj.message?.content || [];
      blocks.forEach(b => {
        if (b.type === "text" && b.text) appendMsg(agentId, "assistant", b.text);
      });
      break;

    case "tool_call":
      addThinkingStep(`${obj.label || obj.tool}: ${obj.path || ""}`, "active");
      break;

    case "done":
    case "worker_done":
      setOrbState(agentId, "idle");
      setReactorState("idle");
      clearThinking();
      if (obj.summary) appendMsg(agentId, "assistant", `✓ ${obj.summary}`);
      break;

    case "backend_switch":
    case "backend_status":
      updateBackendPill(obj);
      break;

    case "skill_installed":
      pushNotif(`Skill installed: ${obj.skill_name || "new skill"}`, "success");
      loadSkills();
      break;

    case "delegation":
      pushNotif(`Delegated to ${obj.item?.agent}: ${(obj.item?.task||"").slice(0,60)}…`);
      break;

    case "queue_update":
      S.workQueue = obj.work_queue || [];
      updateQueuePill();
      break;

    case "failover":
      pushNotif(obj.message || "Backend switched", "warn");
      break;

    case "error":
      setReactorState("idle");
      clearThinking();
      pushNotif(obj.message || "Error", "error");
      break;

    case "email_sent":
      pushNotif(`Email: ${obj.subject}`, obj.ok ? "success" : "error");
      break;
  }
}

function updateQueuePill() {
  const active = (S.workQueue || []).filter(i => i.status === "running" || i.status === "pending").length;
  const pill   = $id("queue-pill");
  pill.style.display = active > 0 ? "inline-flex" : "none";
  $id("queue-count").textContent = active;
}

// ── Keyboard shortcuts ────────────────────────────────────────────────
document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "k") {
    e.preventDefault();
    togglePalette();
  }
  if (e.key === "Escape") {
    closePalette(null);
    $id("skills-panel").style.display = "none";
  }
  if ($id("palette-overlay").style.display !== "none") {
    if (e.key === "ArrowDown") { paletteIdx = Math.min(paletteIdx+1, PALETTE_COMMANDS.length-1); renderPaletteResults($id("palette-input").value); }
    if (e.key === "ArrowUp")   { paletteIdx = Math.max(paletteIdx-1, 0); renderPaletteResults($id("palette-input").value); }
    if (e.key === "Enter")     { const items = $$(".palette-item"); if(items[paletteIdx]) items[paletteIdx].click(); }
  }
});

// ── Input auto-resize ─────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  const inp = $id("msg-input");
  inp.addEventListener("input", () => {
    inp.style.height = "auto";
    inp.style.height = Math.min(inp.scrollHeight, 120) + "px";
  });
  inp.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMsg(); }
  });

  $id("palette-input").addEventListener("input", (e) => {
    paletteIdx = 0;
    renderPaletteResults(e.target.value);
  });

  initFileInput();
  boot();
});
```

- [ ] **Step 2: Commit**

```bash
git add app/static/app-v5.js
git commit -m "feat: ambient JS — arc reactor, agent orbs, skills panel, command palette, WS dispatch"
```

---

## Task 13: End-to-End Smoke Test

- [ ] **Step 1: Full test suite**

```bash
docker exec virtual-company python -m pytest /app/tests/ -v
```

Expected: all tests PASS (backend_state × 7, skill_loader × 5, memory × 7 = 19 total).

- [ ] **Step 2: App loads in browser**

Open `http://localhost:3030` in Chrome.

Verify:
- Arc reactor visible and spinning
- "SUBARU" brand in header
- Command bar at bottom with `⌘K` button
- Header shows "Claude Sonnet" backend pill in green

- [ ] **Step 3: Skills panel opens**

Click the `0 Skills` pill in the header.

Verify:
- Slide-in panel appears
- Core tools (bash, read, write, edit, read_inbox) shown as cyan chips
- Intelligence section shows 4 model chips

- [ ] **Step 4: Command palette opens**

Press `Ctrl+K` or `Cmd+K`.

Verify:
- Dark overlay + search box appears
- All 9 commands listed
- Typing filters the list
- `Esc` closes it

- [ ] **Step 5: Send a message**

Type "Hello, what can you do?" and press Enter.

Verify:
- Arc reactor enters thinking state (faster spin)
- Orb for CEO pulses
- Thinking layer appears
- CEO responds in chat thread
- Arc reactor returns to idle

- [ ] **Step 6: Backend fallback display**

```bash
# Check backend status via API
docker exec virtual-company curl -s http://localhost:3030/api/capabilities | python3 -m json.tool
```

Expected: `email_configured`, capabilities list all present.

- [ ] **Step 7: Register a test skill via API**

```bash
docker exec virtual-company curl -s -X POST http://localhost:3030/api/skills/register \
  -H "Content-Type: application/json" \
  -d '{
    "manifest": {"id":"ping","name":"Ping","active_version":"1","description":"Simple ping","tools":["ping"],"available_to":["all"],"safety_zone":"low","author":"test"},
    "skill_code": "TOOLS=[{\"name\":\"ping\",\"description\":\"ping\"}]\nasync def handle_ping(args): return \"pong\"",
    "test_code": "import pytest\n@pytest.mark.asyncio\nasync def test_ping():\n    from app.skills.learned.ping.v1.skill import handle_ping\n    assert await handle_ping({}) == \"pong\""
  }'
```

Expected: `{"ok": true, "manifest": {...}}`

Reload skills panel — "Ping v1" should appear under Learned Skills.

- [ ] **Step 8: Final commit**

```bash
git add -A
git commit -m "feat: Subaru Foundation complete — 3-tier AI router, SkillRegistry, FTS5 memory, Ambient UI"
```

---

## Self-Review

**Spec coverage check:**

| Spec Section | Covered By |
|---|---|
| System rename to Subaru | Task 10 (HTML brand), Task 12 (app-v5.js) |
| Model routing (Sonnet default, Haiku, Opus) | Task 1 (config), Task 2 (backend_state) |
| 3-tier AI Router | Task 2 (backend_state) + Task 3 (executor) |
| Gemini API (google-genai) | Task 3 |
| Skill Registry + SkillLoader | Task 4 |
| Core tool metadata | Task 4 (core/*.py) |
| Learned skill dispatch | Task 5 |
| /api/skills endpoints | Task 8 |
| SQLite FTS5 memory | Task 6 |
| Context pre-injection | Task 7 |
| skills in WS init | Task 8 |
| Startup wiring | Task 9 |
| Ambient UI shell | Task 10 (HTML), Task 11 (CSS), Task 12 (JS) |
| Arc reactor | Task 11 (CSS), Task 12 (JS) |
| Agent orbs | Task 11 (CSS), Task 12 (JS) |
| Skills panel | Task 10 (HTML), Task 11 (CSS), Task 12 (JS) |
| Command palette ⌘K | Task 10 (HTML), Task 11 (CSS), Task 12 (JS) |
| Floating islands | Task 10 (HTML), Task 11 (CSS), Task 12 (JS) |
| Image drag-drop (attachment) | Task 12 (JS) |

**Phases deferred to follow-up plans (out of scope for this plan):**
- Phase 5: Routines Engine (needs `croniter`, scheduler.py, /api/routines)
- Phase 6: Claude Design Panel (needs preview writer + agent tool)
- Phase 7: Playwright Browser (needs Docker rebuild + browser.py)
- Phase 8: Voice / Hey Subaru (browser STT/TTS)
- Phase 9: Morning Standup (depends on routines)
- Phase 10: Claude Vision multimodal path (needs anthropic SDK streaming)
- Phase 12: Multi-agent [ASK:] collaboration
- Phase 13: Self-Healing zone guard + email approval
