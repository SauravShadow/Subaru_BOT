# LangGraph Transformation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the manual orchestration in `executor.py`, `websocket.py`, `delegation.py`, `email_poller.py`, and `state/manager.py` with two LangGraph graphs (`nexus_graph` + `email_graph`) sharing one `AsyncSqliteSaver` checkpointer on `nexus.db`.

**Architecture:** Two compiled LangGraph graphs — `nexus_graph` (WebSocket-driven, real-time) and `email_graph` (email-driven, long-lived with interrupt gates). Both share one `AsyncSqliteSaver` on `nexus.db`. Worker agents run inside subgraph nodes as black-box async functions; all existing execution code (Claude CLI subprocess, Gemini API, tgpt) is preserved in `app/agents/runner.py` (renamed from `executor.py`).

**Tech Stack:** `langgraph>=0.3.0`, `langgraph-checkpoint-sqlite>=0.1.0`, `langchain-google-genai>=2.0.0`, `langchain-core>=0.3.0`. No `ANTHROPIC_API_KEY` required — Claude CLI subprocess (CLAUDE_BIN), Gemini API (GEMINI_API_KEY), and tgpt (TGPT_BIN) all preserved.

**Spec:** `docs/superpowers/specs/2026-06-10-langgraph-transformation-design.md`

---

## File Map

| Action | File | Purpose |
|---|---|---|
| Create | `app/graph/__init__.py` | package marker |
| Create | `app/graph/state.py` | NexusState, WorkerState, EmailState TypedDicts |
| Create | `app/graph/checkpointer.py` | singleton AsyncSqliteSaver("nexus.db") |
| Create | `app/graph/broadcast.py` | thread_id → send_fn registry (avoids circular import) |
| Create | `app/graph/nodes/__init__.py` | package marker |
| Create | `app/graph/nodes/ceo.py` | CEO node: run_claude_agent + [DELEGATE:] parsing |
| Create | `app/graph/nodes/review.py` | CEO review node: Gemini structured ReviewDecision |
| Create | `app/graph/nodes/output.py` | output pipeline node: wraps pipeline.process() |
| Create | `app/graph/workers/__init__.py` | package marker |
| Create | `app/graph/workers/tools/__init__.py` | package marker |
| Create | `app/graph/workers/tools/core.py` | list_available_skills + call_skill meta-tools |
| Create | `app/graph/workers/base.py` | make_worker_graph() subgraph factory |
| Create | `app/graph/nexus_graph.py` | compiled nexus_graph + route_after_ceo + route_after_review |
| Create | `app/graph/email/__init__.py` | package marker |
| Create | `app/graph/email/nodes.py` | 7 email graph nodes |
| Create | `app/graph/email/graph.py` | compiled email_graph + build_email_graph() |
| Create | `tests/graph/__init__.py` | package marker |
| Create | `tests/graph/conftest.py` | shared fixtures |
| Create | `tests/graph/test_state.py` | TypedDict shape tests |
| Create | `tests/graph/test_ceo_node.py` | delegation parsing tests |
| Create | `tests/graph/test_review_node.py` | ReviewDecision + prompt tests |
| Create | `tests/graph/test_event_translation.py` | _translate_event() mapping tests |
| Create | `tests/graph/test_email_graph.py` | email state machine transition tests |
| Rename | `app/agents/executor.py` → `app/agents/runner.py` | pure rename, no code change |
| Rewrite | `app/api/websocket.py` | gut to ~120 LOC: Session, astream_events, _translate_event |
| Rewrite | `app/services/email_poller.py` | gut to ~100 LOC: IMAP poll + graph dispatch |
| Modify | `app/state/manager.py` | remove work_queue, active_agent_tasks, save_state/load_state |
| Modify | `app/main.py` | switch to lifespan, wire graphs and email_poller |
| Modify | `requirements.txt` | add 4 langgraph deps |
| Delete | `app/agents/executor.py` | replaced by runner.py + graph nodes |
| Delete | `app/services/delegation.py` | logic inlined into ceo.py |

---

## Task 1: Add LangGraph Dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add deps to requirements.txt**

Append these four lines to `requirements.txt`:
```
langgraph>=0.3.0
langgraph-checkpoint-sqlite>=0.1.0
langchain-google-genai>=2.0.0
langchain-core>=0.3.0
```

- [ ] **Step 2: Install inside the running container**

```bash
docker exec nexus-ceo pip install langgraph langgraph-checkpoint-sqlite langchain-google-genai langchain-core
```

Expected: all four packages install without error.

- [ ] **Step 3: Verify imports**

```bash
docker exec nexus-ceo python -c "import langgraph; import langgraph_checkpoint_sqlite; import langchain_google_genai; print('OK')"
```

Expected output: `OK`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: add langgraph + langchain-google-genai deps"
```

---

## Task 2: Create app/graph/ Skeleton

**Files:**
- Create: `app/graph/__init__.py`
- Create: `app/graph/nodes/__init__.py`
- Create: `app/graph/workers/__init__.py`
- Create: `app/graph/workers/tools/__init__.py`
- Create: `app/graph/email/__init__.py`
- Create: `tests/graph/__init__.py`
- Create: `tests/graph/conftest.py`

- [ ] **Step 1: Create all package markers**

```bash
mkdir -p app/graph/nodes app/graph/workers/tools app/graph/email tests/graph
touch app/graph/__init__.py app/graph/nodes/__init__.py
touch app/graph/workers/__init__.py app/graph/workers/tools/__init__.py
touch app/graph/email/__init__.py
touch tests/graph/__init__.py
```

- [ ] **Step 2: Create tests/graph/conftest.py**

```python
# tests/graph/conftest.py
import sys
from pathlib import Path
sys.path.insert(0, "/app")
```

- [ ] **Step 3: Verify package import works**

```bash
docker exec nexus-ceo python -c "import app.graph; print('graph package OK')"
```

Expected: `graph package OK`

- [ ] **Step 4: Commit**

```bash
git add app/graph/ tests/graph/
git commit -m "feat: create app/graph/ skeleton directories"
```

---

## Task 3: Shared State Types

**Files:**
- Create: `app/graph/state.py`
- Create: `tests/graph/test_state.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/graph/test_state.py
import operator
import pytest
from typing import get_type_hints
from app.graph.state import NexusState, WorkerState, EmailState

def test_nexus_state_has_required_keys():
    state: NexusState = {
        "task": "build an API",
        "source": "browser",
        "session_id": "test-123",
        "model": "claude",
        "ceo_response": "",
        "delegations": [],
        "artifacts": {},
        "worker_results": [],
        "ceo_verdict": "approved",
        "revision_notes": "",
        "worker_progress": {},
    }
    assert state["task"] == "build an API"
    assert state["worker_results"] == []
    assert state["worker_progress"] == {}

def test_worker_state_has_required_keys():
    state: WorkerState = {
        "task": "build routes",
        "agent_id": "backend",
        "model": "claude",
        "artifacts": {},
        "messages": [],
        "result": "",
        "new_artifacts": {},
    }
    assert state["agent_id"] == "backend"
    assert state["messages"] == []

def test_email_state_has_required_keys():
    state: EmailState = {
        "email": {"from_email": "user@test.com", "subject": "test"},
        "is_owner": True,
        "verified": False,
        "plan": "",
        "user_reply": "",
        "execution_result": "",
        "port_used": "",
        "subdomain": "",
        "sent_message_ids": [],
    }
    assert state["is_owner"] is True
    assert state["sent_message_ids"] == []
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
docker exec nexus-ceo pytest tests/graph/test_state.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.graph.state'`

- [ ] **Step 3: Create app/graph/state.py**

```python
# app/graph/state.py
"""Shared state TypedDicts for all NEXUS LangGraph graphs."""
import operator
from typing import Annotated, Literal
from typing_extensions import TypedDict
from langgraph.graph import add_messages


class NexusState(TypedDict):
    task: str
    source: Literal["browser", "api"]
    session_id: str
    model: str

    ceo_response: str
    delegations: list[dict]
    artifacts: dict

    worker_results: Annotated[list[dict], operator.add]

    ceo_verdict: Literal["approved", "revise", "delegate_more", "done"]
    revision_notes: str

    worker_progress: dict  # {agent_id: {"step": int, "checkpoints": list[str]}}


class WorkerState(TypedDict):
    task: str
    agent_id: str
    model: str
    artifacts: dict
    messages: Annotated[list, add_messages]
    result: str
    new_artifacts: dict


class EmailState(TypedDict):
    email: dict
    is_owner: bool
    verified: bool
    plan: str
    user_reply: str
    execution_result: str
    port_used: str
    subdomain: str
    sent_message_ids: list[str]
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
docker exec nexus-ceo pytest tests/graph/test_state.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add app/graph/state.py tests/graph/test_state.py tests/graph/conftest.py
git commit -m "feat: add NexusState, WorkerState, EmailState TypedDicts"
```

---

## Task 4: Checkpointer Singleton

**Files:**
- Create: `app/graph/checkpointer.py`

- [ ] **Step 1: Create app/graph/checkpointer.py**

```python
# app/graph/checkpointer.py
"""Singleton AsyncSqliteSaver shared by nexus_graph and email_graph."""
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from app import config

_checkpointer: AsyncSqliteSaver | None = None


async def get_checkpointer() -> AsyncSqliteSaver:
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = AsyncSqliteSaver.from_conn_string(str(config.MEMORY_DB))
        await _checkpointer.setup()
    return _checkpointer
```

- [ ] **Step 2: Verify import**

```bash
docker exec nexus-ceo python -c "from app.graph.checkpointer import get_checkpointer; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/graph/checkpointer.py
git commit -m "feat: add AsyncSqliteSaver singleton checkpointer"
```

---

## Task 5: Broadcast Registry

**Files:**
- Create: `app/graph/broadcast.py`

This module breaks the circular import between `graph/workers/base.py` (which needs to send WS events) and `api/websocket.py` (which imports the graph). Workers register a send function keyed by `thread_id`; the WebSocket registers itself before starting a run.

- [ ] **Step 1: Create app/graph/broadcast.py**

```python
# app/graph/broadcast.py
"""Thread-scoped broadcast registry — decouples worker nodes from websocket.py."""
import asyncio
import logging
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

_registry: dict[str, Callable[[dict], Awaitable[None]]] = {}


def register(thread_id: str, fn: Callable[[dict], Awaitable[None]]) -> None:
    _registry[thread_id] = fn


def unregister(thread_id: str) -> None:
    _registry.pop(thread_id, None)


async def send(thread_id: str, data: dict) -> None:
    fn = _registry.get(thread_id)
    if fn:
        try:
            await fn(data)
        except Exception as exc:
            logger.warning("broadcast send error for %s: %s", thread_id, exc)


async def noop_send(data: dict) -> None:
    pass
```

- [ ] **Step 2: Verify import**

```bash
docker exec nexus-ceo python -c "from app.graph.broadcast import register, send; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/graph/broadcast.py
git commit -m "feat: add broadcast registry for worker→websocket event routing"
```

---

## Task 6: Rename executor.py → runner.py

**Files:**
- Rename: `app/agents/executor.py` → `app/agents/runner.py`

This is a pure rename. All execution functions (run_agent, run_claude_agent, run_gemini_agent, run_tgpt_agent, _execute_tool, etc.) stay unchanged. The module docstring is updated.

- [ ] **Step 1: Rename the file**

```bash
cd /home/subaru/projects/virtual-company && git mv app/agents/executor.py app/agents/runner.py
```

- [ ] **Step 2: Update the module docstring in runner.py**

Find the first line of runner.py:
```python
"""
Agent execution engine.
Provides run_agent() — a multi-turn agentic loop that calls tgpt or Claude CLI
and pipes all events back through the WebSocket via a lock-protected sender.
"""
```

Replace with:
```python
"""
Agent execution engine (runner).
Provides run_agent() — multi-turn agentic loop routing through Claude CLI,
Gemini API, or tgpt. Called from LangGraph worker nodes as a black-box function.
"""
```

- [ ] **Step 3: Update imports in existing callers**

Find all files that import from executor:
```bash
grep -r "from app.agents.executor\|from app\.agents import executor\|agents\.executor" /home/subaru/projects/virtual-company --include="*.py" -l
```

For each file found, update `app.agents.executor` → `app.agents.runner`.

Files to check: `app/api/websocket.py`, `app/services/email_poller.py`, `tests/test_executor_gemini.py`, any others found.

In each file, replace:
```python
from app.agents.executor import ...
```
with:
```python
from app.agents.runner import ...
```

- [ ] **Step 4: Run existing tests to verify nothing broke**

```bash
docker exec nexus-ceo pytest tests/ -v --ignore=tests/graph -x -q 2>&1 | tail -20
```

Expected: same pass/fail ratio as before the rename. Any import failures mean a missed reference — fix them.

- [ ] **Step 5: Commit**

```bash
git add app/agents/runner.py
git rm app/agents/executor.py 2>/dev/null || true
git add -u
git commit -m "refactor: rename executor.py → runner.py (pure rename, no behavior change)"
```

---

## Task 7: CEO Node

**Files:**
- Create: `app/graph/nodes/ceo.py`
- Create: `tests/graph/test_ceo_node.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/graph/test_ceo_node.py
import pytest
from app.graph.nodes.ceo import parse_delegations_from_response


def test_parse_single_delegation():
    text = "Let's do it!\n[DELEGATE:backend] Build the REST API."
    result = parse_delegations_from_response(text)
    assert result == [{"agent": "backend", "task": "Build the REST API."}]


def test_parse_multiple_delegations():
    text = (
        "Kicking off.\n"
        "[DELEGATE:backend] Build API endpoints.\n"
        "[DELEGATE:frontend] Build the React UI."
    )
    result = parse_delegations_from_response(text)
    assert len(result) == 2
    assert result[0] == {"agent": "backend", "task": "Build API endpoints."}
    assert result[1] == {"agent": "frontend", "task": "Build the React UI."}


def test_parse_no_delegations():
    text = "I'll handle this directly. No workers needed."
    result = parse_delegations_from_response(text)
    assert result == []


def test_inline_mention_not_parsed():
    text = "Say the word and I'll get [DELEGATE:browser] Maya on it."
    result = parse_delegations_from_response(text)
    assert result == []


def test_invalid_agent_skipped():
    text = "[DELEGATE:nonexistent] Some task."
    result = parse_delegations_from_response(text)
    assert result == []


def test_multiline_task_captured():
    text = "[DELEGATE:backend] Build the API.\nMake it RESTful with pagination."
    result = parse_delegations_from_response(text)
    assert len(result) == 1
    assert "pagination" in result[0]["task"]
```

- [ ] **Step 2: Run to verify it fails**

```bash
docker exec nexus-ceo pytest tests/graph/test_ceo_node.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.graph.nodes.ceo'`

- [ ] **Step 3: Create app/graph/nodes/ceo.py**

```python
# app/graph/nodes/ceo.py
"""CEO (Subaru Natsuki) graph node — planning and delegation."""
import logging
import re

from app.agents.runner import run_claude_agent, _build_context_block
from app.graph.state import NexusState
from app.graph import broadcast

logger = logging.getLogger(__name__)

_DELEGATE_RE = re.compile(
    r'^\[DELEGATE:(\w+)\]\s*(.*?)(?=^\[DELEGATE:|^\[EMAIL_USER:|\Z)',
    re.DOTALL | re.MULTILINE,
)


def parse_delegations_from_response(text: str) -> list[dict]:
    """Extract [DELEGATE:agent] task blocks; ignore inline mentions."""
    from app.agents.definitions import all_agents
    valid_agents = set(all_agents().keys())
    return [
        {"agent": m.group(1).strip(), "task": m.group(2).strip()}
        for m in _DELEGATE_RE.finditer(text)
        if m.group(1).strip() in valid_agents
    ]


async def ceo_node(state: NexusState, config: dict) -> dict:
    thread_id = config.get("configurable", {}).get("thread_id", "")
    model = config.get("configurable", {}).get("model", "claude")

    async def send(data: dict) -> None:
        await broadcast.send(thread_id, data)

    task = state["task"]
    if state.get("revision_notes"):
        task = f"{task}\n\n[REVISION REQUESTED]\n{state['revision_notes']}"

    response = await run_claude_agent("ceo", task, send, model)
    delegations = parse_delegations_from_response(response)

    return {
        "ceo_response": response,
        "delegations": delegations,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec nexus-ceo pytest tests/graph/test_ceo_node.py -v
```

Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add app/graph/nodes/ceo.py tests/graph/test_ceo_node.py
git commit -m "feat: add CEO graph node with [DELEGATE:] tag parsing"
```

---

## Task 8: Review Node

**Files:**
- Create: `app/graph/nodes/review.py`
- Create: `tests/graph/test_review_node.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/graph/test_review_node.py
import pytest
from pydantic import ValidationError
from app.graph.nodes.review import ReviewDecision, build_review_prompt
from app.graph.state import NexusState


def _make_state(**overrides) -> NexusState:
    base: NexusState = {
        "task": "build REST API",
        "source": "browser",
        "session_id": "test",
        "model": "claude",
        "ceo_response": "Delegated to backend",
        "delegations": [],
        "artifacts": {},
        "worker_results": [{"agent": "backend", "result": "API built at :8090"}],
        "ceo_verdict": "approved",
        "revision_notes": "",
        "worker_progress": {},
    }
    base.update(overrides)
    return base


def test_review_decision_valid_fields():
    d = ReviewDecision(verdict="approved", notes="Good work")
    assert d.verdict == "approved"
    assert d.notes == "Good work"


def test_review_decision_all_verdicts():
    for verdict in ["approved", "revise", "delegate_more", "done"]:
        d = ReviewDecision(verdict=verdict, notes="test")
        assert d.verdict == verdict


def test_review_decision_invalid_verdict_raises():
    with pytest.raises(ValidationError):
        ReviewDecision(verdict="wrong", notes="test")


def test_build_review_prompt_includes_task():
    state = _make_state()
    prompt = build_review_prompt(state)
    assert "build REST API" in prompt


def test_build_review_prompt_includes_worker_result():
    state = _make_state()
    prompt = build_review_prompt(state)
    assert "API built at :8090" in prompt


def test_build_review_prompt_includes_revision_notes():
    state = _make_state(revision_notes="Need better error handling")
    prompt = build_review_prompt(state)
    assert "Need better error handling" in prompt
```

- [ ] **Step 2: Run to verify it fails**

```bash
docker exec nexus-ceo pytest tests/graph/test_review_node.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.graph.nodes.review'`

- [ ] **Step 3: Create app/graph/nodes/review.py**

```python
# app/graph/nodes/review.py
"""CEO review node — Gemini structured output for task verdict."""
import logging
import os
from typing import Literal

from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

from app.graph.state import NexusState

logger = logging.getLogger(__name__)


class ReviewDecision(BaseModel):
    verdict: Literal["approved", "revise", "delegate_more", "done"]
    notes: str


_review_llm: ChatGoogleGenerativeAI | None = None


def _get_review_llm() -> ChatGoogleGenerativeAI:
    global _review_llm
    if _review_llm is None:
        _review_llm = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            google_api_key=os.environ.get("GEMINI_API_KEY", ""),
        ).with_structured_output(ReviewDecision)
    return _review_llm


def build_review_prompt(state: NexusState) -> str:
    results_text = "\n".join(
        f"[{r['agent']}]: {r['result'][:500]}"
        for r in state.get("worker_results", [])
    )
    revision_section = ""
    if state.get("revision_notes"):
        revision_section = f"\n\nPrevious revision notes: {state['revision_notes']}"

    return f"""You are the CEO reviewing worker output for the task:

TASK: {state['task']}

WORKER RESULTS:
{results_text or '(no results yet)'}
{revision_section}

ARTIFACTS AVAILABLE: {list(state.get('artifacts', {}).keys())}

Verdict options:
- "approved" — task is complete and correct
- "done" — task is complete (use when all goals met)
- "revise" — workers need to fix something (explain in notes)
- "delegate_more" — additional workers needed (explain in notes)

Be concise. Your notes will be sent back to the CEO as revision instructions."""


async def ceo_review_node(state: NexusState, config: dict) -> dict:
    if not state.get("worker_results"):
        return {"ceo_verdict": "done", "revision_notes": "No workers ran."}
    try:
        llm = _get_review_llm()
        decision: ReviewDecision = await llm.ainvoke(build_review_prompt(state))
        return {"ceo_verdict": decision.verdict, "revision_notes": decision.notes}
    except Exception as exc:
        logger.warning("review node error, defaulting to approved: %s", exc)
        return {"ceo_verdict": "approved", "revision_notes": ""}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec nexus-ceo pytest tests/graph/test_review_node.py -v
```

Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add app/graph/nodes/review.py tests/graph/test_review_node.py
git commit -m "feat: add CEO review node with Gemini structured ReviewDecision"
```

---

## Task 9: Output Node

**Files:**
- Create: `app/graph/nodes/output.py`

- [ ] **Step 1: Create app/graph/nodes/output.py**

```python
# app/graph/nodes/output.py
"""Output pipeline node — wraps pipeline.process() and extracts artifacts."""
import logging
import re

from app.graph.state import WorkerState
from app.graph import broadcast
from app.output import pipeline

logger = logging.getLogger(__name__)

_ARTIFACT_RE = re.compile(r'\[ARTIFACT:\s*([^|]+)\s*\|\s*([^\]]+)\]')
_DONE_RE = re.compile(r'\[DONE:\s*([^\]]{1,120})\]')


def _extract_artifacts(text: str) -> dict:
    return {
        m.group(1).strip(): m.group(2).strip()
        for m in _ARTIFACT_RE.finditer(text)
    }


def _extract_summary(text: str) -> str:
    m = _DONE_RE.search(text)
    if m:
        return m.group(1).strip()
    return text.strip()[:120]


async def output_node(state: WorkerState, config: dict) -> dict:
    thread_id = config.get("configurable", {}).get("thread_id", "")

    async def send(data: dict) -> None:
        await broadcast.send(thread_id, data)

    result = state.get("result", "")
    agent_id = state["agent_id"]

    try:
        await pipeline.process(result, agent_id, send)
    except Exception as exc:
        logger.warning("output pipeline error for %s: %s", agent_id, exc)

    return {
        "new_artifacts": _extract_artifacts(result),
        "result": result,
    }
```

- [ ] **Step 2: Verify import**

```bash
docker exec nexus-ceo python -c "from app.graph.nodes.output import output_node; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/graph/nodes/output.py
git commit -m "feat: add output pipeline graph node with artifact extraction"
```

---

## Task 10: Worker Skill Meta-Tools

**Files:**
- Create: `app/graph/workers/tools/core.py`

- [ ] **Step 1: Create app/graph/workers/tools/core.py**

```python
# app/graph/workers/tools/core.py
"""Dynamic skill meta-tools compiled into every worker subgraph."""
import logging
from langchain_core.tools import tool

from app.skills import skill_loader

logger = logging.getLogger(__name__)


@tool
def list_available_skills() -> list[str]:
    """List all dynamically loaded skill tools available to this worker."""
    return skill_loader.list_tools()


@tool
async def call_skill(skill_name: str, args: dict) -> str:
    """Call a dynamically loaded skill by name with the given arguments."""
    handler = skill_loader.get_tool(skill_name)
    if not handler:
        available = list_available_skills()
        return f"Skill '{skill_name}' not found. Available: {available}"
    try:
        result = await handler(args)
        return str(result)
    except Exception as exc:
        logger.warning("skill %s error: %s", skill_name, exc)
        return f"Skill error: {exc}"


WORKER_META_TOOLS = [list_available_skills, call_skill]
```

- [ ] **Step 2: Verify import**

```bash
docker exec nexus-ceo python -c "from app.graph.workers.tools.core import WORKER_META_TOOLS; print(len(WORKER_META_TOOLS), 'tools OK')"
```

Expected: `2 tools OK`

- [ ] **Step 3: Commit**

```bash
git add app/graph/workers/tools/core.py
git commit -m "feat: add list_available_skills + call_skill meta-tools for worker subgraphs"
```

---

## Task 11: Worker Subgraph Factory

**Files:**
- Create: `app/graph/workers/base.py`
- Create: `tests/graph/test_worker_subgraph.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/graph/test_worker_subgraph.py
import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from langgraph.checkpoint.memory import MemorySaver
from app.graph.workers.base import make_worker_graph, _extract_artifacts


def test_extract_artifacts_single():
    text = "Done! [ARTIFACT: api_base | http://localhost:8090]"
    result = _extract_artifacts(text)
    assert result == {"api_base": "http://localhost:8090"}


def test_extract_artifacts_multiple():
    text = "[ARTIFACT: port | 8090] and [ARTIFACT: db_url | sqlite:///app.db]"
    result = _extract_artifacts(text)
    assert result["port"] == "8090"
    assert result["db_url"] == "sqlite:///app.db"


def test_extract_artifacts_empty():
    text = "Task complete. No artifacts."
    result = _extract_artifacts(text)
    assert result == {}


@pytest.mark.asyncio
async def test_worker_graph_runs_successfully():
    with patch("app.graph.workers.base.run_agent", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "API built. [ARTIFACT: api_base | http://localhost:8090]"
        with patch("app.graph.nodes.output.pipeline.process", new_callable=AsyncMock):
            graph = make_worker_graph("backend")
            saver = MemorySaver()
            compiled = graph  # already compiled in factory
            config = {"configurable": {"thread_id": "test-001", "model": "claude"}}
            state = {
                "task": "build the API",
                "agent_id": "backend",
                "model": "claude",
                "artifacts": {},
                "messages": [],
                "result": "",
                "new_artifacts": {},
            }
            result = await compiled.ainvoke(state, config)
            assert mock_run.called
            assert result["new_artifacts"].get("api_base") == "http://localhost:8090"
```

- [ ] **Step 2: Run to verify it fails**

```bash
docker exec nexus-ceo pytest tests/graph/test_worker_subgraph.py::test_extract_artifacts_single tests/graph/test_worker_subgraph.py::test_extract_artifacts_multiple tests/graph/test_worker_subgraph.py::test_extract_artifacts_empty -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create app/graph/workers/base.py**

```python
# app/graph/workers/base.py
"""Worker subgraph factory — one compiled subgraph per agent."""
import logging
import re

from langgraph.graph import StateGraph, START, END

from app.graph.state import WorkerState
from app.graph.nodes.output import output_node
from app.graph import broadcast
from app.agents.runner import run_agent

logger = logging.getLogger(__name__)

_ARTIFACT_RE = re.compile(r'\[ARTIFACT:\s*([^|]+)\s*\|\s*([^\]]+)\]')


def _extract_artifacts(text: str) -> dict:
    return {
        m.group(1).strip(): m.group(2).strip()
        for m in _ARTIFACT_RE.finditer(text)
    }


def _make_worker_node(agent_id: str):
    async def worker_node(state: WorkerState, config: dict) -> dict:
        thread_id = config.get("configurable", {}).get("thread_id", "")
        model = config.get("configurable", {}).get("model", "claude")

        async def send(data: dict) -> None:
            await broadcast.send(thread_id, data)

        result = await run_agent(agent_id, state["task"], send, model)
        return {
            "result": result,
            "new_artifacts": _extract_artifacts(result),
        }

    worker_node.__name__ = f"worker_node_{agent_id}"
    return worker_node


def make_worker_graph(agent_id: str):
    """Build and compile a worker subgraph for the given agent."""
    graph = StateGraph(WorkerState)
    graph.add_node("worker_node", _make_worker_node(agent_id))
    graph.add_node("output_node", output_node)
    graph.add_edge(START, "worker_node")
    graph.add_edge("worker_node", "output_node")
    graph.add_edge("output_node", END)
    return graph.compile()
```

- [ ] **Step 4: Run the unit tests (not the async integration test yet)**

```bash
docker exec nexus-ceo pytest tests/graph/test_worker_subgraph.py::test_extract_artifacts_single tests/graph/test_worker_subgraph.py::test_extract_artifacts_multiple tests/graph/test_worker_subgraph.py::test_extract_artifacts_empty -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add app/graph/workers/base.py tests/graph/test_worker_subgraph.py
git commit -m "feat: add make_worker_graph() worker subgraph factory"
```

---

## Task 12: Compile nexus_graph

**Files:**
- Create: `app/graph/nexus_graph.py`

- [ ] **Step 1: Create app/graph/nexus_graph.py**

```python
# app/graph/nexus_graph.py
"""Compiled nexus_graph — WebSocket-driven real-time orchestration graph."""
import logging
from typing import Literal

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

from app.graph.state import NexusState
from app.graph.nodes.ceo import ceo_node
from app.graph.nodes.review import ceo_review_node
from app.graph.workers.base import make_worker_graph

logger = logging.getLogger(__name__)

_KNOWN_AGENTS = ["backend", "frontend", "qa", "devops", "browser"]
_worker_subgraphs: dict = {}


def _get_worker_subgraph(agent_id: str):
    if agent_id not in _worker_subgraphs:
        _worker_subgraphs[agent_id] = make_worker_graph(agent_id)
    return _worker_subgraphs[agent_id]


def route_after_ceo(state: NexusState):
    """Fan out to worker subgraphs or end if CEO handled directly."""
    delegations = state.get("delegations", [])
    if not delegations:
        return END
    return [
        Send(
            d["agent"],
            {
                "task": d["task"],
                "agent_id": d["agent"],
                "model": state["model"],
                "artifacts": state.get("artifacts", {}),
                "messages": [],
                "result": "",
                "new_artifacts": {},
            },
        )
        for d in delegations
        if d["agent"] in _KNOWN_AGENTS
    ]


def route_after_review(state: NexusState) -> str:
    verdict = state.get("ceo_verdict", "done")
    if verdict in ("revise", "delegate_more"):
        return "ceo_node"
    return "__end__"


def build_nexus_graph(checkpointer):
    graph = StateGraph(NexusState)

    graph.add_node("ceo_node", ceo_node)
    graph.add_node("ceo_review_node", ceo_review_node)

    for agent_id in _KNOWN_AGENTS:
        graph.add_node(agent_id, _get_worker_subgraph(agent_id))

    graph.add_edge(START, "ceo_node")
    graph.add_conditional_edges("ceo_node", route_after_ceo, [END] + _KNOWN_AGENTS)

    for agent_id in _KNOWN_AGENTS:
        graph.add_edge(agent_id, "ceo_review_node")

    graph.add_conditional_edges(
        "ceo_review_node",
        route_after_review,
        {"ceo_node": "ceo_node", "__end__": END},
    )

    return graph.compile(checkpointer=checkpointer)
```

- [ ] **Step 2: Verify the graph compiles**

```bash
docker exec nexus-ceo python -c "
from langgraph.checkpoint.memory import MemorySaver
from app.graph.nexus_graph import build_nexus_graph
g = build_nexus_graph(MemorySaver())
print('nexus_graph compiled OK, nodes:', list(g.nodes))
"
```

Expected: prints graph nodes including `ceo_node`, `backend`, `frontend`, etc.

- [ ] **Step 3: Commit**

```bash
git add app/graph/nexus_graph.py
git commit -m "feat: compile nexus_graph with CEO→workers→review topology"
```

---

## Task 13: Event Translation + Rewrite websocket.py

**Files:**
- Create: `tests/graph/test_event_translation.py`
- Rewrite: `app/api/websocket.py`

- [ ] **Step 1: Write the event translation tests**

```python
# tests/graph/test_event_translation.py
import pytest
from app.api.websocket import _translate_event, _step_counters, _checkpoint_counters


def _evt(kind, name, metadata=None, data=None):
    return {
        "event": kind,
        "name": name,
        "metadata": metadata or {},
        "data": data or {},
        "tags": [],
        "run_id": "run-001",
    }


def test_ceo_chain_start_emits_thinking():
    event = _evt("on_chain_start", "ceo_node",
                 metadata={"langgraph_checkpoint_ns": "ceo_node"})
    msg = _translate_event(event, "ws_abc")
    assert msg is not None
    assert msg["type"] == "thinking"
    assert msg["agent"] == "ceo"


def test_tool_start_emits_worker_step():
    _step_counters.clear()
    event = _evt(
        "on_tool_start", "bash",
        metadata={"langgraph_checkpoint_ns": "backend:subgraph123"},
        data={"input": {"command": "pytest tests/"}, "name": "bash"},
    )
    msg = _translate_event(event, "ws_abc")
    assert msg is not None
    assert msg["type"] == "worker_step"
    assert msg["agent"] == "backend"
    assert msg["step"] == 1
    assert msg["tool"] == "bash"
    assert "pytest" in msg["label"]


def test_tool_start_increments_step_per_thread_and_agent():
    _step_counters.clear()
    event = _evt(
        "on_tool_start", "bash",
        metadata={"langgraph_checkpoint_ns": "backend:id"},
        data={"input": {"command": "run"}, "name": "bash"},
    )
    _translate_event(event, "ws_t1")
    _translate_event(event, "ws_t1")
    msg = _translate_event(event, "ws_t1")
    assert msg["step"] == 3


def test_tool_start_separate_agents_have_independent_counters():
    _step_counters.clear()
    ba_event = _evt("on_tool_start", "bash",
                    metadata={"langgraph_checkpoint_ns": "backend:id"},
                    data={"input": {"command": "x"}, "name": "bash"})
    fe_event = _evt("on_tool_start", "bash",
                    metadata={"langgraph_checkpoint_ns": "frontend:id"},
                    data={"input": {"command": "x"}, "name": "bash"})
    _translate_event(ba_event, "ws_t2")
    _translate_event(ba_event, "ws_t2")
    msg = _translate_event(fe_event, "ws_t2")
    assert msg["step"] == 1


def test_worker_node_end_emits_checkpoint():
    _step_counters.clear()
    _checkpoint_counters.clear()
    _step_counters["ws_t3:backend"] = 5
    event = _evt(
        "on_chain_end", "worker_node",
        metadata={"langgraph_checkpoint_ns": "backend:id"},
        data={"output": {"result": "[DONE: Scaffolded API routes]", "new_artifacts": {}}},
    )
    msg = _translate_event(event, "ws_t3")
    assert msg is not None
    assert msg["type"] == "worker_checkpoint"
    assert msg["agent"] == "backend"
    assert msg["index"] == 1
    assert msg["step"] == 5
    assert "Scaffolded API routes" in msg["summary"]


def test_output_node_end_emits_worker_done():
    event = _evt(
        "on_chain_end", "output_node",
        metadata={"langgraph_checkpoint_ns": "backend:id"},
        data={"output": {}},
    )
    msg = _translate_event(event, "ws_t4")
    assert msg is not None
    assert msg["type"] == "worker_done"
    assert msg["agent"] == "backend"


def test_ceo_chain_end_emits_done():
    event = _evt(
        "on_chain_end", "ceo_node",
        metadata={"langgraph_checkpoint_ns": "ceo_node"},
        data={"output": {}},
    )
    msg = _translate_event(event, "ws_t5")
    assert msg is not None
    assert msg["type"] == "done"
    assert msg["agent"] == "ceo"


def test_unknown_event_returns_none():
    event = _evt("on_tool_end", "bash",
                 metadata={"langgraph_checkpoint_ns": "backend:id"})
    msg = _translate_event(event, "ws_t6")
    assert msg is None


def test_step_counters_reset_on_new_ceo_task():
    _step_counters.clear()
    _step_counters["ws_t7:backend"] = 10
    _step_counters["ws_t7:frontend"] = 5
    _step_counters["ws_other:backend"] = 3
    event = _evt("on_chain_start", "ceo_node",
                 metadata={"langgraph_checkpoint_ns": "ceo_node"})
    _translate_event(event, "ws_t7")
    assert "ws_t7:backend" not in _step_counters
    assert "ws_t7:frontend" not in _step_counters
    assert _step_counters.get("ws_other:backend") == 3
```

- [ ] **Step 2: Run to verify they fail**

```bash
docker exec nexus-ceo pytest tests/graph/test_event_translation.py -v 2>&1 | head -15
```

Expected: import errors because the new websocket.py hasn't been written yet.

- [ ] **Step 3: Rewrite app/api/websocket.py**

Read the existing file first:
```bash
wc -l app/api/websocket.py
```

Then replace its entire contents with:

```python
# app/api/websocket.py
"""WebSocket handler — wraps nexus_graph.astream_events() and broadcasts to clients."""
import asyncio
import json
import logging
import re
from uuid import uuid4

from fastapi import WebSocket
from fastapi.websockets import WebSocketDisconnect

from app.agents import definitions as defs
from app.graph import broadcast as bcast

logger = logging.getLogger(__name__)

# ── In-memory step/checkpoint counters (per thread+agent) ──────────────────────

_step_counters: dict[str, int] = {}        # f"{thread_id}:{agent_id}" → count
_checkpoint_counters: dict[str, int] = {}  # f"{thread_id}:{agent_id}" → count

_DONE_RE = re.compile(r'\[DONE:\s*([^\]]{1,120})\]')


def _agent_key(thread_id: str, agent_id: str) -> str:
    return f"{thread_id}:{agent_id}"


def _extract_agent_id(metadata: dict) -> str:
    """Extract agent_id from langgraph_checkpoint_ns like 'backend:abc123'."""
    ns = metadata.get("langgraph_checkpoint_ns", "")
    return ns.split(":")[0] if ":" in ns else ns


def _extract_summary(result: str) -> str:
    m = _DONE_RE.search(result)
    return m.group(1).strip() if m else result.strip()[:120]


def _translate_event(event: dict, thread_id: str) -> dict | None:
    """Map a LangGraph astream_events v2 event to a frontend WS message."""
    kind = event.get("event", "")
    name = event.get("name", "")
    metadata = event.get("metadata", {})
    data = event.get("data", {})
    agent_id = _extract_agent_id(metadata)

    # Reset counters at start of new CEO task
    if kind == "on_chain_start" and name == "ceo_node":
        for k in list(_step_counters):
            if k.startswith(thread_id + ":"):
                del _step_counters[k]
        for k in list(_checkpoint_counters):
            if k.startswith(thread_id + ":"):
                del _checkpoint_counters[k]
        return {"type": "thinking", "agent": "ceo", "thread_id": thread_id}

    if kind == "on_chain_start" and name in defs.all_agents():
        return {"type": "delegation", "agent": name, "thread_id": thread_id}

    if kind == "on_tool_start":
        key = _agent_key(thread_id, agent_id)
        _step_counters[key] = _step_counters.get(key, 0) + 1
        step = _step_counters[key]
        tool_name = data.get("name") or name
        tool_input = data.get("input", {})
        label = (
            tool_input.get("command")
            or tool_input.get("file_path")
            or tool_input.get("query")
            or tool_name
        )
        if isinstance(label, str) and len(label) > 80:
            label = label[:80] + "…"
        return {
            "type": "worker_step",
            "agent": agent_id,
            "step": step,
            "tool": tool_name,
            "label": str(label),
            "thread_id": thread_id,
        }

    if kind == "on_chain_end" and name == "worker_node":
        key = _agent_key(thread_id, agent_id)
        _checkpoint_counters[key] = _checkpoint_counters.get(key, 0) + 1
        step = _step_counters.get(key, 0)
        output = data.get("output", {})
        summary = _extract_summary(output.get("result", ""))
        return {
            "type": "worker_checkpoint",
            "agent": agent_id,
            "index": _checkpoint_counters[key],
            "summary": summary,
            "step": step,
            "thread_id": thread_id,
        }

    if kind == "on_chain_end" and name == "output_node":
        return {"type": "worker_done", "agent": agent_id, "thread_id": thread_id}

    if kind == "on_chain_end" and name == "ceo_node":
        return {"type": "done", "agent": "ceo", "thread_id": thread_id}

    if kind == "on_chain_error":
        err = str(data.get("error", "unknown error"))[:200]
        return {"type": "error", "agent": agent_id or "unknown", "message": err, "thread_id": thread_id}

    if kind == "on_chat_model_stream":
        chunk = data.get("chunk", {})
        content = getattr(chunk, "content", "") if hasattr(chunk, "content") else ""
        if content:
            return {"type": "assistant", "agent": agent_id or "ceo", "message": {"content": content}, "thread_id": thread_id}

    return None


# ── Sessions + active runs ─────────────────────────────────────────────────────

class Session:
    def __init__(self, ws: WebSocket, model: str):
        self.ws = ws
        self.model = model
        self._lock = asyncio.Lock()

    async def send(self, data: dict) -> None:
        async with self._lock:
            try:
                await self.ws.send_json(data)
            except Exception:
                pass


_sessions: set[Session] = set()
_active_runs: dict[str, asyncio.Task] = {}


async def broadcast_event(data: dict) -> None:
    for session in list(_sessions):
        await session.send(data)


def _build_init_payload() -> dict:
    agents = defs.all_agents()
    return {
        "type": "init",
        "agents": [
            {"id": aid, "name": a["name"], "role": a["role"], "status": "idle"}
            for aid, a in agents.items()
        ],
        "work_queue": [],
    }


async def _run_and_stream(task: str, thread_id: str, model: str) -> None:
    from app.graph.nexus_graph import build_nexus_graph
    from app.graph.checkpointer import get_checkpointer

    cp = await get_checkpointer()
    graph = build_nexus_graph(cp)

    async def send_fn(data: dict) -> None:
        await broadcast_event(data)

    bcast.register(thread_id, send_fn)
    try:
        config = {"configurable": {"thread_id": thread_id, "model": model}}
        async for event in graph.astream_events(
            {"task": task, "session_id": thread_id, "model": model,
             "source": "browser", "worker_results": [], "delegations": [],
             "artifacts": {}, "ceo_verdict": "approved", "revision_notes": "",
             "ceo_response": "", "worker_progress": {}},
            config,
            version="v2",
        ):
            msg = _translate_event(event, thread_id)
            if msg:
                await broadcast_event(msg)
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.exception("nexus_graph run error: %s", exc)
        await broadcast_event({"type": "error", "agent": "ceo", "message": str(exc)})
    finally:
        bcast.unregister(thread_id)


async def ws_endpoint(ws: WebSocket, model: str = "claude") -> None:
    session = Session(ws, model)
    thread_id = f"ws_{uuid4().hex}"
    _sessions.add(session)
    await ws.accept()
    await session.send(_build_init_payload())

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type", "")

            if msg_type == "message":
                t = asyncio.create_task(
                    _run_and_stream(msg["text"], thread_id, session.model)
                )
                _active_runs[thread_id] = t

            elif msg_type == "cancel_worker":
                task = _active_runs.pop(thread_id, None)
                if task:
                    task.cancel()

            elif msg_type == "model":
                session.model = msg.get("model", session.model)

            elif msg_type == "clear":
                task = _active_runs.pop(thread_id, None)
                if task:
                    task.cancel()

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("ws_endpoint error")
    finally:
        _sessions.discard(session)
        task = _active_runs.pop(thread_id, None)
        if task:
            task.cancel()


async def handle_browser_result(data: dict, model: str) -> None:
    """Handle browser_result from browser-svc relay."""
    await broadcast_event(data)


async def handle_browser_blocker_resolved(data: dict) -> None:
    """Handle browser_blocker_resolved from browser-svc relay."""
    await broadcast_event(data)
```

- [ ] **Step 4: Run the event translation tests**

```bash
docker exec nexus-ceo pytest tests/graph/test_event_translation.py -v
```

Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
git add app/api/websocket.py tests/graph/test_event_translation.py
git commit -m "feat: rewrite websocket.py with astream_events + _translate_event step/checkpoint counters"
```

---

## Task 14: Email Graph Nodes

**Files:**
- Create: `app/graph/email/nodes.py`
- Create: `tests/graph/test_email_graph.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/graph/test_email_graph.py
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from app.graph.email.nodes import (
    verify_node, route_after_verify,
    _is_trusted,
)
from app.graph.state import EmailState


def _make_email_state(**overrides) -> EmailState:
    base: EmailState = {
        "email": {
            "from_email": "sauravsubaru@gmail.com",
            "subject": "Deploy my site",
            "body": "Please deploy.",
            "message_id": "msg-001",
            "in_reply_to": None,
            "references": [],
        },
        "is_owner": True,
        "verified": False,
        "plan": "",
        "user_reply": "",
        "execution_result": "",
        "port_used": "",
        "subdomain": "",
        "sent_message_ids": [],
    }
    base.update(overrides)
    return base


def test_is_trusted_owner_email():
    import os
    os.environ["USER_EMAIL"] = "sauravsubaru@gmail.com"
    assert _is_trusted("sauravsubaru@gmail.com") is True


def test_is_trusted_unknown_email():
    assert _is_trusted("stranger@example.com") is False


def test_route_after_verify_trusted():
    state = _make_email_state(is_owner=True)
    assert route_after_verify(state) == "plan_node"


def test_route_after_verify_untrusted():
    state = _make_email_state(is_owner=False)
    assert route_after_verify(state) == "send_challenge_node"


@pytest.mark.asyncio
async def test_verify_node_sets_verified_for_owner():
    state = _make_email_state(is_owner=True)
    result = await verify_node(state, {})
    assert result["verified"] is True


@pytest.mark.asyncio
async def test_verify_node_sets_unverified_for_unknown():
    state = _make_email_state(is_owner=False)
    result = await verify_node(state, {})
    assert result["verified"] is False
```

- [ ] **Step 2: Run to verify they fail**

```bash
docker exec nexus-ceo pytest tests/graph/test_email_graph.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create app/graph/email/nodes.py**

```python
# app/graph/email/nodes.py
"""Email graph nodes — 7-node state machine."""
import asyncio
import logging
from typing import Literal

from app import config
from app.graph.state import EmailState
from app.services import email_inbox as inbox

logger = logging.getLogger(__name__)


def _is_trusted(email_addr: str) -> bool:
    trusted = {
        config.USER_EMAIL,
        config.IMAP_USER,
        config.SMTP_USER,
    }
    return email_addr.strip().lower() in {e.lower() for e in trusted if e}


def route_after_verify(state: EmailState) -> Literal["plan_node", "send_challenge_node"]:
    return "plan_node" if state["is_owner"] else "send_challenge_node"


def route_after_execute(state: EmailState) -> Literal["report_node", "ask_subdomain_node"]:
    result = state.get("execution_result", "")
    if "PORT:" in result or state.get("port_used"):
        return "ask_subdomain_node"
    return "report_node"


async def verify_node(state: EmailState, config: dict) -> dict:
    email = state["email"]
    is_owner = _is_trusted(email.get("from_email", ""))
    return {"is_owner": is_owner, "verified": is_owner}


async def send_challenge_node(state: EmailState, config: dict) -> dict:
    email = state["email"]
    try:
        msg_id = await inbox.send_reply(
            original=email,
            body=(
                "I received your message. To verify your identity, "
                "please reply with the word VERIFY."
            ),
            subject=f"Re: {email.get('subject', 'Your request')} [verification]",
        )
        return {"sent_message_ids": state.get("sent_message_ids", []) + [msg_id]}
    except Exception as exc:
        logger.warning("send_challenge error: %s", exc)
        return {}


async def plan_node(state: EmailState, config_: dict) -> dict:
    """Run the CEO headless to create a plan, then email it for approval."""
    from app.services.email_poller import _run_ceo_headless  # existing function
    email = state["email"]
    subject = email.get("subject", "task")
    body = email.get("body", "")
    task_prompt = f"Email task: {subject}\n\nDetails:\n{body}"

    try:
        plan = await _run_ceo_headless(task_prompt, task_id=email.get("message_id", ""))
        msg_id = await inbox.send_reply(
            original=email,
            body=f"Here is my plan:\n\n{plan}\n\nReply APPROVE to proceed or DENY to cancel.",
            subject=f"Re: {subject} [plan approval needed]",
        )
        return {"plan": plan, "sent_message_ids": state.get("sent_message_ids", []) + [msg_id]}
    except Exception as exc:
        logger.warning("plan_node error: %s", exc)
        return {"plan": f"Error creating plan: {exc}"}


async def execute_node(state: EmailState, config_: dict) -> dict:
    """Execute the approved plan using the CEO headless runner."""
    from app.services.email_poller import _run_ceo_headless
    plan = state.get("plan", "")
    email = state["email"]
    try:
        result = await _run_ceo_headless(
            f"Execute this plan:\n{plan}",
            task_id=email.get("message_id", "exec"),
        )
        port_match = None
        import re
        pm = re.search(r'PORT:(\d+)', result)
        if pm:
            port_match = pm.group(1)
        return {"execution_result": result, "port_used": port_match or ""}
    except Exception as exc:
        logger.warning("execute_node error: %s", exc)
        return {"execution_result": f"Error: {exc}"}


async def report_node(state: EmailState, config_: dict) -> dict:
    email = state["email"]
    result = state.get("execution_result", "No result.")
    try:
        msg_id = await inbox.send_reply(
            original=email,
            body=f"Task complete.\n\n{result[:1500]}",
            subject=f"Re: {email.get('subject', 'task')} [done]",
        )
        return {"sent_message_ids": state.get("sent_message_ids", []) + [msg_id]}
    except Exception as exc:
        logger.warning("report_node error: %s", exc)
        return {}


async def ask_subdomain_node(state: EmailState, config_: dict) -> dict:
    email = state["email"]
    port = state.get("port_used", "")
    try:
        msg_id = await inbox.send_reply(
            original=email,
            body=(
                f"Your service is running on port {port}. "
                "Reply with your desired subdomain (e.g. 'myapp') "
                "and I'll wire up a Cloudflare tunnel."
            ),
            subject=f"Re: {email.get('subject', 'task')} [subdomain needed]",
        )
        return {"sent_message_ids": state.get("sent_message_ids", []) + [msg_id]}
    except Exception as exc:
        logger.warning("ask_subdomain_node error: %s", exc)
        return {}


async def wire_cf_node(state: EmailState, config_: dict) -> dict:
    """Wire a Cloudflare tunnel via the operations sidecar API."""
    email = state["email"]
    subdomain = state.get("user_reply", "").strip().split()[0]
    port = state.get("port_used", "")
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "http://127.0.0.1:8899/tunnel",
                json={"subdomain": subdomain, "port": int(port) if port else 0},
            )
        result_text = resp.text
    except Exception as exc:
        logger.warning("wire_cf tunnel API error: %s", exc)
        result_text = f"Tunnel wiring failed: {exc}"
    try:
        msg_id = await inbox.send_reply(
            original=email,
            body=f"Tunnel result:\n{result_text}\n\nSubdomain: {subdomain}.shadowgarden.app → port {port}",
            subject=f"Re: {email.get('subject', 'task')} [done]",
        )
        return {
            "subdomain": subdomain,
            "sent_message_ids": state.get("sent_message_ids", []) + [msg_id],
        }
    except Exception as exc:
        logger.warning("wire_cf_node reply error: %s", exc)
        return {"subdomain": subdomain}
```

- [ ] **Step 4: Run the tests**

```bash
docker exec nexus-ceo pytest tests/graph/test_email_graph.py -v
```

Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add app/graph/email/nodes.py tests/graph/test_email_graph.py
git commit -m "feat: add 7 email graph nodes with verify/plan/execute/report flow"
```

---

## Task 15: Compile email_graph

**Files:**
- Create: `app/graph/email/graph.py`

- [ ] **Step 1: Create app/graph/email/graph.py**

```python
# app/graph/email/graph.py
"""Compiled email_graph — async email-driven state machine with interrupt gates."""
import logging

from langgraph.graph import StateGraph, START, END

from app.graph.state import EmailState
from app.graph.email.nodes import (
    verify_node,
    send_challenge_node,
    plan_node,
    execute_node,
    report_node,
    ask_subdomain_node,
    wire_cf_node,
    route_after_verify,
    route_after_execute,
)

logger = logging.getLogger(__name__)


def build_email_graph(checkpointer):
    graph = StateGraph(EmailState)

    graph.add_node("verify_node", verify_node)
    graph.add_node("send_challenge_node", send_challenge_node)
    graph.add_node("plan_node", plan_node)
    graph.add_node("execute_node", execute_node)
    graph.add_node("report_node", report_node)
    graph.add_node("ask_subdomain_node", ask_subdomain_node)
    graph.add_node("wire_cf_node", wire_cf_node)

    graph.add_edge(START, "verify_node")
    graph.add_conditional_edges(
        "verify_node",
        route_after_verify,
        {"plan_node": "plan_node", "send_challenge_node": "send_challenge_node"},
    )
    # After send_challenge, graph ends — resumes when user replies (interrupt_before verify)
    graph.add_edge("send_challenge_node", END)
    # plan_node → execute_node; interrupt_before=["execute_node"] pauses here for approval
    graph.add_edge("plan_node", "execute_node")
    graph.add_conditional_edges(
        "execute_node",
        route_after_execute,
        {"report_node": "report_node", "ask_subdomain_node": "ask_subdomain_node"},
    )
    graph.add_edge("report_node", END)
    # ask_subdomain_node → wire_cf_node; interrupt_before=["wire_cf_node"] pauses for subdomain
    graph.add_edge("ask_subdomain_node", "wire_cf_node")
    graph.add_edge("wire_cf_node", END)

    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["execute_node", "wire_cf_node"],
    )


def resolve_thread_id(email: dict, checkpointer) -> str:
    """Return the thread_id for an email — new if first contact, existing if reply."""
    in_reply_to = email.get("in_reply_to", "")
    refs = email.get("references", [])
    if isinstance(refs, str):
        import re
        refs = re.findall(r'<[^>]+>', refs)
    return f"email_{email['message_id']}"
```

- [ ] **Step 2: Verify the graph compiles**

```bash
docker exec nexus-ceo python -c "
from langgraph.checkpoint.memory import MemorySaver
from app.graph.email.graph import build_email_graph
g = build_email_graph(MemorySaver())
print('email_graph compiled OK')
"
```

Expected: `email_graph compiled OK`

- [ ] **Step 3: Commit**

```bash
git add app/graph/email/graph.py
git commit -m "feat: compile email_graph with 7 nodes and interrupt_before gates"
```

---

## Task 16: Rewrite email_poller.py

**Files:**
- Rewrite: `app/services/email_poller.py`

Read the file first (`wc -l app/services/email_poller.py` → 773 LOC), then replace with the slim version below. The functions `_run_ceo_headless`, `_is_trusted`, `_is_automated_email`, `_extract_reply_body` are still needed — keep them. The 7-state machine is replaced by graph dispatch.

- [ ] **Step 1: Rewrite app/services/email_poller.py**

```python
# app/services/email_poller.py
"""
Email poller — thin IMAP poll loop dispatching emails to email_graph.
~100 LOC replacing the 773-LOC 7-state machine.
"""
import asyncio
import logging
import re
from typing import Optional

from app import config
from app.services import email_inbox as inbox

logger = logging.getLogger(__name__)

_AUTOMATED_SENDERS = frozenset(["noreply", "no-reply", "mailer-daemon", "postmaster"])
_AUTOMATED_SUBJECTS = re.compile(
    r'(out of office|automatic reply|auto-reply|delivery status|undelivered mail)',
    re.IGNORECASE,
)


def _is_trusted(email_addr: str) -> bool:
    trusted = {config.USER_EMAIL, config.IMAP_USER, config.SMTP_USER}
    return email_addr.strip().lower() in {e.lower() for e in trusted if e}


def _is_automated_email(email: dict) -> bool:
    sender = email.get("from_email", "").lower()
    subject = email.get("subject", "").lower()
    if any(s in sender for s in _AUTOMATED_SENDERS):
        return True
    if _AUTOMATED_SUBJECTS.search(subject):
        return True
    return False


def _extract_reply_body(body: str) -> str:
    lines = body.splitlines()
    reply_lines = []
    for line in lines:
        if line.startswith(">") or line.startswith("On ") and "wrote:" in line:
            break
        reply_lines.append(line)
    return "\n".join(reply_lines).strip()


async def _run_ceo_headless(prompt: str, task_id: str = "") -> str:
    """Run CEO agent without WebSocket, return full text response."""
    from app.agents.runner import run_claude_agent

    accumulated = []

    async def collect(data: dict) -> None:
        if data.get("type") == "assistant":
            content = data.get("message", {}).get("content", "")
            if content:
                accumulated.append(content)

    try:
        result = await run_claude_agent("ceo", prompt, collect, "claude")
        return result or "".join(accumulated)
    except Exception as exc:
        logger.warning("_run_ceo_headless error: %s", exc)
        return f"Error: {exc}"


async def poll_once(email_graph) -> None:
    """Fetch new emails and dispatch each to email_graph."""
    try:
        emails = await inbox.fetch_new_emails(max_emails=10)
    except Exception as exc:
        logger.warning("inbox fetch error: %s", exc)
        return

    for email in emails:
        if _is_automated_email(email):
            continue
        thread_id = f"email_{email['message_id']}"
        try:
            cfg = {"configurable": {"thread_id": thread_id}}
            graph_state = await email_graph.aget_state(cfg)
            if graph_state.next:
                reply_body = _extract_reply_body(email.get("body", ""))
                await email_graph.ainvoke({"user_reply": reply_body}, cfg)
            else:
                await email_graph.ainvoke(
                    {
                        "email": email,
                        "is_owner": _is_trusted(email.get("from_email", "")),
                        "sent_message_ids": [],
                    },
                    cfg,
                )
        except Exception as exc:
            logger.warning("email dispatch error for %s: %s", thread_id, exc)


async def start(email_graph) -> None:
    """Polling loop — runs indefinitely."""
    logger.info("email poller started")
    while True:
        await poll_once(email_graph)
        await asyncio.sleep(30)
```

- [ ] **Step 2: Verify import**

```bash
docker exec nexus-ceo python -c "from app.services.email_poller import start, poll_once; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/services/email_poller.py
git commit -m "feat: rewrite email_poller to ~100 LOC graph dispatch loop"
```

---

## Task 17: Gut state/manager.py

**Files:**
- Modify: `app/state/manager.py`

Remove `work_queue`, `active_agent_tasks`, `save_state()`, `load_state()`. Keep: `record()`, `get_history()`, `conversation_histories`, `load_changelog()`, `log_feature()`, `load_projects()`, `save_project()`.

- [ ] **Step 1: Read the current file to understand what to remove**

```bash
grep -n "work_queue\|active_agent_tasks\|save_state\|load_state\|STATE_FILE" app/state/manager.py
```

- [ ] **Step 2: Rewrite app/state/manager.py**

```python
# app/state/manager.py
"""
State helpers — conversation history (runtime cache), changelog, projects.
Work queue and save_state/load_state removed: LangGraph checkpointer owns persistence.
"""
import json
import logging
from datetime import datetime
from typing import List, Optional

from app import config

logger = logging.getLogger(__name__)

conversation_histories: dict[str, list[dict]] = {}


def record(agent_id: str, role: str, content: str) -> None:
    if agent_id not in conversation_histories:
        conversation_histories[agent_id] = []
    conversation_histories[agent_id].append({"role": role, "content": content})
    cap = config.MAX_HISTORY
    if len(conversation_histories[agent_id]) > cap:
        conversation_histories[agent_id] = conversation_histories[agent_id][-cap:]


def get_history(agent_id: str) -> List[dict]:
    return conversation_histories.get(agent_id, [])


def load_changelog() -> list:
    try:
        if config.CHANGELOG_FILE.exists():
            return json.loads(config.CHANGELOG_FILE.read_text())
    except Exception as exc:
        logger.warning("load_changelog error: %s", exc)
    return []


def log_feature(feature: str, files: list, agent: str = "worker") -> dict:
    changelog = load_changelog()
    entry = {
        "timestamp": datetime.now().isoformat(),
        "feature": feature,
        "files": files,
        "agent": agent,
    }
    changelog.append(entry)
    try:
        config.CHANGELOG_FILE.write_text(json.dumps(changelog, indent=2))
    except Exception as exc:
        logger.warning("log_feature write error: %s", exc)
    return entry


def load_projects() -> list:
    try:
        if config.PROJECTS_FILE.exists():
            return json.loads(config.PROJECTS_FILE.read_text())
    except Exception as exc:
        logger.warning("load_projects error: %s", exc)
    return []


def save_project(project: dict) -> dict:
    projects = load_projects()
    existing = next((p for p in projects if p.get("id") == project.get("id")), None)
    if existing:
        existing.update(project)
    else:
        project.setdefault("id", len(projects) + 1)
        projects.append(project)
    try:
        config.PROJECTS_FILE.write_text(json.dumps(projects, indent=2))
    except Exception as exc:
        logger.warning("save_project write error: %s", exc)
    return project


def load_state() -> None:
    """No-op — LangGraph checkpointer owns persistence. Kept for import compat."""
    pass
```

- [ ] **Step 3: Run existing tests to catch regressions**

```bash
docker exec nexus-ceo pytest tests/ --ignore=tests/graph -x -q 2>&1 | tail -15
```

Fix any test that imports removed functions (`save_state`, `work_queue`, etc.).

- [ ] **Step 4: Commit**

```bash
git add app/state/manager.py
git commit -m "refactor: gut state/manager.py — remove work_queue/save_state, keep history+changelog"
```

---

## Task 18: Update main.py

**Files:**
- Modify: `app/main.py`

Switch from `@app.on_event("startup")` (deprecated) to `@asynccontextmanager lifespan`. Wire graphs and pass `email_graph` to `email_poller.start()`.

- [ ] **Step 1: Rewrite app/main.py**

```python
# app/main.py
"""Shadow Garden — FastAPI application factory with LangGraph lifespan."""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.websockets import WebSocketDisconnect

from app.api import router as api_router_module
from app.api import websocket as ws_module
from app.api.websocket import broadcast_event

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # DB + memory
    from app.services import memory as mem_svc
    mem_svc.init_db()

    # Skills
    from app.skills import skill_loader
    skill_loader.load_all()

    # LangGraph checkpointer + graphs
    from app.graph.checkpointer import get_checkpointer
    from app.graph.nexus_graph import build_nexus_graph
    from app.graph.email.graph import build_email_graph

    cp = await get_checkpointer()
    app.state.nexus_graph = build_nexus_graph(cp)
    app.state.email_graph = build_email_graph(cp)

    # Background services
    from app.services import email_poller, scheduler
    asyncio.create_task(email_poller.start(app.state.email_graph))
    asyncio.create_task(scheduler.start_scheduler_loop())

    yield


app = FastAPI(title="Shadow Garden Command Center", lifespan=lifespan)

app.include_router(api_router_module.router)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, model: str = Query(default="claude")):
    await ws_module.ws_endpoint(ws, model)


@app.websocket("/ws/browser-relay")
async def browser_relay_endpoint(ws: WebSocket):
    """Receives browser_frame events from browser-svc."""
    secret = os.environ.get("BROWSER_RELAY_SECRET", "")
    if secret:
        auth = ws.headers.get("authorization", "")
        if auth != f"Bearer {secret}":
            await ws.close(code=4401)
            return
    await ws.accept()
    try:
        while True:
            try:
                data = await ws.receive_json()
            except WebSocketDisconnect:
                break
            except Exception:
                break
            if data.get("type") == "browser_result":
                active_model = next((s.model for s in ws_module._sessions), "claude")
                asyncio.create_task(ws_module.handle_browser_result(data, active_model))
            elif data.get("type") == "browser_blocker_resolved":
                asyncio.create_task(ws_module.handle_browser_blocker_resolved(data))
            else:
                await broadcast_event(data)
    except Exception:
        logging.getLogger(__name__).exception("browser_relay_endpoint error")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root():
    return FileResponse(str(STATIC_DIR / "index.html"))
```

- [ ] **Step 2: Verify FastAPI starts**

```bash
docker exec nexus-ceo python -c "
import asyncio
from app.main import app
print('app created:', app.title)
"
```

Expected: `app created: Shadow Garden Command Center`

- [ ] **Step 3: Commit**

```bash
git add app/main.py
git commit -m "feat: migrate app/main.py to lifespan context manager, wire LangGraph graphs"
```

---

## Task 19: Remove Obsolete Files + Full Integration Smoke Test

**Files:**
- Delete: `app/services/delegation.py` (logic inlined into ceo.py)
- Verify: full graph run via WebSocket

- [ ] **Step 1: Check nothing imports delegation.py anymore**

```bash
grep -r "from app.services.delegation\|services\.delegation" /home/subaru/projects/virtual-company --include="*.py"
```

Expected: only `tests/test_delegation.py`. Update that test to import from `app.graph.nodes.ceo` instead:

```python
# tests/test_delegation.py — update imports at top of file
from app.graph.nodes.ceo import parse_delegations_from_response

# Replace existing tests to call parse_delegations_from_response(text) which returns list[dict]
# instead of list[tuple]. Update assertions accordingly.
```

- [ ] **Step 2: Delete delegation.py**

```bash
git rm app/services/delegation.py
```

- [ ] **Step 3: Run the full test suite**

```bash
docker exec nexus-ceo pytest tests/ -v -q 2>&1 | tail -30
```

Fix any failures. Common issues:
- Tests importing from `delegation.py` → update to import from `app.graph.nodes.ceo`
- Tests importing `from app.state.manager import work_queue` → remove
- Tests importing `from app.api.websocket import _run_worker_bg` → remove

- [ ] **Step 4: Smoke test the WebSocket graph via HTTP**

```bash
curl -s 127.0.0.1:3030/
```

Expected: HTML response (not 500). If the container needs restart:
```bash
docker restart nexus-ceo && sleep 5 && curl -s 127.0.0.1:3030/ | head -5
```

- [ ] **Step 5: Final commit**

```bash
git add -u
git commit -m "feat: complete LangGraph migration — delete delegation.py, fix remaining imports"
```

---

## Post-Migration Checklist

- [ ] Container starts cleanly: `docker logs nexus-ceo --tail 20`
- [ ] WebSocket connects and receives `init` payload
- [ ] Send a simple task via the UI, verify it runs through CEO → worker → done
- [ ] Email poller starts without error: `docker logs nexus-ceo 2>&1 | grep "email poller"`
- [ ] `nexus.db` exists and has checkpointer tables: `docker exec nexus-ceo sqlite3 nexus.db ".tables"`
