# Browser Agent Maya Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Maya, a 5th NEXUS worker agent that runs up to 5 Playwright browser sessions for job searching, CV tailoring via Overleaf, and job application automation — all visible in a live Browser Board in the NEXUS UI.

**Architecture:** A standalone `browser-svc` Docker container (Python + Playwright + Chromium, port 9002) exposes a FastAPI REST API. Maya lives in NEXUS as a Claude agent whose persona instructs it to emit tool tags (`[BROWSER_APPLY:url]` etc.). `executor.py` intercepts these tags and calls `browser-svc` over internal HTTP. `browser-svc` pushes CDP screencast frames back to NEXUS via a WebSocket relay, which NEXUS broadcasts to all frontends. The existing `broadcast_event()` function is reused unchanged.

**Tech Stack:** Python 3.11, FastAPI, Playwright 1.48, playwright-stealth, Anthropic Python SDK, websockets, httpx, pytest-asyncio; Docker Compose; Vanilla JS island UI.

---

## File Map

| Path | Action | Purpose |
|------|--------|---------|
| `browser-svc/Dockerfile` | Create | Playwright + Chromium container image |
| `browser-svc/requirements.txt` | Create | Python dependencies |
| `browser-svc/main.py` | Create | FastAPI app, all HTTP endpoints, lifespan |
| `browser-svc/session_manager.py` | Create | Slot lifecycle, Playwright contexts, CDP screencast |
| `browser-svc/relay_client.py` | Create | WebSocket client that pushes frames to NEXUS |
| `browser-svc/stealth.py` | Create | UA rotation, human-timing helpers, bezier mouse |
| `browser-svc/cv_enhancer.py` | Create | Anthropic API call for LaTeX CV tailoring |
| `browser-svc/overleaf_pipeline.py` | Create | Overleaf login, LaTeX edit, compile, PDF download |
| `browser-svc/job_workflow.py` | Create | Form fill, CV attach, discovery modes, apply pipeline |
| `browser-svc/browser_profile.json` | Create | Applicant profile (volume-mounted, user-editable) |
| `browser-svc/cv_exports/.gitkeep` | Create | Tailored CV output directory |
| `browser-svc/tests/conftest.py` | Create | asyncio_mode=auto, shared mock fixtures |
| `browser-svc/tests/test_session_manager.py` | Create | SlotState, acquire/release, screencast start |
| `browser-svc/tests/test_stealth.py` | Create | UA rotation, bezier, timing bounds |
| `browser-svc/tests/test_cv_enhancer.py` | Create | Anthropic mock, apply_edits |
| `browser-svc/tests/test_overleaf_pipeline.py` | Create | No-credentials fallback, login error fallback |
| `browser-svc/tests/test_job_workflow.py` | Create | Field resolver, company guesser, profile loader |
| `browser-svc/tests/test_main.py` | Create | Health, slots, profile CRUD, slot-busy 409 |
| `app/config.py` | Modify | Add `BROWSER_SVC_URL` |
| `app/agents/definitions.py` | Modify | Add `"browser"` entry (Maya) to `AGENT_DEFS` |
| `app/agents/tools.py` | Modify | Add `BROWSER_APPLY`, `BROWSER_DISCOVER`, `BROWSER_COMPANY`, `BROWSER_PROFILE_MATCH` parsers |
| `app/agents/executor.py` | Modify | Add `browser_apply/discover/company/profile_match` handlers in `_execute_tool` + icon/label maps |
| `app/services/browser_svc.py` | Create | Thin httpx client: `call_browser_svc(tool_type, args) -> str` |
| `app/main.py` | Modify | Register `/ws/browser-relay` WebSocket endpoint |
| `app/static/index.html` | Modify | Add `island-board` island + Maya pill button |
| `app/static/app-v5.js` | Modify | `handleBrowserFrame()`, `initBrowserBoard()`, profile modal JS |
| `app/static/style-v5.css` | Modify | `.island-board` sizing rule |
| `docker-compose.yml` | Modify | Add `browser-svc` service, port 9002, volumes, env vars |

---

## Task 1: browser-svc scaffold

**Files:**
- Create: `browser-svc/Dockerfile`
- Create: `browser-svc/requirements.txt`
- Create: `browser-svc/browser_profile.json`
- Create: `browser-svc/cv_exports/.gitkeep`
- Create: `browser-svc/tests/conftest.py`
- Create: `browser-svc/tests/test_main.py`
- Create: `browser-svc/main.py` (health endpoint only)

- [ ] **Step 1: Write the failing test**

Create `browser-svc/tests/test_main.py`:

```python
from fastapi.testclient import TestClient


def test_health():
    from main import app
    with TestClient(app) as client:
        r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["slots"] == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run from `browser-svc/` directory:
```bash
cd /mnt/HC_Volume_105874680/virtual-company/browser-svc
python -m pytest tests/test_main.py::test_health -v
```
Expected: `ModuleNotFoundError: No module named 'main'`

- [ ] **Step 3: Create directory structure and scaffold files**

Create `browser-svc/Dockerfile`:
```dockerfile
FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium --with-deps

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9002"]
```

Create `browser-svc/requirements.txt`:
```
fastapi==0.115.0
uvicorn[standard]==0.32.0
playwright==1.48.0
playwright-stealth==1.0.6
anthropic>=0.40.0
websockets>=13.0
httpx>=0.27.0
pytest==8.3.3
pytest-asyncio==0.24.0
```

Create `browser-svc/browser_profile.json`:
```json
{
  "name": "Saurav Subaru",
  "email": "sauravsubaru@gmail.com",
  "phone": "",
  "linkedin": "",
  "experience_years": 5,
  "notice_period": "immediate",
  "target_roles": ["Backend Engineer", "Python Developer", "ML Engineer"],
  "target_companies": ["Stripe", "Razorpay", "CRED"],
  "skills": ["Python", "FastAPI", "ML"],
  "location_preference": "Bangalore / Remote"
}
```

Create `browser-svc/cv_exports/.gitkeep` (empty file).

Create `browser-svc/tests/conftest.py`:
```python
import pytest

# Enable asyncio mode for all tests in this directory
pytest_plugins = ("pytest_asyncio",)
```

Create `browser-svc/tests/__init__.py` (empty).

Create `browser-svc/main.py`:
```python
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

logger = logging.getLogger(__name__)
PROFILE_PATH = Path("/app/browser_profile.json")
CV_DEFAULT_PATH = Path("/app/cv_default.pdf")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="browser-svc", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "slots": 5}
```

- [ ] **Step 4: Install deps and run test**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/browser-svc
pip install fastapi uvicorn pytest pytest-asyncio httpx --quiet
python -m pytest tests/test_main.py::test_health -v
```
Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
cd /mnt/HC_Volume_105874680/virtual-company
git add browser-svc/
git commit -m "feat(browser-svc): scaffold service — health endpoint, profile, Dockerfile"
```

---

## Task 2: Session manager

**Files:**
- Create: `browser-svc/session_manager.py`
- Create: `browser-svc/tests/test_session_manager.py`

- [ ] **Step 1: Write the failing tests**

Create `browser-svc/tests/test_session_manager.py`:
```python
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from session_manager import SessionManager, SlotState


@pytest.fixture
def sm():
    manager = SessionManager()
    mock_browser = AsyncMock()
    mock_context = AsyncMock()
    mock_page = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    manager._browser = mock_browser
    return manager


@pytest.mark.asyncio
async def test_initial_state_all_idle(sm):
    assert len(sm._slots) == 5
    assert all(s.state == SlotState.IDLE for s in sm._slots)


@pytest.mark.asyncio
async def test_acquire_marks_slot_busy(sm):
    slot = await sm.acquire(0)
    assert slot.state == SlotState.BUSY
    assert sm._slots[0].state == SlotState.BUSY


@pytest.mark.asyncio
async def test_acquire_busy_slot_raises(sm):
    await sm.acquire(1)
    with pytest.raises(RuntimeError, match="already busy"):
        await sm.acquire(1)


@pytest.mark.asyncio
async def test_release_marks_slot_idle(sm):
    await sm.acquire(2)
    await sm.release(2)
    assert sm._slots[2].state == SlotState.IDLE
    assert sm._slots[2].url == ""
    assert sm._slots[2].action == ""


@pytest.mark.asyncio
async def test_find_free_slot_skips_busy(sm):
    await sm.acquire(0)
    free = sm.find_free_slot()
    assert free == 1


@pytest.mark.asyncio
async def test_find_free_slot_returns_none_when_all_busy(sm):
    for i in range(5):
        await sm.acquire(i)
    assert sm.find_free_slot() is None


@pytest.mark.asyncio
async def test_status_returns_five_dicts(sm):
    statuses = sm.status()
    assert len(statuses) == 5
    for s in statuses:
        assert "slot_id" in s and "state" in s and "url" in s and "action" in s
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/browser-svc
python -m pytest tests/test_session_manager.py -v
```
Expected: `ModuleNotFoundError: No module named 'session_manager'`

- [ ] **Step 3: Implement session_manager.py**

Create `browser-svc/session_manager.py`:
```python
import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page


class SlotState(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    ERROR = "error"


@dataclass
class SlotInfo:
    slot_id: int
    state: SlotState = SlotState.IDLE
    url: str = ""
    action: str = ""
    context: Optional[BrowserContext] = field(default=None, repr=False)
    page: Optional[Page] = field(default=None, repr=False)
    cdp_session: Optional[object] = field(default=None, repr=False)


class SessionManager:
    NUM_SLOTS = 5

    def __init__(self):
        self._slots: list[SlotInfo] = [SlotInfo(i) for i in range(self.NUM_SLOTS)]
        self._browser: Optional[Browser] = None
        self._pw = None
        self._lock = asyncio.Lock()

    async def start(self):
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

    async def stop(self):
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def acquire(self, slot_id: int) -> SlotInfo:
        async with self._lock:
            slot = self._slots[slot_id]
            if slot.state == SlotState.BUSY:
                raise RuntimeError(f"Slot {slot_id} is already busy")
            if slot.context is None:
                slot.context = await self._browser.new_context(
                    viewport={"width": 1280, "height": 900},
                )
                slot.page = await slot.context.new_page()
            slot.state = SlotState.BUSY
            return slot

    async def release(self, slot_id: int):
        async with self._lock:
            slot = self._slots[slot_id]
            slot.state = SlotState.IDLE
            slot.url = ""
            slot.action = ""

    def status(self) -> list[dict]:
        return [
            {"slot_id": s.slot_id, "state": s.state.value, "url": s.url, "action": s.action}
            for s in self._slots
        ]

    def find_free_slot(self, exclude: int = -1) -> Optional[int]:
        for s in self._slots:
            if s.slot_id != exclude and s.state == SlotState.IDLE:
                return s.slot_id
        return None

    async def start_screencast(self, slot_id: int, relay) -> None:
        slot = self._slots[slot_id]
        if slot.page is None or slot.cdp_session is not None:
            return
        cdp = await slot.context.new_cdp_session(slot.page)
        slot.cdp_session = cdp

        async def on_frame(event):
            relay.push({
                "type": "browser_frame",
                "slot": slot_id,
                "frame": event["data"],
                "url": slot.url,
                "action": slot.action,
            })
            try:
                await cdp.send("Page.screencastFrameAck", {"sessionId": event["sessionId"]})
            except Exception:
                pass

        cdp.on("Page.screencastFrame", on_frame)
        await cdp.send("Page.startScreencast", {
            "format": "jpeg",
            "quality": 60,
            "maxWidth": 1280,
            "maxHeight": 800,
            "everyNthFrame": 1,
        })

    async def stop_screencast(self, slot_id: int) -> None:
        slot = self._slots[slot_id]
        if slot.cdp_session is None:
            return
        try:
            await slot.cdp_session.send("Page.stopScreencast")
        except Exception:
            pass
        slot.cdp_session = None


session_manager = SessionManager()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/browser-svc
python -m pytest tests/test_session_manager.py -v
```
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
cd /mnt/HC_Volume_105874680/virtual-company
git add browser-svc/session_manager.py browser-svc/tests/test_session_manager.py
git commit -m "feat(browser-svc): session manager — slot lifecycle and CDP screencast"
```

---

## Task 3: Relay client

**Files:**
- Create: `browser-svc/relay_client.py`
- Create: `browser-svc/tests/test_relay_client.py`

- [ ] **Step 1: Write the failing test**

Create `browser-svc/tests/test_relay_client.py`:
```python
import asyncio
import pytest
from relay_client import RelayClient


def test_push_queues_item():
    relay = RelayClient()
    relay.push({"type": "browser_frame", "slot": 0, "frame": "abc"})
    assert relay._queue.qsize() == 1


def test_push_drops_oldest_when_full():
    relay = RelayClient()
    # Fill queue to maxsize
    for i in range(30):
        relay.push({"seq": i})
    # Now push one more — should drop oldest, queue stays at 30
    relay.push({"seq": 30})
    assert relay._queue.qsize() == 30
    # The newest item should be in the queue (we can't guarantee order easily,
    # but qsize should be capped)


def test_start_creates_task():
    import asyncio

    async def _run():
        relay = RelayClient()
        relay.start()
        assert relay._task is not None
        relay._task.cancel()
        try:
            await relay._task
        except (asyncio.CancelledError, Exception):
            pass

    asyncio.run(_run())
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/browser-svc
python -m pytest tests/test_relay_client.py -v
```
Expected: `ModuleNotFoundError: No module named 'relay_client'`

- [ ] **Step 3: Implement relay_client.py**

Create `browser-svc/relay_client.py`:
```python
import asyncio
import json
import logging
import os

import websockets

logger = logging.getLogger(__name__)

NEXUS_WS_URL = os.environ.get(
    "NEXUS_WS_URL", "ws://virtual-company:3030/ws/browser-relay"
)


class RelayClient:
    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=30)
        self._task: asyncio.Task | None = None

    def push(self, data: dict) -> None:
        try:
            self._queue.put_nowait(data)
        except asyncio.QueueFull:
            # Drop oldest, insert newest
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(data)
            except Exception:
                pass

    def start(self):
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def _run(self):
        while True:
            try:
                async with websockets.connect(
                    NEXUS_WS_URL,
                    ping_interval=20,
                    ping_timeout=10,
                ) as ws:
                    logger.info("browser-relay connected to NEXUS")
                    while True:
                        data = await asyncio.wait_for(
                            self._queue.get(), timeout=30
                        )
                        await ws.send(json.dumps(data))
            except Exception as exc:
                logger.warning(
                    "browser-relay disconnected (%s) — retrying in 3s", exc
                )
                await asyncio.sleep(3)


relay = RelayClient()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/browser-svc
python -m pytest tests/test_relay_client.py -v
```
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
cd /mnt/HC_Volume_105874680/virtual-company
git add browser-svc/relay_client.py browser-svc/tests/test_relay_client.py
git commit -m "feat(browser-svc): relay client — WebSocket frame pusher to NEXUS"
```

---

## Task 4: Stealth module

**Files:**
- Create: `browser-svc/stealth.py`
- Create: `browser-svc/tests/test_stealth.py`

- [ ] **Step 1: Write the failing tests**

Create `browser-svc/tests/test_stealth.py`:
```python
import asyncio
import pytest

from stealth import random_ua, random_viewport, _bezier, human_delay, _USER_AGENTS


def test_random_ua_is_known():
    assert random_ua() in _USER_AGENTS


def test_random_viewport_in_range():
    vp = random_viewport()
    assert 1280 <= vp["width"] <= 1440
    assert 768 <= vp["height"] <= 900


def test_bezier_at_zero_is_p0():
    assert _bezier(0, 10, 20, 30, 40) == pytest.approx(10.0)


def test_bezier_at_one_is_p3():
    assert _bezier(1, 10, 20, 30, 40) == pytest.approx(40.0)


def test_bezier_midpoint_is_between():
    mid = _bezier(0.5, 0, 0, 100, 100)
    assert 0 < mid < 100


@pytest.mark.asyncio
async def test_human_delay_within_bounds():
    import time
    start = time.monotonic()
    await human_delay(100, 200)
    elapsed = time.monotonic() - start
    # Allow generous upper bound for slow CI
    assert 0.09 < elapsed < 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/browser-svc
python -m pytest tests/test_stealth.py -v
```
Expected: `ModuleNotFoundError: No module named 'stealth'`

- [ ] **Step 3: Implement stealth.py**

Create `browser-svc/stealth.py`:
```python
import asyncio
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page, BrowserContext

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

_STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
window.chrome = {runtime: {}};
"""


def random_ua() -> str:
    return random.choice(_USER_AGENTS)


def random_viewport() -> dict:
    return {
        "width": random.randint(1280, 1440),
        "height": random.randint(768, 900),
    }


async def apply_stealth(context: "BrowserContext") -> None:
    try:
        from playwright_stealth import stealth_async as _sa  # noqa: F401
    except ImportError:
        pass
    await context.add_init_script(_STEALTH_SCRIPT)


async def human_delay(min_ms: int = 800, max_ms: int = 2500) -> None:
    await asyncio.sleep(random.uniform(min_ms / 1000, max_ms / 1000))


async def human_click_delay(min_ms: int = 300, max_ms: int = 1200) -> None:
    await asyncio.sleep(random.uniform(min_ms / 1000, max_ms / 1000))


def _bezier(t: float, p0: float, p1: float, p2: float, p3: float) -> float:
    return (
        (1 - t) ** 3 * p0
        + 3 * (1 - t) ** 2 * t * p1
        + 3 * (1 - t) * t ** 2 * p2
        + t ** 3 * p3
    )


async def human_move_and_click(page: "Page", x: int, y: int) -> None:
    vp = page.viewport_size or {"width": 1280, "height": 800}
    sx = random.randint(0, vp["width"])
    sy = random.randint(0, vp["height"])
    cp1x = random.randint(min(sx, x), max(sx, x))
    cp1y = random.randint(min(sy, y), max(sy, y))
    cp2x = random.randint(min(sx, x), max(sx, x))
    cp2y = random.randint(min(sy, y), max(sy, y))
    steps = random.randint(20, 40)
    for i in range(steps + 1):
        t = i / steps
        mx = int(_bezier(t, sx, cp1x, cp2x, x))
        my = int(_bezier(t, sy, cp1y, cp2y, y))
        await page.mouse.move(mx, my)
        await asyncio.sleep(random.uniform(0.005, 0.015))
    await asyncio.sleep(random.uniform(0.1, 0.3))
    await page.mouse.click(x, y)


async def human_type(page: "Page", selector: str, text: str) -> None:
    await page.click(selector)
    await human_click_delay(200, 500)
    for char in text:
        await page.keyboard.type(char, delay=random.uniform(80, 250))
        if random.random() < 0.05:
            await asyncio.sleep(random.uniform(0.3, 0.8))


async def scroll_to_read(page: "Page") -> None:
    height = await page.evaluate("document.body.scrollHeight")
    steps = random.randint(3, 7)
    for _ in range(steps):
        scroll_to = random.randint(100, max(200, height // max(steps, 1)))
        await page.evaluate(f"window.scrollBy(0, {scroll_to})")
        await asyncio.sleep(random.uniform(0.4, 1.2))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/browser-svc
python -m pytest tests/test_stealth.py -v
```
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
cd /mnt/HC_Volume_105874680/virtual-company
git add browser-svc/stealth.py browser-svc/tests/test_stealth.py
git commit -m "feat(browser-svc): stealth module — UA rotation, human timing, bezier mouse"
```

---

## Task 5: CV enhancer

**Files:**
- Create: `browser-svc/cv_enhancer.py`
- Create: `browser-svc/tests/test_cv_enhancer.py`

- [ ] **Step 1: Write the failing tests**

Create `browser-svc/tests/test_cv_enhancer.py`:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from cv_enhancer import CVEdit, apply_edits

SAMPLE_LATEX = r"""\documentclass{article}
\begin{document}
\section{Skills}
Python, Django, REST APIs
\end{document}"""


def test_apply_edits_replaces_text():
    edits = [{"old": "Django, REST APIs", "new": "FastAPI, REST APIs, asyncio"}]
    result = apply_edits(SAMPLE_LATEX, edits)
    assert "FastAPI" in result
    assert "Django" not in result


def test_apply_edits_skips_missing_old():
    edits = [{"old": "NOTEXIST", "new": "something"}]
    result = apply_edits(SAMPLE_LATEX, edits)
    assert result == SAMPLE_LATEX


def test_apply_edits_multiple():
    edits = [
        {"old": "Django", "new": "FastAPI"},
        {"old": "REST APIs", "new": "REST APIs, async"},
    ]
    result = apply_edits(SAMPLE_LATEX, edits)
    assert "FastAPI" in result
    assert "async" in result


@pytest.mark.asyncio
async def test_enhance_cv_calls_anthropic_and_parses():
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"edits": [{"old": "Django", "new": "FastAPI"}], "keywords": ["FastAPI", "async"]}'
        )
    ]

    with patch("cv_enhancer.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            from cv_enhancer import enhance_cv
            result = await enhance_cv("FastAPI JD", SAMPLE_LATEX)

    assert isinstance(result, CVEdit)
    assert result.keywords == ["FastAPI", "async"]
    assert result.edits == [{"old": "Django", "new": "FastAPI"}]


@pytest.mark.asyncio
async def test_enhance_cv_strips_markdown_fences():
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='```json\n{"edits": [], "keywords": ["k1"]}\n```'
        )
    ]

    with patch("cv_enhancer.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            from cv_enhancer import enhance_cv
            result = await enhance_cv("JD", SAMPLE_LATEX)

    assert result.keywords == ["k1"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/browser-svc
python -m pytest tests/test_cv_enhancer.py -v
```
Expected: `ModuleNotFoundError: No module named 'cv_enhancer'`

- [ ] **Step 3: Implement cv_enhancer.py**

Create `browser-svc/cv_enhancer.py`:
```python
import json
import os
from dataclasses import dataclass

import anthropic

_SYSTEM = (
    "You are an expert LaTeX CV editor. Given a job description and a LaTeX CV source, "
    "output ONLY a JSON object with two fields:\n"
    "- \"edits\": list of {\"old\": str, \"new\": str} pairs (LaTeX block replacements)\n"
    "- \"keywords\": list of keywords injected\n\n"
    "Rules: tailor to highlight relevant skills, inject up to 8 keywords naturally, "
    "keep changes minimal and professional. Output valid JSON only, no markdown."
)


@dataclass
class CVEdit:
    edits: list[dict[str, str]]
    keywords: list[str]


async def enhance_cv(job_description: str, latex_source: str) -> CVEdit:
    client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=_SYSTEM,
        messages=[{
            "role": "user",
            "content": f"JOB DESCRIPTION:\n{job_description}\n\nLATEX CV:\n{latex_source}",
        }],
    )
    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:]
    data = json.loads(raw)
    return CVEdit(edits=data.get("edits", []), keywords=data.get("keywords", []))


def apply_edits(latex_source: str, edits: list[dict[str, str]]) -> str:
    result = latex_source
    for edit in edits:
        old, new = edit.get("old", ""), edit.get("new", "")
        if old and old in result:
            result = result.replace(old, new, 1)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/browser-svc
pip install anthropic --quiet
python -m pytest tests/test_cv_enhancer.py -v
```
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
cd /mnt/HC_Volume_105874680/virtual-company
git add browser-svc/cv_enhancer.py browser-svc/tests/test_cv_enhancer.py
git commit -m "feat(browser-svc): CV enhancer — Claude API LaTeX diff generation"
```

---

## Task 6: Overleaf pipeline

**Files:**
- Create: `browser-svc/overleaf_pipeline.py`
- Create: `browser-svc/tests/test_overleaf_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Create `browser-svc/tests/test_overleaf_pipeline.py`:
```python
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import overleaf_pipeline as op


@pytest.mark.asyncio
async def test_tailor_and_export_no_credentials_returns_default():
    page = AsyncMock()
    original_email = op.OVERLEAF_EMAIL
    original_url = op.OVERLEAF_PROJECT_URL
    op.OVERLEAF_EMAIL = ""
    op.OVERLEAF_PROJECT_URL = ""

    result = await op.tailor_and_export(page, "JD text", "Stripe", "Backend")

    op.OVERLEAF_EMAIL = original_email
    op.OVERLEAF_PROJECT_URL = original_url
    assert result == op.CV_DEFAULT_PATH


@pytest.mark.asyncio
async def test_tailor_and_export_returns_default_on_login_error():
    page = AsyncMock()
    page.goto = AsyncMock(side_effect=Exception("Network error"))

    with patch.object(op, "OVERLEAF_EMAIL", "test@test.com"), \
         patch.object(op, "OVERLEAF_PROJECT_URL", "https://overleaf.com/project/abc"):
        result = await op.tailor_and_export(page, "JD", "CRED", "ML")

    assert result == op.CV_DEFAULT_PATH


def test_cv_exports_dir_is_inside_app():
    assert str(op.CV_EXPORTS_DIR) == "/app/cv_exports"


def test_cv_default_path_is_inside_app():
    assert str(op.CV_DEFAULT_PATH) == "/app/cv_default.pdf"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/browser-svc
python -m pytest tests/test_overleaf_pipeline.py -v
```
Expected: `ModuleNotFoundError: No module named 'overleaf_pipeline'`

- [ ] **Step 3: Implement overleaf_pipeline.py**

Create `browser-svc/overleaf_pipeline.py`:
```python
import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from playwright.async_api import Page
    from session_manager import SlotInfo

logger = logging.getLogger(__name__)

OVERLEAF_EMAIL = os.environ.get("OVERLEAF_EMAIL", "")
OVERLEAF_PASSWORD = os.environ.get("OVERLEAF_PASSWORD", "")
OVERLEAF_PROJECT_URL = os.environ.get("OVERLEAF_PROJECT_URL", "")
CV_EXPORTS_DIR = Path("/app/cv_exports")
CV_DEFAULT_PATH = Path("/app/cv_default.pdf")


async def _login(page: "Page") -> None:
    await page.goto("https://www.overleaf.com/login", wait_until="networkidle")
    await page.fill("input[name='email']", OVERLEAF_EMAIL)
    await page.fill("input[name='password']", OVERLEAF_PASSWORD)
    await page.click("button[type='submit']")
    await page.wait_for_url("**/project**", timeout=15000)


async def _open_project(page: "Page") -> None:
    await page.goto(OVERLEAF_PROJECT_URL, wait_until="networkidle")
    try:
        source_btn = page.locator("button:has-text('Source')")
        if await source_btn.is_visible(timeout=3000):
            await source_btn.click()
            await asyncio.sleep(1)
    except Exception:
        pass


async def _get_latex_source(page: "Page") -> str:
    return await page.evaluate(
        "() => window._codeMirror?.getValue() "
        "|| document.querySelector('.cm-content')?.textContent || ''"
    )


async def _set_latex_source(page: "Page", content: str) -> None:
    escaped = content.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
    await page.evaluate(f"""
        () => {{
            const cm = window._codeMirror;
            if (cm) {{
                cm.setValue(`{escaped}`);
            }} else {{
                const editor = document.querySelector('.cm-content');
                if (editor) {{
                    editor.focus();
                    document.execCommand('selectAll');
                    document.execCommand('insertText', false, `{escaped}`);
                }}
            }}
        }}
    """)


async def _compile_and_wait(page: "Page", timeout: int = 60) -> bool:
    try:
        await page.click(
            "button[data-testid='recompile-btn'], button:has-text('Recompile')",
            timeout=5000,
        )
    except Exception:
        await page.keyboard.press("Control+Enter")
    try:
        await page.wait_for_selector(
            "[data-testid='pdf-viewer'], .pdf-viewer, iframe[src*='pdf']",
            timeout=timeout * 1000,
        )
        return True
    except Exception:
        return False


async def _download_pdf(page: "Page", company: str, role: str) -> Path:
    CV_EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_company = company.replace(" ", "_").replace("/", "_")
    safe_role = role.replace(" ", "_").replace("/", "_")
    dest = CV_EXPORTS_DIR / f"cv_{safe_company}_{safe_role}_{date_str}.pdf"

    async with page.expect_download() as dl_info:
        try:
            await page.click("a[download], button:has-text('Download PDF')", timeout=5000)
        except Exception:
            pass
    dl = await dl_info.value
    await dl.save_as(str(dest))
    return dest


async def tailor_and_export(
    page: "Page",
    job_description: str,
    company: str,
    role: str,
    slot_info: Optional["SlotInfo"] = None,
) -> Path:
    """Run the full Overleaf CV pipeline. Returns PDF path or CV_DEFAULT_PATH on failure."""
    from cv_enhancer import enhance_cv, apply_edits

    if not OVERLEAF_EMAIL or not OVERLEAF_PROJECT_URL:
        logger.warning("Overleaf credentials not configured — using default CV")
        return CV_DEFAULT_PATH

    try:
        if slot_info:
            slot_info.action = "Logging in to Overleaf"
        if "overleaf.com" not in page.url:
            await _login(page)

        if slot_info:
            slot_info.action = "Opening project"
        await _open_project(page)

        if slot_info:
            slot_info.action = "Reading LaTeX source"
        latex = await _get_latex_source(page)
        if not latex.strip():
            raise ValueError("Could not read LaTeX source from Overleaf")

        if slot_info:
            slot_info.action = "Tailoring CV with Claude"
        cv_edit = await enhance_cv(job_description, latex)
        new_latex = apply_edits(latex, cv_edit.edits)

        if slot_info:
            slot_info.action = f"Compiling ({len(cv_edit.keywords)} keywords injected)"
        await _set_latex_source(page, new_latex)
        ok = await _compile_and_wait(page)
        if not ok:
            raise TimeoutError("Compile timed out")

        if slot_info:
            slot_info.action = "Downloading PDF"
        pdf_path = await _download_pdf(page, company, role)
        logger.info("CV exported: %s", pdf_path.name)
        return pdf_path

    except Exception as exc:
        logger.warning("Overleaf pipeline failed (%s) — using default CV", exc)
        return CV_DEFAULT_PATH
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/browser-svc
python -m pytest tests/test_overleaf_pipeline.py -v
```
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
cd /mnt/HC_Volume_105874680/virtual-company
git add browser-svc/overleaf_pipeline.py browser-svc/tests/test_overleaf_pipeline.py
git commit -m "feat(browser-svc): Overleaf pipeline — LaTeX edit, compile, PDF download, fallback"
```

---

## Task 7: Job workflow

**Files:**
- Create: `browser-svc/job_workflow.py`
- Create: `browser-svc/tests/test_job_workflow.py`

- [ ] **Step 1: Write the failing tests**

Create `browser-svc/tests/test_job_workflow.py`:
```python
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from job_workflow import _resolve_field, _guess_company, ApplyResult


_PROFILE = {
    "name": "Saurav Subaru",
    "email": "saurav@test.com",
    "phone": "9999999999",
    "linkedin": "https://linkedin.com/in/saurav",
    "experience_years": 5,
    "notice_period": "immediate",
    "location_preference": "Bangalore / Remote",
    "target_roles": ["Backend Engineer"],
    "target_companies": ["Stripe"],
    "skills": ["Python"],
}


def test_resolve_field_email():
    assert _resolve_field("email address", _PROFILE) == "saurav@test.com"


def test_resolve_field_full_name():
    assert _resolve_field("Full Name", _PROFILE) == "Saurav Subaru"


def test_resolve_field_first_name():
    assert _resolve_field("First Name", _PROFILE) == "Saurav"


def test_resolve_field_last_name():
    assert _resolve_field("Last Name", _PROFILE) == "Subaru"


def test_resolve_field_phone():
    assert _resolve_field("Mobile Number", _PROFILE) == "9999999999"


def test_resolve_field_linkedin():
    assert _resolve_field("LinkedIn Profile", _PROFILE) == "https://linkedin.com/in/saurav"


def test_resolve_field_unknown_returns_none():
    assert _resolve_field("salary_expectations_xyz", _PROFILE) is None


def test_guess_company_linkedin():
    assert _guess_company("https://www.linkedin.com/jobs/123") == "Linkedin"


def test_guess_company_careers_subdomain():
    assert _guess_company("https://careers.stripe.com/apply/123") == "Careers"


def test_guess_company_custom_domain():
    assert _guess_company("https://razorpay.com/jobs/123") == "Razorpay"


def test_apply_result_fields():
    r = ApplyResult(url="https://test.com", company="Test", role="Eng", status="applied")
    assert r.status == "applied"
    assert r.keywords == []
    assert r.error == ""


def test_load_profile_reads_json(tmp_path):
    profile_data = {"name": "Test User", "email": "t@t.com"}
    profile_file = tmp_path / "browser_profile.json"
    profile_file.write_text(json.dumps(profile_data))

    import job_workflow as jw
    original = jw.PROFILE_PATH
    jw.PROFILE_PATH = profile_file
    result = jw.load_profile()
    jw.PROFILE_PATH = original
    assert result["name"] == "Test User"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/browser-svc
python -m pytest tests/test_job_workflow.py -v
```
Expected: `ModuleNotFoundError: No module named 'job_workflow'`

- [ ] **Step 3: Implement job_workflow.py**

Create `browser-svc/job_workflow.py`:
```python
import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from urllib.parse import urlparse

if TYPE_CHECKING:
    from playwright.async_api import Page
    from session_manager import SlotInfo

logger = logging.getLogger(__name__)
PROFILE_PATH = Path("/app/browser_profile.json")


def load_profile() -> dict:
    return json.loads(PROFILE_PATH.read_text())


@dataclass
class ApplyResult:
    url: str
    company: str
    role: str
    status: str  # "applied" | "failed" | "captcha" | "skipped"
    cv_path: str = ""
    keywords: list[str] = field(default_factory=list)
    error: str = ""


# ── Field resolver ─────────────────────────────────────────────────────────────

_FIELD_PATTERNS = [
    (r"(?i)first.?name|fname", "first_name"),
    (r"(?i)last.?name|lname|surname", "last_name"),
    (r"(?i)full.?name|your.?name", "full_name"),
    (r"(?i)email", "email"),
    (r"(?i)phone|mobile|contact", "phone"),
    (r"(?i)linkedin", "linkedin"),
    (r"(?i)experience|years", "experience_years"),
    (r"(?i)notice|availability", "notice_period"),
    (r"(?i)location|city", "location_preference"),
]


def _resolve_field(label_text: str, profile: dict) -> Optional[str]:
    full_name = profile.get("name", "")
    parts = full_name.split(" ", 1)
    resolved = {
        "first_name": parts[0] if parts else "",
        "last_name": parts[1] if len(parts) > 1 else "",
        "full_name": full_name,
        "email": profile.get("email", ""),
        "phone": profile.get("phone", ""),
        "linkedin": profile.get("linkedin", ""),
        "experience_years": str(profile.get("experience_years", "")),
        "notice_period": profile.get("notice_period", ""),
        "location_preference": profile.get("location_preference", ""),
    }
    for pattern, field_key in _FIELD_PATTERNS:
        if re.search(pattern, label_text):
            return resolved.get(field_key, "")
    return None


def _guess_company(url: str) -> str:
    host = urlparse(url).netloc.lower()
    parts = host.replace("www.", "").split(".")
    return parts[0].capitalize() if parts else "Unknown"


# ── Job description extraction ─────────────────────────────────────────────────

async def fetch_job_description(page: "Page", url: str) -> str:
    from stealth import scroll_to_read
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await scroll_to_read(page)
    for selector in [
        "[data-testid='jobDescriptionText']",
        ".jobs-description__content",
        ".job-description",
        ".description__text",
        "#job-description",
        "article",
        "main",
    ]:
        try:
            el = page.locator(selector).first
            if await el.is_visible(timeout=2000):
                return await el.inner_text()
        except Exception:
            continue
    return await page.inner_text("body") or ""


# ── Form filling ──────────────────────────────────────────────────────────────

async def fill_form_fields(page: "Page", profile: dict) -> int:
    from stealth import human_click_delay
    filled = 0
    inputs = await page.locator("input:visible, textarea:visible").all()
    for inp in inputs:
        try:
            inp_id = await inp.get_attribute("id") or ""
            inp_name = await inp.get_attribute("name") or ""
            inp_placeholder = await inp.get_attribute("placeholder") or ""
            inp_aria = await inp.get_attribute("aria-label") or ""
            label_text = ""
            if inp_id:
                label_el = page.locator(f"label[for='{inp_id}']")
                if await label_el.count() > 0:
                    label_text = await label_el.first.inner_text()
            search_text = " ".join([label_text, inp_name, inp_placeholder, inp_aria])
            value = _resolve_field(search_text, profile)
            if value:
                await inp.fill(value)
                filled += 1
                await human_click_delay(100, 300)
        except Exception:
            continue
    return filled


async def attach_cv(page: "Page", cv_path: str) -> bool:
    from stealth import human_delay
    for selector in [
        "input[type='file'][accept*='pdf']",
        "input[type='file']",
        "[data-testid='file-upload']",
    ]:
        try:
            file_input = page.locator(selector).first
            if await file_input.count() > 0:
                await file_input.set_input_files(cv_path)
                await human_delay(500, 1000)
                return True
        except Exception:
            continue
    return False


# ── LinkedIn Easy Apply ───────────────────────────────────────────────────────

async def _apply_linkedin_easy(page: "Page", profile: dict, cv_path: str) -> bool:
    from stealth import human_delay
    try:
        easy_btn = page.locator("button:has-text('Easy Apply'), .jobs-apply-button")
        if not await easy_btn.is_visible(timeout=3000):
            return False
        await easy_btn.click()
        await human_delay(1000, 2000)
        for _ in range(10):
            await fill_form_fields(page, profile)
            await attach_cv(page, cv_path)
            submit_btn = page.locator(
                "button:has-text('Submit application'), button:has-text('Review')"
            ).first
            next_btn = page.locator(
                "button:has-text('Next'), button:has-text('Continue'),"
                "button[aria-label='Continue to next step']"
            ).first
            if await submit_btn.is_visible(timeout=1000):
                await submit_btn.click()
                await human_delay(2000, 3000)
                return True
            elif await next_btn.is_visible(timeout=1000):
                await next_btn.click()
                await human_delay(800, 1500)
            else:
                break
        return False
    except Exception as exc:
        logger.warning("LinkedIn Easy Apply failed: %s", exc)
        return False


# ── Generic ATS ───────────────────────────────────────────────────────────────

async def _apply_generic_ats(page: "Page", profile: dict, cv_path: str) -> bool:
    from stealth import human_delay
    try:
        apply_btn = page.locator(
            "a:has-text('Apply'), button:has-text('Apply Now'),"
            "button:has-text('Apply for this job'),"
            "a:has-text('Apply Now'), a:has-text('Apply for this job')"
        ).first
        if await apply_btn.is_visible(timeout=3000):
            await apply_btn.click()
            await human_delay(1500, 2500)
        filled = await fill_form_fields(page, profile)
        await attach_cv(page, cv_path)
        submit = page.locator(
            "button[type='submit'], button:has-text('Submit'), input[type='submit']"
        ).first
        if await submit.is_visible(timeout=3000):
            await submit.click()
            await human_delay(2000, 3000)
            return True
        return filled > 0
    except Exception as exc:
        logger.warning("Generic ATS apply failed: %s", exc)
        return False


# ── Main apply entry point ────────────────────────────────────────────────────

async def apply_to_job(
    page: "Page",
    url: str,
    cv_path: str,
    slot_info: Optional["SlotInfo"] = None,
    overleaf_page: Optional["Page"] = None,
) -> ApplyResult:
    profile = load_profile()
    company = _guess_company(url)
    role = ""
    try:
        if slot_info:
            slot_info.url = url
            slot_info.action = "Fetching job description"
        jd = await fetch_job_description(page, url)
        try:
            role = await page.title() or "Role"
        except Exception:
            role = "Role"
        if overleaf_page is not None:
            if slot_info:
                slot_info.action = "Tailoring CV via Overleaf"
            from overleaf_pipeline import tailor_and_export
            cv_path = str(await tailor_and_export(overleaf_page, jd, company, role))
        if slot_info:
            slot_info.action = f"Applying to {company}"
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        ok = await _apply_linkedin_easy(page, profile, cv_path)
        if not ok:
            ok = await _apply_generic_ats(page, profile, cv_path)
        status = "applied" if ok else "failed"
        return ApplyResult(url=url, company=company, role=role, status=status, cv_path=cv_path)
    except Exception as exc:
        err = str(exc)
        if "captcha" in err.lower() or "cloudflare" in err.lower():
            return ApplyResult(url=url, company=company, role=role, status="captcha", error=err)
        return ApplyResult(url=url, company=company, role=role, status="failed", error=err)


# ── Discovery modes ───────────────────────────────────────────────────────────

async def discover_jobs_linkedin(
    page: "Page", keywords: str, location: str = "Bangalore"
) -> list[str]:
    from stealth import scroll_to_read
    query = keywords.replace(" ", "%20")
    loc = location.replace(" ", "%20")
    url = f"https://www.linkedin.com/jobs/search/?keywords={query}&location={loc}&f_AL=true"
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await scroll_to_read(page)
    links = await page.locator("a.job-card-list__title, a.base-card__full-link").all()
    urls = []
    for link in links[:10]:
        href = await link.get_attribute("href")
        if href and "/jobs/" in href:
            urls.append(href.split("?")[0])
    return list(dict.fromkeys(urls))


async def discover_jobs_indeed(
    page: "Page", keywords: str, location: str = "Bangalore"
) -> list[str]:
    from stealth import scroll_to_read
    query = keywords.replace(" ", "+")
    loc = location.replace(" ", "+")
    url = f"https://in.indeed.com/jobs?q={query}&l={loc}"
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await scroll_to_read(page)
    links = await page.locator("a.jcs-JobTitle, h2.jobTitle a").all()
    urls = []
    for link in links[:10]:
        href = await link.get_attribute("href")
        if href:
            if not href.startswith("http"):
                href = "https://in.indeed.com" + href
            urls.append(href)
    return list(dict.fromkeys(urls))


async def discover_company_roles(
    page: "Page", company: str, target_roles: list[str]
) -> list[str]:
    from stealth import scroll_to_read
    query = f"{company}+careers+jobs"
    await page.goto(
        f"https://www.google.com/search?q={query}",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    await scroll_to_read(page)
    # Try first Google result link containing the company name
    try:
        link = page.locator(f"a[href*='{company.lower()}']").first
        href = await link.get_attribute("href")
        if href and href.startswith("http"):
            await page.goto(href, wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass
    urls = []
    for role in target_roles:
        try:
            role_links = await page.locator(f"a:has-text('{role}')").all()
            for rl in role_links[:3]:
                href = await rl.get_attribute("href")
                if href:
                    if not href.startswith("http"):
                        parsed = urlparse(page.url)
                        href = f"{parsed.scheme}://{parsed.netloc}{href}"
                    urls.append(href)
        except Exception:
            continue
    return list(dict.fromkeys(urls))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/browser-svc
python -m pytest tests/test_job_workflow.py -v
```
Expected: `11 passed`

- [ ] **Step 5: Commit**

```bash
cd /mnt/HC_Volume_105874680/virtual-company
git add browser-svc/job_workflow.py browser-svc/tests/test_job_workflow.py
git commit -m "feat(browser-svc): job workflow — form fill, CV attach, LinkedIn/ATS/discovery pipelines"
```

---

## Task 8: browser-svc REST API

**Files:**
- Modify: `browser-svc/main.py` — add all endpoints, wire SessionManager + RelayClient
- Modify: `browser-svc/tests/test_main.py` — add endpoint tests

- [ ] **Step 1: Write the failing tests**

Replace `browser-svc/tests/test_main.py` with:
```python
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# Prevent actual Playwright/WebSocket startup during tests
with patch("session_manager.async_playwright"), \
     patch("relay_client.websockets"):
    from main import app

from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    import main as m
    # Point to temp profile file so tests are isolated
    original_profile = m.PROFILE_PATH
    tmp_profile = tmp_path / "browser_profile.json"
    tmp_profile.write_text(json.dumps({
        "name": "Test User", "email": "t@t.com", "phone": "",
        "linkedin": "", "experience_years": 3, "notice_period": "1 month",
        "target_roles": ["SWE"], "target_companies": ["Test Corp"],
        "skills": ["Python"], "location_preference": "Remote",
    }))
    m.PROFILE_PATH = tmp_profile
    with TestClient(app) as c:
        yield c
    m.PROFILE_PATH = original_profile


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "slots": 5}


def test_get_slots(client):
    r = client.get("/slots")
    assert r.status_code == 200
    slots = r.json()
    assert len(slots) == 5
    assert all(s["state"] == "idle" for s in slots)


def test_get_profile(client):
    r = client.get("/profile")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "Test User"
    assert data["email"] == "t@t.com"


def test_get_profile_not_found(client, tmp_path):
    import main as m
    original = m.PROFILE_PATH
    m.PROFILE_PATH = tmp_path / "nonexistent.json"
    r = client.get("/profile")
    m.PROFILE_PATH = original
    assert r.status_code == 404


def test_patch_profile(client):
    r = client.patch("/profile", json={"phone": "9999999999", "experience_years": 5})
    assert r.status_code == 200
    data = r.json()
    assert data["phone"] == "9999999999"
    assert data["experience_years"] == 5
    # Existing fields preserved
    assert data["name"] == "Test User"


def test_apply_invalid_slot_zero(client):
    r = client.post("/apply", json={"url": "https://linkedin.com/jobs/123", "slot_id": 0})
    assert r.status_code == 400


def test_apply_invalid_slot_five(client):
    r = client.post("/apply", json={"url": "https://linkedin.com/jobs/123", "slot_id": 5})
    assert r.status_code == 400


def test_apply_queues_job(client):
    r = client.post("/apply", json={"url": "https://linkedin.com/jobs/123", "slot_id": 1})
    assert r.status_code == 200
    data = r.json()
    assert data["queued"] is True
    assert data["slot_id"] == 1


def test_discover_queues_job(client):
    r = client.post("/discover", json={"keywords": "Python backend", "platform": "linkedin"})
    assert r.status_code == 200
    assert r.json()["queued"] is True


def test_company_apply_queues(client):
    r = client.post("/company-apply", json={"company": "Stripe"})
    assert r.status_code == 200
    assert r.json()["queued"] is True


def test_profile_match_queues(client):
    r = client.post("/profile-match", json={})
    assert r.status_code == 200
    assert r.json()["queued"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/browser-svc
python -m pytest tests/test_main.py -v
```
Expected: tests fail because `/profile-match` and other endpoints don't exist yet.

- [ ] **Step 3: Rewrite main.py with all endpoints**

Replace `browser-svc/main.py` with:
```python
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel

from relay_client import relay
from session_manager import SlotState, session_manager

logger = logging.getLogger(__name__)
PROFILE_PATH = Path("/app/browser_profile.json")
CV_DEFAULT_PATH = Path("/app/cv_default.pdf")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await session_manager.start()
    relay.start()
    yield
    await session_manager.stop()


app = FastAPI(title="browser-svc", lifespan=lifespan)


# ── Status ─────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "slots": 5}


@app.get("/slots")
def get_slots():
    return session_manager.status()


# ── Profile ────────────────────────────────────────────────────────────────────

@app.get("/profile")
def get_profile():
    if not PROFILE_PATH.exists():
        raise HTTPException(404, "Profile not found")
    return json.loads(PROFILE_PATH.read_text())


class ProfileUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin: str | None = None
    experience_years: int | None = None
    notice_period: str | None = None
    target_roles: list[str] | None = None
    target_companies: list[str] | None = None
    skills: list[str] | None = None
    location_preference: str | None = None


@app.patch("/profile")
def update_profile(update: ProfileUpdate):
    current = json.loads(PROFILE_PATH.read_text()) if PROFILE_PATH.exists() else {}
    current.update(update.model_dump(exclude_none=True))
    PROFILE_PATH.write_text(json.dumps(current, indent=2))
    return current


# ── Helpers ────────────────────────────────────────────────────────────────────

def _slot_is_busy(slot_id: int) -> bool:
    return session_manager.status()[slot_id]["state"] == SlotState.BUSY


async def _run_apply(url: str, slot_id: int, use_overleaf: bool):
    from job_workflow import apply_to_job

    overleaf_page = None
    overleaf_acquired = False

    slot = await session_manager.acquire(slot_id)
    await session_manager.start_screencast(slot_id, relay)
    try:
        if use_overleaf and not _slot_is_busy(0):
            overleaf_slot = await session_manager.acquire(0)
            overleaf_acquired = True
            await session_manager.start_screencast(0, relay)
            overleaf_page = overleaf_slot.page

        cv_path = str(CV_DEFAULT_PATH)
        result = await apply_to_job(
            slot.page, url, cv_path,
            slot_info=slot, overleaf_page=overleaf_page,
        )
        logger.info("Apply result: %s %s → %s", result.company, result.role, result.status)
        return result
    finally:
        await session_manager.stop_screencast(slot_id)
        await session_manager.release(slot_id)
        if overleaf_acquired:
            await session_manager.stop_screencast(0)
            await session_manager.release(0)


# ── Apply endpoints ────────────────────────────────────────────────────────────

class ApplyRequest(BaseModel):
    url: str
    slot_id: int = 1
    use_overleaf: bool = True


@app.post("/apply")
async def apply_endpoint(req: ApplyRequest, bg: BackgroundTasks):
    if req.slot_id < 1 or req.slot_id > 4:
        raise HTTPException(400, "slot_id must be 1–4 (slot 0 is reserved for Overleaf)")
    if _slot_is_busy(req.slot_id):
        raise HTTPException(409, f"Slot {req.slot_id} is busy")
    bg.add_task(_run_apply, req.url, req.slot_id, req.use_overleaf)
    return {"queued": True, "slot_id": req.slot_id, "url": req.url}


class DiscoverRequest(BaseModel):
    keywords: str
    platform: str = "linkedin"
    location: str = "Bangalore"
    slot_id: int = 1
    use_overleaf: bool = True


@app.post("/discover")
async def discover_endpoint(req: DiscoverRequest, bg: BackgroundTasks):
    if _slot_is_busy(req.slot_id):
        raise HTTPException(409, f"Slot {req.slot_id} is busy")

    async def run():
        from job_workflow import discover_jobs_linkedin, discover_jobs_indeed
        slot = await session_manager.acquire(req.slot_id)
        await session_manager.start_screencast(req.slot_id, relay)
        try:
            if req.platform == "indeed":
                urls = await discover_jobs_indeed(slot.page, req.keywords, req.location)
            else:
                urls = await discover_jobs_linkedin(slot.page, req.keywords, req.location)
            for url in urls:
                await _run_apply(url, req.slot_id, req.use_overleaf)
        finally:
            await session_manager.stop_screencast(req.slot_id)
            await session_manager.release(req.slot_id)

    bg.add_task(run)
    return {"queued": True, "platform": req.platform, "keywords": req.keywords}


class CompanyRequest(BaseModel):
    company: str
    slot_id: int = 1
    use_overleaf: bool = True


@app.post("/company-apply")
async def company_apply_endpoint(req: CompanyRequest, bg: BackgroundTasks):
    if _slot_is_busy(req.slot_id):
        raise HTTPException(409, f"Slot {req.slot_id} is busy")

    async def run():
        from job_workflow import discover_company_roles, load_profile
        slot = await session_manager.acquire(req.slot_id)
        await session_manager.start_screencast(req.slot_id, relay)
        try:
            profile = load_profile()
            urls = await discover_company_roles(
                slot.page, req.company, profile.get("target_roles", [])
            )
            for url in urls:
                await _run_apply(url, req.slot_id, req.use_overleaf)
        finally:
            await session_manager.stop_screencast(req.slot_id)
            await session_manager.release(req.slot_id)

    bg.add_task(run)
    return {"queued": True, "company": req.company}


class ProfileMatchRequest(BaseModel):
    slot_id: int = 1
    use_overleaf: bool = True


@app.post("/profile-match")
async def profile_match_endpoint(req: ProfileMatchRequest, bg: BackgroundTasks):
    if _slot_is_busy(req.slot_id):
        raise HTTPException(409, f"Slot {req.slot_id} is busy")

    async def run():
        from job_workflow import discover_company_roles, load_profile
        profile = load_profile()
        companies = profile.get("target_companies", [])
        roles = profile.get("target_roles", [])
        slot = await session_manager.acquire(req.slot_id)
        await session_manager.start_screencast(req.slot_id, relay)
        try:
            for company in companies:
                urls = await discover_company_roles(slot.page, company, roles)
                for url in urls:
                    await _run_apply(url, req.slot_id, req.use_overleaf)
        finally:
            await session_manager.stop_screencast(req.slot_id)
            await session_manager.release(req.slot_id)

    bg.add_task(run)
    return {"queued": True, "mode": "profile_match"}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/browser-svc
python -m pytest tests/test_main.py -v
```
Expected: `11 passed`

- [ ] **Step 5: Commit**

```bash
cd /mnt/HC_Volume_105874680/virtual-company
git add browser-svc/main.py browser-svc/tests/test_main.py
git commit -m "feat(browser-svc): full REST API — apply, discover, company-apply, profile-match, profile CRUD"
```

---

## Task 9: Maya agent + NEXUS tool tags

**Files:**
- Modify: `app/config.py` — add `BROWSER_SVC_URL`
- Modify: `app/agents/definitions.py` — add `"browser"` Maya entry
- Modify: `app/agents/tools.py` — add four browser tool tag parsers
- Modify: `app/agents/executor.py` — add four browser tool handlers + icon/label entries
- Create: `app/services/browser_svc.py` — HTTP client for browser-svc
- Create: `tests/test_maya_agent.py` — unit tests for tag parsing + executor dispatch

> **Note:** Tests for Maya run inside the NEXUS container (`/app/`). Run them with: `python -m pytest tests/test_maya_agent.py -v` from the `/app/` working directory (i.e., `/home/subaru/projects/virtual-company/`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_maya_agent.py` in the virtual-company repo root (alongside existing tests):
```python
"""Tests for Maya browser agent integration in NEXUS."""
import pytest
from unittest.mock import AsyncMock, patch

from app.agents.tools import parse_tool_call
from app.services.browser_svc import call_browser_svc


# ── Tool tag parsing ──────────────────────────────────────────────────────────

def test_parse_browser_apply():
    tool, args = parse_tool_call("[BROWSER_APPLY: https://linkedin.com/jobs/123]")
    assert tool == "browser_apply"
    assert args["url"] == "https://linkedin.com/jobs/123"


def test_parse_browser_discover_with_platform_and_location():
    tool, args = parse_tool_call("[BROWSER_DISCOVER: Python backend | linkedin | Bangalore]")
    assert tool == "browser_discover"
    assert args["keywords"] == "Python backend"
    assert args["platform"] == "linkedin"
    assert args["location"] == "Bangalore"


def test_parse_browser_discover_defaults():
    tool, args = parse_tool_call("[BROWSER_DISCOVER: FastAPI jobs]")
    assert tool == "browser_discover"
    assert args["keywords"] == "FastAPI jobs"
    assert args["platform"] == "linkedin"
    assert args["location"] == "Bangalore"


def test_parse_browser_company():
    tool, args = parse_tool_call("[BROWSER_COMPANY: Stripe]")
    assert tool == "browser_company"
    assert args["company"] == "Stripe"


def test_parse_browser_profile_match():
    tool, args = parse_tool_call("[BROWSER_PROFILE_MATCH]")
    assert tool == "browser_profile_match"
    assert args == {}


def test_parse_unknown_is_none():
    tool, args = parse_tool_call("No tool here")
    assert tool is None
    assert args is None


# ── browser_svc HTTP client ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_call_browser_svc_apply_success():
    with patch("app.services.browser_svc.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = lambda: {"queued": True, "slot_id": 1}
        mock_response.raise_for_status = lambda: None
        mock_client.post = AsyncMock(return_value=mock_response)

        result = await call_browser_svc("browser_apply", {"url": "https://test.com"})

    assert "queued" in result


@pytest.mark.asyncio
async def test_call_browser_svc_unreachable_returns_error_string():
    with patch("app.services.browser_svc.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))

        result = await call_browser_svc("browser_apply", {"url": "https://test.com"})

    assert "unreachable" in result.lower() or "connection" in result.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/subaru/projects/virtual-company
python -m pytest tests/test_maya_agent.py -v
```
Expected: failures on `parse_tool_call` missing browser tags and `browser_svc` module not found.

- [ ] **Step 3: Add BROWSER_SVC_URL to config.py**

Edit `/home/subaru/projects/virtual-company/app/config.py`. Add after line 60 (`BARK_SVC_URL = ...`):

```python
# Browser automation sidecar
BROWSER_SVC_URL = os.environ.get("BROWSER_SVC_URL", "http://browser-svc:9002")
```

- [ ] **Step 4: Add Maya to definitions.py**

Edit `/home/subaru/projects/virtual-company/app/agents/definitions.py`.

Find the closing `}` of `AGENT_DEFS` (after the last worker entry) and add before it:

```python
    "browser": {
        "name":        "Maya",
        "title":       "Browser Automation Agent",
        "color":       "#00ff88",
        "avatar":      "MA",
        "description": "Job search, CV tailoring, and application automation via Playwright.",
        "persona":     _worker_persona(
            "Maya",
            "Browser Automation Agent",
            "Python, Playwright, CDP, Anthropic API, Job Applications",
            """You control up to 5 browser instances (slots 0–4).
Slot 0 is reserved for Overleaf CV tailoring. Slots 1–4 handle job applications.

Use these tool tags to trigger browser actions:

  [BROWSER_APPLY: https://job-url]
      Apply to a specific job URL. Slot auto-selected.

  [BROWSER_DISCOVER: keywords | platform | location]
      Find jobs on a board and apply. platform: "linkedin" or "indeed". location default: "Bangalore".
      Example: [BROWSER_DISCOVER: FastAPI backend | linkedin | Bangalore]

  [BROWSER_COMPANY: Company Name]
      Find open roles on a company's careers page and apply based on target_roles in profile.
      Example: [BROWSER_COMPANY: Stripe]

  [BROWSER_PROFILE_MATCH]
      Use target_companies from profile, visit each careers page, and apply to matching roles.

After each action you will receive a result string. Report:
- Company name, role title, status (applied/failed/captcha/skipped)
- Number of keywords injected into CV (if Overleaf pipeline ran)
- Any blockers (captcha, login required, etc.)

End with [DONE: N applied, M skipped — summary]
""",
        ),
    },
```

- [ ] **Step 5: Add browser tool parsers to tools.py**

Edit `/home/subaru/projects/virtual-company/app/agents/tools.py`.

Find the line `return None, None` at the very end of `parse_tool_call()` (line 274) and insert before it:

```python
    m = re.search(r'\[BROWSER_APPLY:\s*(\S+)\]', text)
    if m:
        return "browser_apply", {"url": m.group(1).strip()}

    m = re.search(r'\[BROWSER_DISCOVER:\s*([^\]]+)\]', text)
    if m:
        parts = [p.strip() for p in m.group(1).split("|")]
        return "browser_discover", {
            "keywords": parts[0] if parts else "",
            "platform": parts[1] if len(parts) > 1 else "linkedin",
            "location": parts[2] if len(parts) > 2 else "Bangalore",
        }

    m = re.search(r'\[BROWSER_COMPANY:\s*([^\]]+)\]', text)
    if m:
        return "browser_company", {"company": m.group(1).strip()}

    m = re.search(r'\[BROWSER_PROFILE_MATCH\]', text)
    if m:
        return "browser_profile_match", {}

```

- [ ] **Step 6: Create app/services/browser_svc.py**

Create `/home/subaru/projects/virtual-company/app/services/browser_svc.py`:
```python
"""Thin HTTP client for the browser-svc sidecar."""
import httpx

from app.config import BROWSER_SVC_URL

_ENDPOINT_MAP = {
    "browser_apply":         "/apply",
    "browser_discover":      "/discover",
    "browser_company":       "/company-apply",
    "browser_profile_match": "/profile-match",
}

_PAYLOAD_MAP = {
    "browser_apply":         lambda a: {"url": a.get("url", ""), "slot_id": 1, "use_overleaf": True},
    "browser_discover":      lambda a: {
        "keywords": a.get("keywords", ""),
        "platform": a.get("platform", "linkedin"),
        "location": a.get("location", "Bangalore"),
        "slot_id": 1,
        "use_overleaf": True,
    },
    "browser_company":       lambda a: {"company": a.get("company", ""), "slot_id": 1, "use_overleaf": True},
    "browser_profile_match": lambda a: {"slot_id": 1, "use_overleaf": True},
}


async def call_browser_svc(tool_type: str, tool_args: dict) -> str:
    endpoint = _ENDPOINT_MAP.get(tool_type, "/apply")
    payload_fn = _PAYLOAD_MAP.get(tool_type, lambda a: {})
    payload = payload_fn(tool_args)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(f"{BROWSER_SVC_URL}{endpoint}", json=payload)
            if r.status_code == 409:
                return f"[browser-svc: slot busy — task will run when a slot frees]"
            r.raise_for_status()
            return str(r.json())
    except Exception as exc:
        return f"[browser-svc unreachable: {exc}]"
```

- [ ] **Step 7: Add browser handlers to executor.py**

Edit `/home/subaru/projects/virtual-company/app/agents/executor.py`.

**7a.** In `icon_map` dict (around line 758), add these entries after the `"jira_comment"` line:
```python
        "browser_apply":         "🌐",
        "browser_discover":      "🔍",
        "browser_company":       "🏢",
        "browser_profile_match": "👤",
```

**7b.** In `label_map` dict (around line 782), add after the `"jira_comment"` line:
```python
        "browser_apply":         "Applying via Browser",
        "browser_discover":      "Discovering Jobs",
        "browser_company":       "Searching Company Careers",
        "browser_profile_match": "Profile-Matched Job Search",
```

**7c.** In `_execute_tool`, after the `elif tool_type == "jira_comment":` block (line 1018), add before the `else:` fallthrough:
```python
        elif tool_type in ("browser_apply", "browser_discover",
                           "browser_company", "browser_profile_match"):
            from app.services.browser_svc import call_browser_svc
            result = await call_browser_svc(tool_type, tool_args)
```

- [ ] **Step 8: Run tests to verify they pass**

```bash
cd /home/subaru/projects/virtual-company
python -m pytest tests/test_maya_agent.py -v
```
Expected: `8 passed`

- [ ] **Step 9: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/config.py app/agents/definitions.py app/agents/tools.py \
        app/agents/executor.py app/services/browser_svc.py \
        tests/test_maya_agent.py
git commit -m "feat(nexus): Maya agent — tool tags, executor handlers, browser_svc client"
```

---

## Task 10: NEXUS browser-relay WebSocket endpoint

**Files:**
- Modify: `app/main.py` — add `/ws/browser-relay` endpoint
- Create: `tests/test_browser_relay.py`

- [ ] **Step 1: Write the failing test**

Create `/home/subaru/projects/virtual-company/tests/test_browser_relay.py`:
```python
"""Tests for the /ws/browser-relay WebSocket endpoint."""
import json
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from app.main import app


def test_browser_relay_endpoint_exists():
    """Verify /ws/browser-relay accepts connections without error."""
    broadcast_calls = []

    async def fake_broadcast(data):
        broadcast_calls.append(data)

    with patch("app.api.websocket.broadcast_event", new=fake_broadcast):
        with TestClient(app) as client:
            with client.websocket_connect("/ws/browser-relay") as ws:
                ws.send_json({
                    "type": "browser_frame",
                    "slot": 1,
                    "frame": "base64data",
                    "url": "https://linkedin.com",
                    "action": "Filling Name",
                })
                # Give the relay endpoint a moment to process
                # TestClient is synchronous so we just verify no exception was raised


def test_browser_relay_ignores_invalid_json():
    """Relay endpoint should not crash on malformed messages."""
    with TestClient(app) as client:
        with client.websocket_connect("/ws/browser-relay") as ws:
            ws.send_text("not-valid-json{{{")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/subaru/projects/virtual-company
python -m pytest tests/test_browser_relay.py -v
```
Expected: `WebSocketDisconnect` or connection refused — `/ws/browser-relay` doesn't exist yet.

- [ ] **Step 3: Add /ws/browser-relay to main.py**

Edit `/home/subaru/projects/virtual-company/app/main.py`.

After the existing `/ws` endpoint (line 72), insert:

```python
@app.websocket("/ws/browser-relay")
async def browser_relay_endpoint(ws: WebSocket):
    """Receives browser_frame events from browser-svc and broadcasts to all frontend sessions."""
    from app.api.websocket import broadcast_event
    await ws.accept()
    try:
        while True:
            try:
                data = await ws.receive_json()
            except Exception:
                break
            await broadcast_event(data)
    except Exception:
        pass
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/subaru/projects/virtual-company
python -m pytest tests/test_browser_relay.py -v
```
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/main.py tests/test_browser_relay.py
git commit -m "feat(nexus): /ws/browser-relay endpoint — browser-svc frame relay to frontend"
```

---

## Task 11: Browser Board UI

**Files:**
- Modify: `app/static/index.html` — add `island-board` island + Maya pill button
- Modify: `app/static/style-v5.css` — add `.island-board` sizing
- Modify: `app/static/app-v5.js` — `handleBrowserFrame`, `initBrowserBoard`, WS case, apply log

- [ ] **Step 1: Add CSS for island-board**

Edit `/home/subaru/projects/virtual-company/app/static/style-v5.css`.

Find the line `.island-browser { width: 420px; height: 380px; }` (around line 209) and append after it:

```css
.island-board   { top: 80px; right: 16px; width: 740px; height: 510px; }
```

- [ ] **Step 2: Add Maya pill button and island-board to index.html**

Edit `/home/subaru/projects/virtual-company/app/static/index.html`.

**2a.** Find the pill buttons area in the header (look for other `pill pill-icon` buttons). Add the Maya pill alongside them:

```html
<button class="pill pill-icon" id="browser-board-btn" title="Browser Board (Maya)" onclick="showIsland('board')">🤖</button>
```

**2b.** Find `</body>` and insert the Browser Board island and Profile Modal just before it:

```html
<!-- Browser Board island — live view of all 5 Maya browser slots -->
<div class="island island-board" id="island-board" style="display:none">
  <div class="island-header" id="island-board-header">
    Browser Board — Maya
    <div style="display:flex;gap:8px;align-items:center">
      <button id="profile-btn" onclick="toggleProfileModal()"
        style="background:rgba(0,255,136,0.1);border:1px solid #00ff88;color:#00ff88;padding:2px 10px;border-radius:4px;font-size:11px;cursor:pointer">
        Profile
      </button>
      <button onclick="hideIsland('board')" style="background:none;border:none;color:var(--muted);cursor:pointer;font-size:16px">✕</button>
    </div>
  </div>
  <div class="browser-board-grid" id="browser-board-grid"></div>
</div>

<!-- Applicant Profile Modal -->
<div id="profile-modal"
  style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:2000;align-items:center;justify-content:center">
  <div style="background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:24px;width:480px;max-height:80vh;overflow-y:auto">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <span style="color:#00ff88;font-weight:600">Applicant Profile</span>
      <button onclick="closeProfileModal()"
        style="background:none;border:none;color:var(--muted);cursor:pointer;font-size:18px">✕</button>
    </div>
    <div id="profile-form-fields"></div>
    <div style="display:flex;gap:8px;margin-top:16px;justify-content:flex-end">
      <button onclick="closeProfileModal()"
        style="background:none;border:1px solid var(--border);color:var(--muted);padding:6px 16px;border-radius:6px;cursor:pointer">
        Cancel
      </button>
      <button onclick="saveProfile()"
        style="background:#00ff88;color:#000;padding:6px 16px;border-radius:6px;cursor:pointer;font-weight:600">
        Save
      </button>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Add Browser Board JS to app-v5.js**

Edit `/home/subaru/projects/virtual-company/app/static/app-v5.js`.

**3a.** Find the WebSocket message switch-case block. Locate the last `case` before the default/closing. Add after `case "browser_navigated":` (or after the last existing case):

```javascript
      case "browser_frame":
        handleBrowserFrame(obj);
        break;

      case "apply_result":
        logApplyResult(obj);
        break;
```

**3b.** Append the following functions at the end of the file (before the final `}`  closing the module, or simply at the end of the file):

```javascript
// ── Browser Board ─────────────────────────────────────────────────────────────
const _SLOT_LABELS = ["Overleaf (CV)", "Slot 1", "Slot 2", "Slot 3", "Slot 4"];
const _boardTiles = {};

function initBrowserBoard() {
  const grid = document.getElementById("browser-board-grid");
  if (!grid || Object.keys(_boardTiles).length > 0) return;
  grid.style.cssText =
    "display:grid;grid-template-columns:repeat(3,1fr);gap:6px;padding:8px;height:calc(100% - 36px);box-sizing:border-box";

  for (let i = 0; i < 5; i++) {
    const tile = document.createElement("div");
    tile.style.cssText =
      "position:relative;background:#0d1117;border:1px solid var(--border);border-radius:6px;overflow:hidden";
    tile.innerHTML =
      `<img id="bframe-${i}" src="" style="width:100%;height:100%;object-fit:cover;display:none">` +
      `<div id="bidle-${i}" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:4px">` +
        `<span style="color:var(--muted);font-size:11px">${_SLOT_LABELS[i]}</span>` +
        `<span style="color:var(--border);font-size:9px">idle</span>` +
      `</div>` +
      `<div id="bstatus-${i}" style="position:absolute;bottom:0;left:0;right:0;padding:3px 6px;background:rgba(0,0,0,0.75);font-size:9px;color:#00d4ff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:none"></div>` +
      `<div id="bbadge-${i}" style="position:absolute;top:4px;right:4px;padding:1px 5px;border-radius:3px;font-size:8px;font-weight:700;background:rgba(0,255,128,0.15);color:#0f0;display:none">LIVE</div>`;
    grid.appendChild(tile);
    _boardTiles[i] = {
      img: document.getElementById(`bframe-${i}`),
      idle: document.getElementById(`bidle-${i}`),
      status: document.getElementById(`bstatus-${i}`),
      badge: document.getElementById(`bbadge-${i}`),
    };
  }

  // Log tile
  const logTile = document.createElement("div");
  logTile.style.cssText =
    "background:#0d1117;border:1px solid var(--border);border-radius:6px;padding:8px;overflow-y:auto";
  logTile.innerHTML =
    `<div style="font-size:10px;color:#00ff88;margin-bottom:4px;font-weight:600">Apply Log</div>` +
    `<div id="board-log" style="font-size:9px;color:var(--muted);display:flex;flex-direction:column;gap:3px"></div>`;
  grid.appendChild(logTile);
}

function handleBrowserFrame(obj) {
  const boardEl = document.getElementById("island-board");
  if (!boardEl) return;
  initBrowserBoard();
  const slot = obj.slot != null ? obj.slot : 0;
  const tile = _boardTiles[slot];
  if (!tile) return;
  if (obj.frame) {
    tile.img.src = "data:image/jpeg;base64," + obj.frame;
    tile.img.style.display = "block";
    tile.idle.style.display = "none";
    tile.badge.style.display = "block";
  }
  const label = (obj.action ? obj.action + (obj.url ? "  —  " + obj.url : "") : obj.url) || "";
  if (label) {
    tile.status.textContent = label;
    tile.status.style.display = "block";
  }
}

function logApplyResult(obj) {
  const log = document.getElementById("board-log");
  if (!log) return;
  const icon = obj.status === "applied" ? "✓" : obj.status === "captcha" ? "⚠" : "✕";
  const color = obj.status === "applied" ? "#0f0" : obj.status === "captcha" ? "#fa0" : "#f55";
  const entry = document.createElement("div");
  entry.style.color = color;
  entry.textContent = `${icon} ${obj.company || "?"} — ${obj.role || "?"}: ${obj.status}`;
  log.insertBefore(entry, log.firstChild);
  if (log.children.length > 30) log.removeChild(log.lastChild);
}

// ── Profile Modal ─────────────────────────────────────────────────────────────
let _profileData = {};
const _BROWSER_SVC = "http://127.0.0.1:9002";

async function toggleProfileModal() {
  const modal = document.getElementById("profile-modal");
  if (modal.style.display !== "none") { closeProfileModal(); return; }
  try {
    const r = await fetch(`${_BROWSER_SVC}/profile`);
    _profileData = await r.json();
    renderProfileForm(_profileData);
    modal.style.display = "flex";
  } catch (e) {
    alert("browser-svc unreachable — is Docker running?");
  }
}

function closeProfileModal() {
  document.getElementById("profile-modal").style.display = "none";
}

function renderProfileForm(data) {
  const simple = ["name", "email", "phone", "linkedin", "notice_period", "location_preference"];
  const labels = {
    name: "Full Name", email: "Email", phone: "Phone",
    linkedin: "LinkedIn URL", notice_period: "Notice Period", location_preference: "Location",
  };
  const fields = document.getElementById("profile-form-fields");
  fields.innerHTML =
    simple.map(k =>
      `<div style="margin-bottom:10px">` +
        `<label style="font-size:11px;color:var(--muted);display:block;margin-bottom:3px">${labels[k]}</label>` +
        `<input id="pf-${k}" value="${(data[k] || "").replace(/"/g, "&quot;")}"` +
          ` style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:6px 8px;border-radius:4px;font-size:13px;box-sizing:border-box">` +
      `</div>`
    ).join("") +
    `<div style="margin-bottom:10px">` +
      `<label style="font-size:11px;color:var(--muted);display:block;margin-bottom:3px">Experience (years)</label>` +
      `<input id="pf-experience_years" type="number" value="${data.experience_years || 0}"` +
        ` style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:6px 8px;border-radius:4px;font-size:13px;box-sizing:border-box">` +
    `</div>` +
    `<div style="margin-bottom:10px">` +
      `<label style="font-size:11px;color:var(--muted);display:block;margin-bottom:3px">Target Roles (comma-separated)</label>` +
      `<input id="pf-target_roles" value="${(data.target_roles || []).join(", ")}"` +
        ` style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:6px 8px;border-radius:4px;font-size:13px;box-sizing:border-box">` +
    `</div>` +
    `<div style="margin-bottom:10px">` +
      `<label style="font-size:11px;color:var(--muted);display:block;margin-bottom:3px">Target Companies (comma-separated)</label>` +
      `<input id="pf-target_companies" value="${(data.target_companies || []).join(", ")}"` +
        ` style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:6px 8px;border-radius:4px;font-size:13px;box-sizing:border-box">` +
    `</div>` +
    `<div>` +
      `<label style="font-size:11px;color:var(--muted);display:block;margin-bottom:3px">Skills (comma-separated)</label>` +
      `<input id="pf-skills" value="${(data.skills || []).join(", ")}"` +
        ` style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:6px 8px;border-radius:4px;font-size:13px;box-sizing:border-box">` +
    `</div>`;
}

async function saveProfile() {
  const simple = ["name", "email", "phone", "linkedin", "notice_period", "location_preference"];
  const payload = {};
  for (const k of simple) {
    const el = document.getElementById(`pf-${k}`);
    if (el) payload[k] = el.value;
  }
  const expEl = document.getElementById("pf-experience_years");
  if (expEl) payload.experience_years = parseInt(expEl.value) || 0;
  const toList = id => {
    const el = document.getElementById(id);
    return el ? el.value.split(",").map(s => s.trim()).filter(Boolean) : [];
  };
  payload.target_roles = toList("pf-target_roles");
  payload.target_companies = toList("pf-target_companies");
  payload.skills = toList("pf-skills");
  try {
    const r = await fetch(`${_BROWSER_SVC}/profile`, {
      method: "PATCH",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    if (r.ok) { closeProfileModal(); }
    else { alert("Failed to save profile — check browser-svc logs"); }
  } catch (e) {
    alert("browser-svc unreachable");
  }
}
```

- [ ] **Step 4: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/static/index.html app/static/app-v5.js app/static/style-v5.css
git commit -m "feat(ui): Browser Board island — live 5-slot grid, apply log, profile modal"
```

---

## Task 12: docker-compose.yml

**Files:**
- Modify: `docker-compose.yml` — add `browser-svc` service

- [ ] **Step 1: Verify existing compose structure**

```bash
cat /mnt/HC_Volume_105874680/virtual-company/docker-compose.yml
```
Expected: two services (`virtual-company` and `bark-svc`).

- [ ] **Step 2: Add browser-svc service and update virtual-company**

Edit `/mnt/HC_Volume_105874680/virtual-company/docker-compose.yml`.

**2a.** Add `browser-svc` to the `depends_on` block of the `virtual-company` service:

Find:
```yaml
    depends_on:
      bark-svc:
        condition: service_started
```
Replace with:
```yaml
    depends_on:
      bark-svc:
        condition: service_started
      browser-svc:
        condition: service_started
```

**2b.** Add `BROWSER_SVC_URL` to the `virtual-company` environment block:

Find `- BARK_SVC_URL=http://bark-svc:9001` and add after it:
```yaml
      - BROWSER_SVC_URL=http://browser-svc:9002
```

**2c.** Append the complete `browser-svc` service at the end of the file:

```yaml
  browser-svc:
    build: ./browser-svc
    container_name: browser-svc
    restart: unless-stopped
    env_file: .env
    ports:
      - "9002:9002"
    volumes:
      - /mnt/HC_Volume_105874680/virtual-company/browser-svc/browser_profile.json:/app/browser_profile.json
      - /mnt/HC_Volume_105874680/virtual-company/browser-svc/cv_exports:/app/cv_exports
      # Place cv_default.pdf next to docker-compose.yml
      - /mnt/HC_Volume_105874680/virtual-company/cv_default.pdf:/app/cv_default.pdf:ro
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - OVERLEAF_EMAIL=${OVERLEAF_EMAIL:-}
      - OVERLEAF_PASSWORD=${OVERLEAF_PASSWORD:-}
      - OVERLEAF_PROJECT_URL=${OVERLEAF_PROJECT_URL:-}
      - NEXUS_WS_URL=ws://virtual-company:3030/ws/browser-relay
    healthcheck:
      test: ["CMD", "curl", "-f", "http://127.0.0.1:9002/health"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 30s
```

- [ ] **Step 3: Validate compose file syntax**

```bash
cd /mnt/HC_Volume_105874680/virtual-company
docker compose config --quiet && echo "VALID" || echo "INVALID"
```
Expected: `VALID`

- [ ] **Step 4: Add cv_default.pdf placeholder**

The volume mount expects a PDF at `browser-svc/cv_default.pdf`. Create a note file if the user hasn't provided one yet:

```bash
if [ ! -f /mnt/HC_Volume_105874680/virtual-company/cv_default.pdf ]; then
  echo "Place your default CV PDF here as cv_default.pdf" > /mnt/HC_Volume_105874680/virtual-company/cv_default.pdf.README.txt
  echo "REMINDER: add cv_default.pdf to the virtual-company directory before building"
fi
```

- [ ] **Step 5: Build and smoke test**

```bash
cd /mnt/HC_Volume_105874680/virtual-company
docker compose build browser-svc
docker compose up -d browser-svc
sleep 10
curl -sf http://127.0.0.1:9002/health
```
Expected:
```json
{"status":"ok","slots":5}
```

- [ ] **Step 6: Restart full stack and verify**

```bash
cd /mnt/HC_Volume_105874680/virtual-company
docker compose down && docker compose up -d
sleep 15
curl -sf http://127.0.0.1:9002/health
curl -sf http://127.0.0.1:3031/api/capabilities | python3 -c "import sys,json; d=json.load(sys.stdin); print('maya' in str(d) or 'browser' in str(d))"
```
Expected: `{"status":"ok","slots":5}` and `True` (Maya appears in capabilities).

- [ ] **Step 7: Commit**

```bash
cd /mnt/HC_Volume_105874680/virtual-company
git add docker-compose.yml
git commit -m "feat(infra): add browser-svc to docker-compose — port 9002, Playwright, Chromium"
```

---

## Task 13: End-to-end verification

**Files:** No new files — verification only.

- [ ] **Step 1: Run all NEXUS tests**

```bash
cd /home/subaru/projects/virtual-company
python -m pytest tests/ -v --tb=short
```
Expected: all tests pass including `test_maya_agent.py` and `test_browser_relay.py`.

- [ ] **Step 2: Run all browser-svc tests**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/browser-svc
python -m pytest tests/ -v --tb=short
```
Expected: all tests pass.

- [ ] **Step 3: Verify Maya appears in NEXUS UI**

Open `http://127.0.0.1:3031` in a browser.
- Maya (green `MA` avatar) should appear in the agent list.
- A `🤖` pill button should appear in the header — clicking it opens the Browser Board island.
- The Browser Board shows 5 idle tiles + 1 log tile.
- Clicking "Profile" opens the profile modal with fields pre-filled from `browser_profile.json`.

- [ ] **Step 4: Verify CEO delegation reaches browser-svc**

In the NEXUS chat, send to CEO:
```
Ask Maya to check status of browser slots
```
Expected: CEO delegates to Maya (`[DELEGATE:browser]`). Maya responds after receiving the reply from browser-svc. The NEXUS work queue shows a Maya task completing.

- [ ] **Step 5: Verify live streaming smoke test**

```bash
# From host, trigger a slot manually
curl -sf -X POST http://127.0.0.1:9002/apply \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "slot_id": 1, "use_overleaf": false}'
```
Expected: `{"queued":true,"slot_id":1,"url":"https://example.com"}`

Open the Browser Board in the UI — Slot 1 tile should show a live JPEG from `example.com` within a few seconds.

---

## Self-Review Checklist

**Spec coverage:**
- ✓ Separate `browser-svc` Docker service (Task 12)
- ✓ 5 browser slots, Slot 0 = Overleaf, Slots 1–4 = applications (Task 2)
- ✓ CDP Screencast live frames at ~10fps (Task 2 + 3)
- ✓ WebSocket relay to NEXUS (Task 3 + 10)
- ✓ Browser Board 2×3 grid island (Task 11)
- ✓ CV tailoring via Claude API (Task 5)
- ✓ Overleaf pipeline: login, edit, compile, download (Task 6)
- ✓ cv_default.pdf fallback on Overleaf failure (Task 6)
- ✓ Best-effort stealth: playwright-stealth, UA rotation, bezier mouse (Task 4)
- ✓ Targeted apply mode `[BROWSER_APPLY:]` (Task 7 + 9)
- ✓ Discovery mode `[BROWSER_DISCOVER:]` (Task 7 + 9)
- ✓ Direct company careers mode `[BROWSER_COMPANY:]` (Task 7 + 9)
- ✓ Profile-matched discovery `[BROWSER_PROFILE_MATCH]` (Task 7 + 8 + 9)
- ✓ Editable `browser_profile.json` via Profile Modal (Task 11 + 8)
- ✓ Maya agent key `"browser"` for `[DELEGATE:browser]` routing (Task 9)
- ✓ `BROWSER_SVC_URL` env var following `BARK_SVC_URL` pattern (Task 9)
- ✓ All files inside virtual-company directory (confirmed throughout)

**Type consistency check:**
- `SlotInfo` used in `session_manager.py`, referenced as `slot_info: Optional[SlotInfo]` in `overleaf_pipeline.py` and `job_workflow.py` — consistent via `TYPE_CHECKING` import.
- `CVEdit.edits: list[dict[str, str]]` in `cv_enhancer.py`, consumed by `apply_edits(latex, cv_edit.edits)` — consistent.
- `apply_to_job(page, url, cv_path, slot_info, overleaf_page)` called from `_run_apply()` in `main.py` — signature matches.
- `call_browser_svc(tool_type, tool_args)` returns `str` — used as `result` in `_execute_tool` which also expects `str` — consistent.
- `broadcast_event(data: dict)` in `websocket.py` — called with `data` in `browser_relay_endpoint` — consistent.
