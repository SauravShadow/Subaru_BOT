# NEXUS Orchestration Stability Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make multi-agent task runs stable — one voice at a time (CEO-only), no overlapping/duplicate speech, no overlapping runs (FIFO queue), and immediate CEO feedback.

**Architecture:** Workers keep running in parallel but report silently; a server-side + client-side gate ensures only the CEO produces audio. All runs (user + scheduled routines) flow through a single global FIFO queue that emits a "queued" notice when busy. The CEO turn streams text and ends with a spoken wrap-up that summarizes the (now correctly plumbed) worker results.

**Tech Stack:** Python 3 / FastAPI / LangGraph (backend, `app/`), pytest (`tests/`), React + Zustand + TypeScript (frontend, `nexus-ui/`).

**Working directory for all backend commands:** `/mnt/HC_Volume_105874680/virtual-company`
**Test runner:** `python -m pytest` (tests live in `tests/`). Run inside the container per project convention if host lacks deps: `docker exec <nexus-container> python -m pytest ...`. The plan shows host commands; prefix with `docker exec` if needed.

---

## File Structure

**Create:**
- `app/api/run_queue.py` — global FIFO serial run executor (enqueue, worker loop, queued-notice, cancel/clear).
- `app/graph/nodes/wrapup.py` — CEO spoken wrap-up node (replaces the dead review node).
- `tests/test_run_queue.py` — queue ordering / queued-notice / cancel tests.
- `tests/test_audio_gate.py` — CEO-only voice gate tests.
- `tests/test_wrapup.py` — wrap-up node tests.

**Modify:**
- `app/output/handlers/speak.py` / `sing.py` — gate audio to CEO.
- `app/agents/runner.py` — CEO-only `[SPEAK:]` prompt instruction; stream CEO assistant text.
- `app/graph/state.py` — add `worker_results` reducer to `WorkerState`.
- `app/graph/nodes/output.py` — emit `worker_results`.
- `app/graph/nexus_graph.py` — wire wrap-up node, make terminal.
- `app/api/websocket.py` — remove duplicate emit branch; route messages through run_queue; immediate ack; cancel/clear → queue.
- `app/services/scheduler.py` — enqueue routines via run_queue.
- `app/main.py` — start run_queue in lifespan.
- `nexus-ui/src/store.ts` — gate speech fallback to CEO; handle `queued` + `ceo_stream`.
- `nexus-ui/src/types.ts` — add new event fields if typed.

---

## Task 1: Server-side audio gate — CEO-only voice

**Files:**
- Modify: `app/output/handlers/speak.py`
- Modify: `app/output/handlers/sing.py`
- Test: `tests/test_audio_gate.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_audio_gate.py`:

```python
"""CEO-only voice gate — workers must never emit audio."""
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_worker_speak_emits_no_audio():
    from app.output.handlers import speak
    send = AsyncMock()
    with patch("app.services.bark_client.speak", new_callable=AsyncMock) as bark:
        bark.return_value = "BASE64AUDIO"
        text, audio_sent = await speak.handle("Hello | emotion: calm", "backend", send)
    assert audio_sent is False
    assert text == "Hello"
    bark.assert_not_called()
    audio_calls = [c for c in send.call_args_list if c[0][0].get("type") == "audio"]
    assert audio_calls == []


@pytest.mark.asyncio
async def test_ceo_speak_emits_audio():
    from app.output.handlers import speak
    send = AsyncMock()
    with patch("app.services.bark_client.speak", new_callable=AsyncMock) as bark:
        bark.return_value = "BASE64AUDIO"
        text, audio_sent = await speak.handle("Hello | emotion: calm", "ceo", send)
    assert audio_sent is True
    assert text == "Hello"
    audio_calls = [c for c in send.call_args_list if c[0][0].get("type") == "audio"]
    assert len(audio_calls) == 1


@pytest.mark.asyncio
async def test_worker_sing_emits_no_audio():
    from app.output.handlers import sing
    send = AsyncMock()
    with patch("app.services.bark_client.sing", new_callable=AsyncMock) as bark:
        bark.return_value = "BASE64AUDIO"
        lyrics, audio_sent = await sing.handle("la la | style: pop", "frontend", send)
    assert audio_sent is False
    bark.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_audio_gate.py -v`
Expected: FAIL (workers currently emit audio).

- [ ] **Step 3: Add the gate to `speak.py`**

In `app/output/handlers/speak.py`, replace the body of `handle` with a CEO check at the top:

```python
async def handle(args: str, agent_id: str, send: Sender) -> tuple[str, bool]:
    text, emotion = _parse_args(args)
    if agent_id != "ceo":
        # CEO-only voice: workers report in text, never speak.
        return text, False
    audio = await bark_client.speak(text, emotion)
    if audio:
        await send({"type": "audio", "mode": "speak", "data": audio})
        return text, True
    return text, False
```

- [ ] **Step 4: Add the gate to `sing.py`**

In `app/output/handlers/sing.py`, add the CEO check at the top of `handle`:

```python
async def handle(args: str, agent_id: str, send: Sender) -> tuple[str, bool]:
    lyrics, style = _parse_sing_args(args)
    if agent_id != "ceo":
        return lyrics, False
    audio = await bark_client.sing(lyrics, style)
    if audio:
        await send({"type": "audio", "mode": "sing", "data": audio})
        return "", True
    return lyrics, False
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_audio_gate.py tests/test_pipeline.py -v`
Expected: PASS (audio-gate tests pass; existing pipeline tests still pass — they use `agent_id="ceo"`).

- [ ] **Step 6: Commit**

```bash
git add app/output/handlers/speak.py app/output/handlers/sing.py tests/test_audio_gate.py
git commit -m "feat: gate SPEAK/SING audio to CEO only (CEO-only voice)"
```

---

## Task 2: Frontend voice gate — speech-synthesis fallback CEO-only

**Files:**
- Modify: `nexus-ui/src/store.ts:339`

The browser speech-synthesis fallback fires for *any* assistant message with `bark_ok === false`. After Task 1, worker messages have `bark_ok === false`, so the browser would still speak them → overlapping voices. Gate it to the CEO.

- [ ] **Step 1: Edit the fallback guard**

In `nexus-ui/src/store.ts`, change the condition at line 339 from:

```ts
      if (data.type === 'assistant' && data.bark_ok === false) {
```

to:

```ts
      if (data.type === 'assistant' && data.bark_ok === false && data.agent === 'ceo') {
```

- [ ] **Step 2: Build to verify it compiles**

Run: `cd nexus-ui && npm run build`
Expected: build succeeds (output copied to `app/static` per existing build setup; verify no TS errors).

- [ ] **Step 3: Commit**

```bash
git add nexus-ui/src/store.ts nexus-ui/dist app/static 2>/dev/null; git add -A nexus-ui app/static
git commit -m "fix(ui): only run browser speech fallback for CEO (CEO-only voice)"
```

> Note: include whichever build-output dir the project tracks (`app/static` is the served bundle per `app/main.py`). If the build writes elsewhere, stage that path instead.

---

## Task 3: Worker prompt — mandatory [SPEAK:] for CEO only

**Files:**
- Modify: `app/agents/runner.py` (`_build_gemini_prompt`, ~line 484-499)
- Test: `tests/test_executor_gemini.py` (extend) or `tests/test_audio_gate.py`

The Gemini prompt currently appends a "MANDATORY — you MUST use [SPEAK:] in EVERY response" block for all agents. Make that block CEO-only; workers get a text-reporting instruction instead.

- [ ] **Step 1: Write failing test**

Add to `tests/test_audio_gate.py`:

```python
def test_gemini_prompt_speak_mandate_is_ceo_only():
    from app.agents.runner import _build_gemini_prompt
    ceo_prompt = _build_gemini_prompt("ceo", "hi")
    worker_prompt = _build_gemini_prompt("backend", "hi")
    assert "[SPEAK:" in ceo_prompt
    assert "MANDATORY" in ceo_prompt
    # Workers must NOT be told to speak
    assert "[SPEAK:" not in worker_prompt
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_audio_gate.py::test_gemini_prompt_speak_mandate_is_ceo_only -v`
Expected: FAIL (`[SPEAK:` currently present for all agents).

- [ ] **Step 3: Make the SPEAK block conditional**

In `app/agents/runner.py`, inside `_build_gemini_prompt`, wrap the `MANDATORY ... [SPEAK:]` portion of the returned f-string so it is included only when `agent_id == "ceo"`. Build it as a variable before the `return`:

```python
    if agent_id == "ceo":
        voice_block = (
            "MANDATORY — you MUST use these tags in EVERY response:\n"
            "  [SPEAK: your full reply | emotion: calm|excited|sad|whisper|energetic]  — REQUIRED for ALL responses\n"
            "    Match emotion to context. Example: [SPEAK: That's done! | emotion: excited]\n"
            "    If asked to sing: [SING: full lyrics | style: genre]\n"
        )
    else:
        voice_block = (
            "REPORTING: Respond in plain text only. Do NOT use [SPEAK:] or [SING:] — "
            "only the CEO speaks aloud. State your results and any [ARTIFACT:...]/[DONE:...] tags as text.\n"
        )
```

Then replace the inline `MANDATORY ... [SPEAK:] ... [SING:] ...` lines in the `return (...)` with `f"{voice_block}"`, keeping the OPTIONAL `[GENERATE_IMAGE]` / `[EMAIL_USER]` lines unchanged.

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_audio_gate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/agents/runner.py tests/test_audio_gate.py
git commit -m "feat: mandate [SPEAK:] for CEO only; workers report in text"
```

---

## Task 4: Plumb worker_results up to NexusState

**Files:**
- Modify: `app/graph/state.py` (`WorkerState`)
- Modify: `app/graph/nodes/output.py` (`output_node`)
- Test: `tests/test_delegation.py` (extend) or new assertion

`NexusState.worker_results` is `Annotated[list[dict], operator.add]` but nothing writes it. Add a matching reducer key to `WorkerState` and have `output_node` emit one entry.

- [ ] **Step 1: Write failing test**

Add to `tests/test_pipeline.py` (it already imports `output_node`):

```python
@pytest.mark.asyncio
async def test_output_node_emits_worker_results():
    from app.graph.nodes.output import output_node
    from langchain_core.runnables import RunnableConfig

    state = {"result": "[DONE: built the API]", "agent_id": "backend"}
    config = RunnableConfig(configurable={"thread_id": "test-wr"})

    with patch("app.graph.nodes.output.pipeline.process", new_callable=AsyncMock), \
         patch("app.graph.broadcast.send", new_callable=AsyncMock):
        out = await output_node(state, config)

    assert out["worker_results"] == [{"agent": "backend", "result": "[DONE: built the API]"}]
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_pipeline.py::test_output_node_emits_worker_results -v`
Expected: FAIL (`worker_results` not in output).

- [ ] **Step 3: Add reducer key to `WorkerState`**

In `app/graph/state.py`, add to `WorkerState` (after `new_artifacts`):

```python
    worker_results: Annotated[list[dict], operator.add]
```

(`operator` and `Annotated` are already imported at the top of the file.)

- [ ] **Step 4: Emit it from `output_node`**

In `app/graph/nodes/output.py`, change the return of `output_node` to include `worker_results`:

```python
    return {
        "new_artifacts": _extract_artifacts(result),
        "result": result,
        "worker_results": [{"agent": agent_id, "result": result}],
    }
```

- [ ] **Step 5: Run to verify pass**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/graph/state.py app/graph/nodes/output.py tests/test_pipeline.py
git commit -m "fix: plumb worker_results up to NexusState via reducer key"
```

---

## Task 5: CEO spoken wrap-up node (replace review node)

**Files:**
- Create: `app/graph/nodes/wrapup.py`
- Modify: `app/graph/nexus_graph.py`
- Test: `tests/test_wrapup.py`

Replace the dead `ceo_review_node` revise loop with a terminal CEO wrap-up that speaks a summary of `worker_results`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_wrapup.py`:

```python
"""CEO wrap-up node — speaks a single summary after workers finish."""
import pytest
from unittest.mock import AsyncMock, patch
from langchain_core.runnables import RunnableConfig


@pytest.mark.asyncio
async def test_wrapup_runs_ceo_and_processes_once():
    from app.graph.nodes import wrapup
    state = {
        "task": "build a books site",
        "worker_results": [{"agent": "backend", "result": "[DONE: API ready]"}],
    }
    config = RunnableConfig(configurable={"thread_id": "t-wrap", "model": "claude"})

    with patch.object(wrapup, "run_claude_agent", new_callable=AsyncMock) as run_ceo, \
         patch.object(wrapup.pipeline, "process", new_callable=AsyncMock) as proc, \
         patch("app.graph.broadcast.send", new_callable=AsyncMock):
        run_ceo.return_value = "[SPEAK: All done — the team shipped the API. | emotion: excited]"
        out = await wrapup.ceo_wrapup_node(state, config)

    run_ceo.assert_called_once()
    assert run_ceo.call_args[0][0] == "ceo"
    proc.assert_called_once()
    assert proc.call_args[0][1] == "ceo"
    assert out["ceo_verdict"] == "done"


@pytest.mark.asyncio
async def test_wrapup_skips_when_no_results():
    from app.graph.nodes import wrapup
    state = {"task": "noop", "worker_results": []}
    config = RunnableConfig(configurable={"thread_id": "t-wrap2", "model": "claude"})

    with patch.object(wrapup, "run_claude_agent", new_callable=AsyncMock) as run_ceo, \
         patch.object(wrapup.pipeline, "process", new_callable=AsyncMock):
        out = await wrapup.ceo_wrapup_node(state, config)

    run_ceo.assert_not_called()
    assert out["ceo_verdict"] == "done"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_wrapup.py -v`
Expected: FAIL (`app.graph.nodes.wrapup` does not exist).

- [ ] **Step 3: Create `app/graph/nodes/wrapup.py`**

```python
# app/graph/nodes/wrapup.py
"""CEO wrap-up node — speaks a single summary of worker results, then ends."""
import logging

from langchain_core.runnables import RunnableConfig

from app.agents.runner import run_claude_agent
from app.graph.state import NexusState
from app.graph import broadcast
from app.output import pipeline

logger = logging.getLogger(__name__)


async def ceo_wrapup_node(state: NexusState, config: RunnableConfig) -> dict:
    thread_id = config.get("configurable", {}).get("thread_id", "")

    async def send(data: dict) -> None:
        await broadcast.send(thread_id, data)

    results = state.get("worker_results", [])
    if not results:
        return {"ceo_verdict": "done", "revision_notes": ""}

    results_text = "\n".join(
        f"[{r['agent']}]: {r['result'][:500]}" for r in results
    )
    prompt = (
        f"The team just finished working on this task:\n\nTASK: {state['task']}\n\n"
        f"WORKER RESULTS:\n{results_text}\n\n"
        "Give the user a short, warm spoken wrap-up (2-3 sentences) of what the "
        "team accomplished. Speak it with a [SPEAK: ... | emotion: ...] tag."
    )
    response = await run_claude_agent("ceo", prompt, send)
    await pipeline.process(response, "ceo", send)
    return {"ceo_verdict": "done", "revision_notes": "", "ceo_response": response}
```

- [ ] **Step 4: Wire it into the graph (terminal)**

In `app/graph/nexus_graph.py`:

1. Replace the review import:

```python
from app.graph.nodes.wrapup import ceo_wrapup_node
```
(remove `from app.graph.nodes.review import ceo_review_node`)

2. Delete the `route_after_review` function entirely.

3. In `build_nexus_graph`, replace the review node registration and edges. Change:

```python
    graph.add_node("ceo_review_node", ceo_review_node)
```
to:

```python
    graph.add_node("ceo_wrapup_node", ceo_wrapup_node)
```

4. Change the worker→review edges and the conditional review edges. Replace:

```python
    for agent_id in _KNOWN_AGENTS:
        graph.add_edge(agent_id, "ceo_review_node")

    graph.add_conditional_edges(
        "ceo_review_node",
        route_after_review,
        {"ceo_node": "ceo_node", "__end__": END},
    )
```
with:

```python
    for agent_id in _KNOWN_AGENTS:
        graph.add_edge(agent_id, "ceo_wrapup_node")

    graph.add_edge("ceo_wrapup_node", END)
```

- [ ] **Step 5: Run tests to verify pass**

Run: `python -m pytest tests/test_wrapup.py -v`
Expected: PASS.

- [ ] **Step 6: Verify graph still builds**

Run: `python -c "import asyncio; from app.graph.checkpointer import get_checkpointer; from app.graph.nexus_graph import build_nexus_graph; asyncio.run((lambda: build_nexus_graph(asyncio.run(get_checkpointer())))()) if False else build_nexus_graph(asyncio.get_event_loop().run_until_complete(get_checkpointer()))"`

If that one-liner is awkward in the environment, instead run the existing graph/delegation tests:
Run: `python -m pytest tests/test_delegation.py -v`
Expected: PASS (or update any test that referenced `ceo_review_node`/`route_after_review` — search with `grep -rn "ceo_review_node\|route_after_review" tests/` and fix those references to the wrap-up node).

- [ ] **Step 7: Commit**

```bash
git add app/graph/nodes/wrapup.py app/graph/nexus_graph.py tests/test_wrapup.py
git commit -m "feat: replace dead review loop with terminal CEO spoken wrap-up"
```

---

## Task 6: Remove duplicate assistant-emit path

**Files:**
- Modify: `app/api/websocket.py` (`_translate_event`, lines 111-115)
- Test: `tests/test_websocket.py` (extend)

The `on_chat_model_stream` branch double-emits CEO text and leaks the LangChain review model's raw tokens. `pipeline.process` is the canonical text emitter; CEO live streaming is handled separately in Task 9 via a distinct event type.

- [ ] **Step 1: Write failing test**

Add to `tests/test_websocket.py`:

```python
def test_translate_event_ignores_chat_model_stream():
    from app.api.websocket import _translate_event

    class _Chunk:
        content = "some streamed text"

    event = {
        "event": "on_chat_model_stream",
        "name": "ChatGoogleGenerativeAI",
        "metadata": {},
        "data": {"chunk": _Chunk()},
    }
    assert _translate_event(event, "t1") is None
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_websocket.py::test_translate_event_ignores_chat_model_stream -v`
Expected: FAIL (currently returns an assistant dict).

- [ ] **Step 3: Delete the branch**

In `app/api/websocket.py`, remove these lines (111-115):

```python
    if kind == "on_chat_model_stream":
        chunk = data.get("chunk", {})
        content = getattr(chunk, "content", "") if hasattr(chunk, "content") else ""
        if content:
            return {"type": "assistant", "agent": agent_id or "ceo", "message": {"content": content}, "thread_id": thread_id}
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_websocket.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/api/websocket.py tests/test_websocket.py
git commit -m "fix: drop duplicate on_chat_model_stream assistant emit"
```

---

## Task 7: Global FIFO run queue

**Files:**
- Create: `app/api/run_queue.py`
- Test: `tests/test_run_queue.py`

A single global serial executor: one run at a time across the app; emits a `queued` notice when busy.

- [ ] **Step 1: Write failing tests**

Create `tests/test_run_queue.py`:

```python
"""Global FIFO run queue — serial execution + queued notice."""
import asyncio
import pytest


@pytest.mark.asyncio
async def test_jobs_run_serially_in_order():
    from app.api.run_queue import RunQueue
    q = RunQueue()
    order = []

    async def make(n):
        order.append(("start", n))
        await asyncio.sleep(0.02)
        order.append(("end", n))

    async def notify(_): pass

    await q.enqueue({"coro_factory": lambda: make(1), "label": "one"}, notify)
    await q.enqueue({"coro_factory": lambda: make(2), "label": "two"}, notify)
    await q.join()

    # Strictly serial: job 1 fully completes before job 2 starts.
    assert order == [("start", 1), ("end", 1), ("start", 2), ("end", 2)]


@pytest.mark.asyncio
async def test_second_job_gets_queued_notice():
    from app.api.run_queue import RunQueue
    q = RunQueue()
    notices = []

    async def slow():
        await asyncio.sleep(0.05)

    async def notify(data):
        notices.append(data)

    await q.enqueue({"coro_factory": slow, "label": "first"}, notify)
    await asyncio.sleep(0.005)  # let first start
    await q.enqueue({"coro_factory": slow, "label": "second"}, notify)
    await q.join()

    queued = [n for n in notices if n.get("type") == "queued"]
    assert len(queued) == 1
    assert queued[0]["task"] == "second"
    assert queued[0]["position"] >= 1


@pytest.mark.asyncio
async def test_first_job_gets_no_queued_notice():
    from app.api.run_queue import RunQueue
    q = RunQueue()
    notices = []

    async def quick():
        return None

    async def notify(data):
        notices.append(data)

    await q.enqueue({"coro_factory": quick, "label": "only"}, notify)
    await q.join()
    assert [n for n in notices if n.get("type") == "queued"] == []


@pytest.mark.asyncio
async def test_clear_flushes_pending():
    from app.api.run_queue import RunQueue
    q = RunQueue()
    ran = []

    async def slow():
        await asyncio.sleep(0.05)
        ran.append("slow")

    async def never():
        ran.append("never")

    async def notify(_): pass

    await q.enqueue({"coro_factory": slow, "label": "a"}, notify)
    await asyncio.sleep(0.005)
    await q.enqueue({"coro_factory": never, "label": "b"}, notify)
    q.clear()
    await asyncio.sleep(0.1)
    assert "never" not in ran
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_run_queue.py -v`
Expected: FAIL (module does not exist).

- [ ] **Step 3: Implement `app/api/run_queue.py`**

```python
# app/api/run_queue.py
"""Global FIFO run queue — the company runs one task at a time.

A single async consumer drains the queue serially. User messages and
scheduled routines both enqueue here, so nothing ever runs (or speaks)
concurrently. When a job is enqueued while another is active/waiting, the
provided `notify` callback receives a {"type": "queued", ...} message.
"""
import asyncio
import logging
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

Notify = Callable[[dict], Awaitable[None]]


class RunQueue:
    def __init__(self) -> None:
        self._queue: asyncio.Queue = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._current: asyncio.Task | None = None

    def start(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run_loop())

    async def enqueue(self, job: dict, notify: Notify) -> None:
        """job = {"coro_factory": () -> coroutine, "label": str}."""
        ahead = (1 if self._current is not None else 0) + self._queue.qsize()
        await self._queue.put(job)
        self.start()
        if ahead > 0:
            try:
                await notify({
                    "type": "queued",
                    "position": ahead,
                    "task": job.get("label", ""),
                    "agent": "ceo",
                })
            except Exception:
                logger.warning("queued-notice failed", exc_info=True)

    async def _run_loop(self) -> None:
        while True:
            job = await self._queue.get()
            self._current = asyncio.create_task(job["coro_factory"]())
            try:
                await self._current
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("run_queue job error")
            finally:
                self._current = None
                self._queue.task_done()

    def cancel_current(self) -> None:
        if self._current and not self._current.done():
            self._current.cancel()

    def clear(self) -> None:
        """Cancel the running job and drop everything still queued."""
        self.cancel_current()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break

    async def join(self) -> None:
        """Wait until the queue is fully drained (test helper)."""
        await self._queue.join()


_run_queue: RunQueue | None = None


def get_run_queue() -> RunQueue:
    global _run_queue
    if _run_queue is None:
        _run_queue = RunQueue()
    return _run_queue
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_run_queue.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/api/run_queue.py tests/test_run_queue.py
git commit -m "feat: add global FIFO run queue with queued notice"
```

---

## Task 8: Route WebSocket runs through the queue + immediate ack

**Files:**
- Modify: `app/api/websocket.py` (`ws_endpoint`, `_run_and_stream`)
- Test: `tests/test_websocket.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_websocket.py`:

```python
@pytest.mark.asyncio
async def test_run_and_stream_sends_immediate_ack(monkeypatch):
    from app.api import websocket as ws_module

    events = []

    async def fake_broadcast(data):
        events.append(data)

    async def fake_astream(*a, **k):
        if False:
            yield {}
        return

    monkeypatch.setattr(ws_module, "broadcast_event", fake_broadcast)

    class _Graph:
        def astream_events(self, *a, **k):
            return fake_astream()

    monkeypatch.setattr(ws_module, "build_nexus_graph", lambda cp: _Graph(), raising=False)

    async def fake_cp():
        return None
    monkeypatch.setattr(ws_module, "get_checkpointer", fake_cp, raising=False)

    await ws_module._run_and_stream("create a books site", "t-ack", "claude")

    # First broadcast is the CEO planning ack.
    assert events, "no events emitted"
    first = events[0]
    assert first["type"] == "assistant"
    assert first["agent"] == "ceo"
    text = first["message"]["content"][0]["text"]
    assert "planning" in text.lower()
```

> Note: `_run_and_stream` imports `build_nexus_graph` and `get_checkpointer` locally today. For testability, move those imports to module level in `app/api/websocket.py` (top of file) so the monkeypatches above resolve. Do that as part of Step 3.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_websocket.py::test_run_and_stream_sends_immediate_ack -v`
Expected: FAIL (no ack today; local imports).

- [ ] **Step 3: Hoist imports + add immediate ack**

In `app/api/websocket.py`:

1. Add near the top imports:

```python
from app.graph.nexus_graph import build_nexus_graph
from app.graph.checkpointer import get_checkpointer
from app.api.run_queue import get_run_queue
```

2. Remove the two local imports inside `_run_and_stream`.

3. At the very start of `_run_and_stream` (right after `cp = await get_checkpointer()` / `graph = build_nexus_graph(cp)` and defining `send_fn`/registering broadcast), send the ack before the astream loop:

```python
    bcast.register(thread_id, send_fn)
    await broadcast_event({
        "type": "assistant",
        "agent": "ceo",
        "message": {"content": [{"type": "text", "text": "On it — planning…"}]},
        "bark_ok": True,  # ack is text-only; suppress speech-synth fallback
    })
    try:
        ...
```

(`bark_ok: True` prevents the frontend speech fallback from voicing the ack.)

- [ ] **Step 4: Route messages through the queue**

In `ws_endpoint`, replace the `if msg_type == "message":` block so user messages enqueue instead of spawning overlapping tasks:

```python
            if msg_type == "message":
                target = msg.get("agent") or "ceo"
                text = msg["text"]
                model = session.model
                if target == "ceo":
                    job = {
                        "coro_factory": (lambda t=text, m=model:
                                         _run_and_stream(t, thread_id, m)),
                        "label": text[:100],
                    }
                else:
                    job = {
                        "coro_factory": (lambda tg=target, t=text, m=model:
                                         _run_direct(tg, t, m)),
                        "label": f"{target}: {text[:80]}",
                    }
                await get_run_queue().enqueue(job, broadcast_event)
```

And update the cancel/clear handlers to drive the queue:

```python
            elif msg_type == "cancel_worker":
                get_run_queue().cancel_current()

            elif msg_type == "clear":
                get_run_queue().clear()
```

Remove the now-unused `_active_runs` dict and its references in `ws_endpoint` (search `grep -n "_active_runs" app/api/websocket.py` and delete those lines, including the `finally:` cancellation that referenced it).

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_websocket.py -v`
Expected: PASS. If `test_run_direct_*` referenced `_active_runs`, they don't — they call `_run_direct` directly and still pass.

- [ ] **Step 6: Commit**

```bash
git add app/api/websocket.py tests/test_websocket.py
git commit -m "feat: route ws runs through FIFO queue; add immediate CEO ack"
```

---

## Task 9: Stream CEO planning text

**Files:**
- Modify: `app/agents/runner.py` (`run_claude_agent`)
- Modify: `nexus-ui/src/store.ts`
- Test: `tests/test_executor_gemini.py` or a new runner test

The CEO turn should stream its text live. To avoid duplicating the final `pipeline.process` message (Task 6 removed the generic stream branch), emit live deltas as a distinct `ceo_stream` event the frontend renders as a typing preview; the committed message still comes from `pipeline.process`.

- [ ] **Step 1: Write failing test**

Add `tests/test_ceo_stream.py`:

```python
"""run_claude_agent streams CEO assistant text as ceo_stream deltas."""
import pytest
from unittest.mock import AsyncMock, patch


class _FakeStdout:
    def __init__(self, lines):
        self._lines = [l.encode() for l in lines]

    def __aiter__(self):
        async def gen():
            for l in self._lines:
                yield l
        return gen()


class _FakeProc:
    def __init__(self, lines):
        self.stdout = _FakeStdout(lines)
        self.stderr = AsyncMock()
        self.stderr.read = AsyncMock(return_value=b"")
        self.returncode = 0

    async def wait(self):
        return 0


@pytest.mark.asyncio
async def test_ceo_text_streams_as_ceo_stream():
    import app.agents.runner as runner
    import json

    line = json.dumps({
        "type": "assistant",
        "message": {"role": "assistant",
                    "content": [{"type": "text", "text": "Planning the site"}]},
    })
    proc = _FakeProc([line])
    sent = []

    async def send(data):
        sent.append(data)

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as cse, \
         patch.object(runner, "_build_claude_prompt", new_callable=AsyncMock) as bp:
        cse.return_value = proc
        bp.return_value = "prompt"
        result = await runner.run_claude_agent("ceo", "build a books site", send)

    assert "Planning the site" in result
    stream_events = [s for s in sent if s.get("type") == "ceo_stream"]
    assert any("Planning the site" in s.get("delta", "") for s in stream_events)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_ceo_stream.py -v`
Expected: FAIL (no `ceo_stream` emitted; CEO text currently suppressed).

- [ ] **Step 3: Emit `ceo_stream` deltas for the CEO**

In `app/agents/runner.py`, inside `run_claude_agent`, in the `async for raw in proc.stdout:` loop, where assistant text blocks are accumulated, also stream them for the CEO. Replace:

```python
            if obj.get("type") == "assistant":
                for blk in obj.get("message", {}).get("content", []):
                    if blk.get("type") == "text":
                        full_resp += blk["text"]
```

with:

```python
            if obj.get("type") == "assistant":
                for blk in obj.get("message", {}).get("content", []):
                    if blk.get("type") == "text":
                        full_resp += blk["text"]
                        if agent_id == "ceo" and blk["text"]:
                            await send({
                                "type": "ceo_stream",
                                "agent": "ceo",
                                "delta": blk["text"],
                            })
```

> `ceo_stream` is a preview channel only. The committed CEO message + audio still comes from `pipeline.process` in `ceo_node`/`wrapup`. The frontend (Step 5) shows the preview while streaming and clears it when the committed `assistant` message arrives.

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_ceo_stream.py -v`
Expected: PASS.

- [ ] **Step 5: Handle `ceo_stream` + `queued` in the frontend store**

In `nexus-ui/src/store.ts`, add two cases inside the `switch (type)` block (near the `assistant` case):

```ts
        case 'queued': {
          addNotif(
            `Task queued (#${event.position ?? '?'}): ${String(event.task ?? '').slice(0, 60)}`,
            'system',
          )
          break
        }

        case 'ceo_stream': {
          const prev = agents['ceo'] ?? defaultAgent('ceo')
          updateAgent('ceo', {
            status: 'thinking',
            streamPreview: `${prev.streamPreview ?? ''}${event.delta ?? ''}`,
          })
          break
        }
```

When the committed CEO `assistant` message arrives, clear the preview. In the existing `case 'assistant':`, after computing `content`, add (only for ceo):

```ts
          if (agentId === 'ceo') updateAgent('ceo', { streamPreview: '' })
```

Add `streamPreview?: string` to the agent type in `nexus-ui/src/types.ts` (find the `Agent`/agent state interface and add the optional field), and include `streamPreview: ''` in `defaultAgent(...)`.

- [ ] **Step 6: Build frontend**

Run: `cd nexus-ui && npm run build`
Expected: build succeeds, no TS errors.

- [ ] **Step 7: Commit**

```bash
git add app/agents/runner.py tests/test_ceo_stream.py nexus-ui/src/store.ts nexus-ui/src/types.ts app/static
git commit -m "feat: stream CEO planning text via ceo_stream preview channel"
```

---

## Task 10: Route scheduled routines through the queue

**Files:**
- Modify: `app/services/scheduler.py` (`_maybe_fire`)
- Test: `tests/test_scheduler.py`

Routines must queue behind user tasks instead of broadcasting concurrently.

- [ ] **Step 1: Write failing test**

Add to `tests/test_scheduler.py`:

```python
def test_maybe_fire_enqueues_via_run_queue(monkeypatch):
    import app.services.scheduler as sched
    from datetime import datetime
    import pytz

    enqueued = []

    class _FakeQueue:
        async def enqueue(self, job, notify):
            enqueued.append(job)

    monkeypatch.setattr(sched, "get_run_queue", lambda: _FakeQueue(), raising=False)

    captured = {}

    def fake_create_task(coro):
        captured["coro"] = coro
        coro.close()  # avoid 'never awaited' warning
        return None

    monkeypatch.setattr(sched.asyncio, "create_task", fake_create_task)

    # A routine whose schedule matches the current minute (every minute).
    routine = {"id": "r1", "name": "R", "schedule": "* * * * *",
               "timezone": "UTC", "enabled": True, "agent": "ceo", "prompt": "hi"}
    sched._maybe_fire(routine, {})

    # _maybe_fire scheduled a coroutine (the enqueue) via create_task.
    assert "coro" in captured
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_scheduler.py::test_maybe_fire_enqueues_via_run_queue -v`
Expected: FAIL (currently `create_task(run_routine(routine))`, no `get_run_queue`).

- [ ] **Step 3: Enqueue routines**

In `app/services/scheduler.py`:

1. Add import near the top:

```python
from app.api.run_queue import get_run_queue
```

2. In `_maybe_fire`, replace:

```python
    fired[fire_key] = datetime.utcnow().isoformat()
    asyncio.create_task(run_routine(routine))
    logger.info("Fired routine '%s' (schedule=%s)", routine["id"], routine["schedule"])
```

with:

```python
    fired[fire_key] = datetime.utcnow().isoformat()

    async def _enqueue() -> None:
        from app.api.websocket import broadcast_event
        await get_run_queue().enqueue(
            {"coro_factory": (lambda r=routine: run_routine(r)),
             "label": f"routine:{routine['id']}"},
            broadcast_event,
        )

    asyncio.create_task(_enqueue())
    logger.info("Fired routine '%s' (schedule=%s)", routine["id"], routine["schedule"])
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/scheduler.py tests/test_scheduler.py
git commit -m "feat: route scheduled routines through the FIFO run queue"
```

---

## Task 11: Start the run queue at app startup

**Files:**
- Modify: `app/main.py` (lifespan)

- [ ] **Step 1: Start the queue in lifespan**

In `app/main.py`, in the `lifespan` function, after the background services block (`asyncio.create_task(scheduler.start_scheduler_loop())`), add:

```python
    from app.api.run_queue import get_run_queue
    get_run_queue().start()
```

- [ ] **Step 2: Verify the app imports/boots**

Run: `python -c "import app.main"`
Expected: no import errors.

Run the full suite:
Run: `python -m pytest tests/ -q`
Expected: PASS (fix any test that still references removed symbols — `grep -rn "ceo_review_node\|route_after_review\|_active_runs" tests/ app/` and reconcile).

- [ ] **Step 3: Commit**

```bash
git add app/main.py
git commit -m "chore: start global run queue in app lifespan"
```

---

## Task 12: End-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Full test suite**

Run: `python -m pytest tests/ -q`
Expected: all PASS.

- [ ] **Step 2: Frontend build**

Run: `cd nexus-ui && npm run build`
Expected: succeeds.

- [ ] **Step 3: Manual smoke (per project deployment convention)**

Bring up the container (`docker compose up -d` per project), open the UI on the host port from `PORT_REGISTRY.json` (host 3031 → container 3030 per memory; confirm against `docker ps`), and send: **"create a books recommendation site"**. Verify:
  - CEO shows "On it — planning…" immediately, then streamed planning text.
  - Workers light up in parallel but produce **no audio** — only the CEO voice is heard.
  - Exactly one spoken CEO wrap-up at the end.
  - Sending a second message while the first runs shows a "Task queued" notification and does not overlap.

- [ ] **Step 4: Final commit (if any tweaks)**

```bash
git add -A
git commit -m "test: verify NEXUS stability fix end-to-end"
```

---

## Self-Review Notes (for the implementer)

- **Spec A (CEO-only voice):** Tasks 1 (server gate), 2 (frontend speech-fallback gate), 3 (prompt). All three layers covered — server, browser TTS fallback, and prompt.
- **Spec B (FIFO queue + notice):** Tasks 7, 8, 10, 11.
- **Spec C (dedup):** Task 6.
- **Spec D (ack + streaming):** Tasks 8 (ack), 9 (streaming).
- **Spec E (wrap-up + worker_results):** Tasks 4, 5.
- If any existing test references `ceo_review_node`, `route_after_review`, or `_active_runs`, update it as encountered (Tasks 5/8/11 call this out).
