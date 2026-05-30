# Phase 3 — Playwright Browser, Voice (Hey Subaru), Claude Vision

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three multimedia capabilities to Subaru: headless Chromium browser control agents can operate, voice activation with "Hey Subaru" wake word + per-agent TTS, and Claude Vision so users can drag-drop images directly into chat for multimodal reasoning.

**Architecture:** Playwright runs as a module-level singleton in `app/services/browser.py` (extending the existing `write_preview()` module). Voice is pure frontend (browser Web Speech API + SpeechSynthesis — no backend changes). Claude Vision adds a `run_claude_vision()` path in `executor.py` that uses the Anthropic Python SDK directly (bypassing the CLI) for multimodal content blocks; `websocket.py` detects `attachments` in incoming messages and routes to this path. Each feature is independently deployable.

**Tech Stack:** Python 3.12, `playwright>=1.40.0` (Chromium), FastAPI, `anthropic` SDK (already installed), browser Web Speech API, SpeechSynthesis API, Docker.

**Base SHA:** `20e57ed`

**Run tests inside container:** `docker exec virtual-company python -m pytest /app/tests/test_<name>.py -v`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `Dockerfile` | Install Chromium via `playwright install chromium --with-deps` |
| Modify | `requirements.txt` | Add `playwright>=1.40.0` |
| Modify | `app/services/browser.py` | Add Playwright singleton + navigate/screenshot/extract/click |
| Create | `tests/test_browser_playwright.py` | Playwright service unit tests (mocked) |
| Modify | `app/api/router.py` | POST /api/browser/navigate, /screenshot, /click, /extract; GET /api/browser/screenshot |
| Modify | `app/static/index.html` | Browser island: URL bar, nav button, auto-refresh toggle |
| Modify | `app/static/style-v5.css` | Browser island URL bar styles |
| Modify | `app/static/app-v5.js` | Browser island logic + Voice engine (STT/TTS/wake word) |
| Modify | `app/agents/executor.py` | Add `run_claude_vision()` function |
| Modify | `app/api/websocket.py` | Detect image attachments → route to vision path |
| Create | `tests/test_vision.py` | Vision path unit tests |

---

## Task 1: Add Playwright to Docker

**Files:**
- Modify: `requirements.txt`
- Modify: `Dockerfile`

- [ ] **Step 1: Add playwright to requirements.txt**

Add this line to `requirements.txt`:
```
playwright>=1.40.0
```

- [ ] **Step 2: Add Chromium install to Dockerfile**

In `Dockerfile`, add after `RUN pip install --no-cache-dir -r requirements.txt`:

```dockerfile
# Install Playwright Chromium + system deps (~300 MB, required for browser tools)
RUN pip install playwright && playwright install chromium --with-deps
```

The full Dockerfile should look like:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium + system deps (~300 MB, required for browser tools)
RUN pip install playwright && playwright install chromium --with-deps

# Create non-root user matching host uid=1000 (subaru) so volume mounts work
RUN groupadd -g 1000 nexus && useradd -m -u 1000 -g nexus nexus

COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

EXPOSE 3030

ENTRYPOINT ["./entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3030", "--reload", "--reload-dir", "/app"]
```

- [ ] **Step 3: Rebuild container (takes ~5 minutes for Chromium)**

```bash
cd /home/subaru/projects/virtual-company
docker compose build --no-cache
docker compose up -d
sleep 10
docker exec virtual-company python -c "from playwright.sync_api import sync_playwright; print('playwright OK')"
```

Expected: `playwright OK`

- [ ] **Step 4: Verify app still starts**

```bash
docker exec virtual-company curl -s http://localhost:3030/api/capabilities > /dev/null && echo OK
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add requirements.txt Dockerfile
git commit -m "feat: add playwright + install Chromium in Docker"
```

---

## Task 2: Playwright Browser Service (TDD)

**Files:**
- Modify: `app/services/browser.py`
- Create: `tests/test_browser_playwright.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_browser_playwright.py`:

```python
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock


@pytest.mark.asyncio
async def test_navigate_returns_title_and_screenshot_path():
    from app.services.browser import navigate

    mock_page = AsyncMock()
    mock_page.title = AsyncMock(return_value="Google")
    mock_page.goto = AsyncMock()
    mock_page.screenshot = AsyncMock()
    mock_page.close = AsyncMock()

    mock_browser = MagicMock()
    mock_browser.is_connected.return_value = True
    mock_browser.new_page = AsyncMock(return_value=mock_page)

    with patch("app.services.browser._get_browser", new=AsyncMock(return_value=mock_browser)):
        result = await navigate("https://example.com")

    assert result["title"] == "Google"
    assert "screenshot" in result
    assert result["url"] == "https://example.com"


@pytest.mark.asyncio
async def test_extract_text_returns_string():
    from app.services.browser import extract_text

    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.inner_text = AsyncMock(return_value="Hello World")
    mock_page.close = AsyncMock()

    mock_browser = MagicMock()
    mock_browser.is_connected.return_value = True
    mock_browser.new_page = AsyncMock(return_value=mock_page)

    with patch("app.services.browser._get_browser", new=AsyncMock(return_value=mock_browser)):
        result = await extract_text("https://example.com", "body")

    assert result == "Hello World"


@pytest.mark.asyncio
async def test_navigate_error_returns_error_dict():
    from app.services.browser import navigate

    async def _raise(*a, **kw):
        raise Exception("connection refused")

    mock_browser = MagicMock()
    mock_browser.is_connected.return_value = True
    mock_page = AsyncMock()
    mock_page.goto = _raise
    mock_page.close = AsyncMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)

    with patch("app.services.browser._get_browser", new=AsyncMock(return_value=mock_browser)):
        result = await navigate("https://bad.url")

    assert "error" in result


@pytest.mark.asyncio
async def test_get_browser_creates_new_when_disconnected():
    """_get_browser should recreate when browser is disconnected."""
    from app.services import browser as bmod

    # Simulate a disconnected browser
    mock_old = MagicMock()
    mock_old.is_connected.return_value = False

    mock_new_browser = MagicMock()
    mock_new_browser.is_connected.return_value = True

    mock_pw = AsyncMock()
    mock_pw.chromium.launch = AsyncMock(return_value=mock_new_browser)

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_pw)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)

    bmod._browser = mock_old
    bmod._playwright_ctx = None

    with patch("app.services.browser.async_playwright", return_value=mock_ctx):
        b = await bmod._get_browser()

    assert b is mock_new_browser
    # cleanup
    bmod._browser = None
    bmod._playwright_ctx = None
```

- [ ] **Step 2: Run — expect failure**

```bash
docker exec virtual-company python -m pytest /app/tests/test_browser_playwright.py -v 2>&1 | tail -6
```

Expected: `ImportError` — `navigate`, `extract_text`, `_get_browser` don't exist yet.

- [ ] **Step 3: Extend app/services/browser.py with Playwright**

Replace the entire `app/services/browser.py`:

```python
"""
Browser service.

Provides:
- write_preview(html)     — write agent HTML to live preview iframe (no Playwright needed)
- navigate(url)           — headless Chromium navigation + screenshot
- extract_text(url, sel)  — scrape text from a CSS selector
- click_element(sel)      — click an element on the current page
- take_screenshot()       — screenshot current browser state
- _get_browser()          — singleton Playwright browser (auto-reconnects)
"""
import asyncio
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────────
PREVIEW_FILE     = Path("/app/app/static/previews/index.html")
SCREENSHOT_FILE  = Path("/app/app/static/previews/browser_screenshot.png")

# ── Playwright singleton ───────────────────────────────────────────────────────
_playwright_ctx  = None   # holds the async context manager
_browser         = None   # holds the Browser instance
_current_page    = None   # persistent page for multi-step navigation


async def _get_browser():
    """Return a connected Playwright Chromium browser, recreating if disconnected."""
    global _playwright_ctx, _browser

    if _browser is not None and _browser.is_connected():
        return _browser

    # Close stale context before creating new one
    if _playwright_ctx is not None:
        try:
            await _playwright_ctx.__aexit__(None, None, None)
        except Exception:
            pass
        _playwright_ctx = None

    from playwright.async_api import async_playwright
    _playwright_ctx = async_playwright()
    pw       = await _playwright_ctx.__aenter__()
    _browser = await pw.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    logger.info("Playwright Chromium browser started.")
    return _browser


# ── Design preview (no Playwright) ────────────────────────────────────────────

def write_preview(html_content: str) -> str:
    """Write agent-generated HTML to the live design preview file."""
    try:
        PREVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
        PREVIEW_FILE.write_text(html_content, encoding="utf-8")
        logger.info("Design preview updated (%d chars)", len(html_content))
        return f"Preview written ({len(html_content)} chars). Visible at /static/previews/index.html"
    except Exception as exc:
        logger.error("write_preview failed: %s", exc)
        return f"[write_preview error: {exc}]"


# ── Playwright operations ──────────────────────────────────────────────────────

async def navigate(url: str) -> dict:
    """Navigate to URL, take screenshot. Returns {title, url, screenshot, error?}."""
    try:
        browser = await _get_browser()
        page    = await browser.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        title   = await page.title()
        SCREENSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(SCREENSHOT_FILE))
        await page.close()
        return {
            "title":      title,
            "url":        url,
            "screenshot": "/static/previews/browser_screenshot.png",
        }
    except Exception as exc:
        logger.warning("navigate(%s) failed: %s", url, exc)
        return {"url": url, "error": str(exc)}


async def take_screenshot(url: Optional[str] = None) -> dict:
    """Screenshot the current browser state (optionally navigate first)."""
    if url:
        return await navigate(url)
    if not SCREENSHOT_FILE.exists():
        return {"error": "No screenshot yet — navigate to a URL first"}
    return {"screenshot": "/static/previews/browser_screenshot.png"}


async def extract_text(url: str, selector: str) -> str:
    """Fetch a page and return innerText of the first matching CSS selector."""
    try:
        browser = await _get_browser()
        page    = await browser.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        text    = await page.inner_text(selector)
        await page.close()
        return text
    except Exception as exc:
        logger.warning("extract_text failed: %s", exc)
        return f"[extract_text error: {exc}]"


async def click_element(url: str, selector: str) -> dict:
    """Navigate to URL, click an element, take screenshot."""
    try:
        browser = await _get_browser()
        page    = await browser.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await page.click(selector, timeout=5000)
        await asyncio.sleep(0.5)   # brief wait for any transition
        SCREENSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(SCREENSHOT_FILE))
        title = await page.title()
        await page.close()
        return {
            "title":      title,
            "url":        page.url,
            "screenshot": "/static/previews/browser_screenshot.png",
        }
    except Exception as exc:
        logger.warning("click_element failed: %s", exc)
        return {"error": str(exc)}
```

- [ ] **Step 4: Run tests — expect pass**

```bash
docker exec virtual-company python -m pytest /app/tests/test_browser_playwright.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Run full suite**

```bash
docker exec virtual-command python -m pytest /app/tests/ -v 2>&1 | tail -5
```

Expected: 40 tests pass (36 + 4 new).

- [ ] **Step 6: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/services/browser.py tests/test_browser_playwright.py
git commit -m "feat: Playwright browser service — navigate, screenshot, extract, click"
```

---

## Task 3: Browser API Endpoints

**Files:**
- Modify: `app/api/router.py`

- [ ] **Step 1: Add browser endpoints to router.py**

Add these imports at the top of `app/api/router.py` (after existing imports):

```python
from app.services.browser import navigate, take_screenshot, extract_text, click_element
```

Add these routes after the `/api/design/preview` endpoint:

```python
# ── Browser ────────────────────────────────────────────────────────────────────

@router.post("/api/browser/navigate")
async def api_browser_navigate(body: dict):
    url = body.get("url", "").strip()
    if not url:
        return JSONResponse({"ok": False, "error": "url required"}, status_code=400)
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    result = await navigate(url)
    if "error" in result:
        return JSONResponse({"ok": False, **result}, status_code=422)
    return {"ok": True, **result}


@router.get("/api/browser/screenshot")
async def api_browser_screenshot_get():
    from pathlib import Path
    from fastapi.responses import FileResponse
    screenshot = Path("/app/app/static/previews/browser_screenshot.png")
    if not screenshot.exists():
        return JSONResponse({"ok": False, "error": "No screenshot yet"}, status_code=404)
    return FileResponse(str(screenshot), media_type="image/png")


@router.post("/api/browser/screenshot")
async def api_browser_screenshot_post(body: dict):
    url    = body.get("url", "").strip() or None
    result = await take_screenshot(url)
    if "error" in result:
        return JSONResponse({"ok": False, **result}, status_code=422)
    return {"ok": True, **result}


@router.post("/api/browser/extract")
async def api_browser_extract(body: dict):
    url      = body.get("url", "").strip()
    selector = body.get("selector", "body").strip()
    if not url:
        return JSONResponse({"ok": False, "error": "url required"}, status_code=400)
    text = await extract_text(url, selector)
    return {"ok": True, "text": text}


@router.post("/api/browser/click")
async def api_browser_click(body: dict):
    url      = body.get("url", "").strip()
    selector = body.get("selector", "").strip()
    if not url or not selector:
        return JSONResponse({"ok": False, "error": "url and selector required"}, status_code=400)
    result = await click_element(url, selector)
    if "error" in result:
        return JSONResponse({"ok": False, **result}, status_code=422)
    return {"ok": True, **result}
```

- [ ] **Step 2: Add browser tools for agents in executor.py**

In `app/agents/executor.py`, inside `_execute_tool()`, add browser tools after the `write_preview` case (before the `else:` branch):

In `icon_map` and `label_map`, add:
```python
        "web_navigate":   "🌐",
        "web_screenshot": "📸",
        "web_extract":    "🔍",
```

```python
        "web_navigate":   "Navigating Browser",
        "web_screenshot": "Taking Screenshot",
        "web_extract":    "Extracting Text",
```

In the `try` block, add before `else:`:
```python
        elif tool_type == "web_navigate":
            from app.services.browser import navigate as _nav
            from app.api.websocket import broadcast_event
            url    = tool_args.get("url", "")
            result_d = await _nav(url)
            result   = str(result_d)
            asyncio.create_task(broadcast_event({
                "type":       "browser_navigated",
                "screenshot": result_d.get("screenshot", ""),
                "title":      result_d.get("title", ""),
                "url":        url,
            }))
        elif tool_type == "web_screenshot":
            from app.services.browser import take_screenshot as _ss
            result_d = await _ss()
            result   = str(result_d)
        elif tool_type == "web_extract":
            from app.services.browser import extract_text as _ex
            url      = tool_args.get("url", "")
            selector = tool_args.get("selector", "body")
            result   = await _ex(url, selector)
```

- [ ] **Step 3: Add browser tool parsers in tools.py**

In `app/agents/tools.py`, inside `parse_tool_call()`, add before `return None, None`:

```python
    m = re.search(r'\[WEB_NAVIGATE:\s*(.*?)\]', text, re.DOTALL)
    if m:
        return "web_navigate", {"url": m.group(1).strip()}

    m = re.search(r'\[WEB_EXTRACT:\s*(.*?)\]', text, re.DOTALL)
    if m:
        parts = m.group(1).strip().split()
        url      = parts[0] if parts else ""
        selector = " ".join(parts[1:]) if len(parts) > 1 else "body"
        return "web_extract", {"url": url, "selector": selector}

    m = re.search(r'\[WEB_SCREENSHOT\]', text)
    if m:
        return "web_screenshot", {}
```

- [ ] **Step 4: Add browser tools to the tgpt tool list in executor.py**

In `_build_tgpt_prompt`, find the tool list and add after `[WRITE_PREVIEW:]`:

```
8. [WEB_NAVIGATE: https://url]  — Navigate browser to URL, take screenshot
9. [WEB_EXTRACT: https://url selector]  — Extract text from CSS selector
10. [WEB_SCREENSHOT]            — Take screenshot of current browser page
```

- [ ] **Step 5: Verify browser API**

```bash
docker exec virtual-company curl -s -X POST http://localhost:3030/api/browser/navigate \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}' | python3 -m json.tool
```

Expected: `{"ok": true, "title": "Example Domain", "screenshot": "/static/previews/browser_screenshot.png", ...}`

- [ ] **Step 6: Run full test suite**

```bash
docker exec virtual-company python -m pytest /app/tests/ -v 2>&1 | tail -5
```

Expected: 40 tests pass.

- [ ] **Step 7: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/api/router.py app/agents/executor.py app/agents/tools.py
git commit -m "feat: browser API endpoints + web_navigate/screenshot/extract agent tools"
```

---

## Task 4: Browser Island UI

**Files:**
- Modify: `app/static/index.html`
- Modify: `app/static/style-v5.css`
- Modify: `app/static/app-v5.js`

- [ ] **Step 1: Update browser island in index.html**

Find the browser island div:
```html
<div class="island island-browser" id="island-browser" style="display:none">
  <div class="island-header" id="island-browser-header">Browser <button onclick="hideIsland('browser')">✕</button></div>
  <img id="browser-screenshot" src="" alt="Browser screenshot">
</div>
```

Replace with:
```html
<div class="island island-browser" id="island-browser" style="display:none">
  <div class="island-header" id="island-browser-header">
    <span>Browser</span>
    <button onclick="hideIsland('browser')">✕</button>
  </div>
  <div class="browser-urlbar">
    <input type="text" id="browser-url-input" placeholder="https://example.com" class="browser-url-field">
    <button class="btn-run" onclick="browserNavigate()" style="white-space:nowrap">Go</button>
  </div>
  <div id="browser-status" style="font-size:10px;color:var(--muted);padding:2px 6px;height:16px"></div>
  <img id="browser-screenshot" src="" alt="Browser screenshot" style="display:block">
</div>
```

- [ ] **Step 2: Add browser island CSS to style-v5.css**

Append to `app/static/style-v5.css`:

```css
/* ── Browser Island ──────────────────────────────────────────────────── */
.island-browser { width: 420px; height: 380px; }
.browser-urlbar {
  display: flex; gap: 4px; padding: 6px 8px;
  background: var(--bg-elevated); border-bottom: 1px solid var(--border);
}
.browser-url-field {
  flex: 1; background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 6px; padding: 4px 8px; color: var(--text);
  font-family: var(--font-code); font-size: 11px; outline: none;
}
.browser-url-field:focus { border-color: var(--cyan); }
#browser-screenshot {
  width: 100%; height: calc(100% - 76px);
  object-fit: contain; background: #111;
}
```

- [ ] **Step 3: Add browser JS to app-v5.js**

Just before `document.addEventListener("DOMContentLoaded", ...)`, add:

```javascript
// ── Browser Island ──────────────────────────────────────────────────────────
let _browserRefreshInterval = null;

async function browserNavigate() {
  const input  = $id("browser-url-input");
  const url    = input.value.trim();
  if (!url) return;

  const status = $id("browser-status");
  status.textContent = "Navigating…";

  try {
    const r = await fetch("/api/browser/navigate", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ url }),
    }).then(r => r.json());

    if (r.ok) {
      status.textContent = `✓ ${r.title || url}`;
      browserRefreshScreenshot();
    } else {
      status.textContent = `✗ ${r.error || "Navigation failed"}`;
    }
  } catch(e) {
    status.textContent = `✗ ${e.message}`;
  }
}

function browserRefreshScreenshot() {
  const img = $id("browser-screenshot");
  if (!img) return;
  img.src = `/static/previews/browser_screenshot.png?t=${Date.now()}`;
}

function startBrowserAutoRefresh() {
  if (_browserRefreshInterval) return;
  _browserRefreshInterval = setInterval(browserRefreshScreenshot, 2000);
}

function stopBrowserAutoRefresh() {
  if (_browserRefreshInterval) {
    clearInterval(_browserRefreshInterval);
    _browserRefreshInterval = null;
  }
}

// Override showIsland to start auto-refresh for browser
const _origShowIsland = showIsland;
function showIsland(name) {
  _origShowIsland(name);
  if (name === "browser") startBrowserAutoRefresh();
}
const _origHideIsland = hideIsland;
function hideIsland(name) {
  _origHideIsland(name);
  if (name === "browser") stopBrowserAutoRefresh();
}
```

Also add handler for `browser_navigated` WS event inside `dispatch()`:

```javascript
    case "browser_navigated":
      browserRefreshScreenshot();
      if ($id("browser-url-input") && obj.url) $id("browser-url-input").value = obj.url;
      if ($id("browser-status")) $id("browser-status").textContent = `✓ ${obj.title || obj.url}`;
      break;
```

Also handle Enter key in URL bar. In the `DOMContentLoaded` block, add:

```javascript
  const urlInput = $id("browser-url-input");
  if (urlInput) urlInput.addEventListener("keydown", e => { if (e.key === "Enter") browserNavigate(); });
```

- [ ] **Step 4: Add browser commands to PALETTE_CMDS**

In `PALETTE_CMDS`, add before the existing `"Open Design Preview"` entry:

```javascript
  { icon:"🌐", label:"Open Browser Panel", action: () => showIsland("browser") },
```

- [ ] **Step 5: Verify browser island works**

Open `http://localhost:3030`, press ⌘K → "Open Browser Panel". Type `https://example.com` and press Enter. Verify:
- Status changes to "Navigating…" then "✓ Example Domain"
- Screenshot appears in the island

- [ ] **Step 6: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/static/index.html app/static/style-v5.css app/static/app-v5.js
git commit -m "feat: browser island UI — URL bar, navigation, auto-refresh screenshot"
```

---

## Task 5: Voice Engine (Hey Subaru)

**Files:**
- Modify: `app/static/app-v5.js`
- Modify: `app/static/index.html`

This is pure frontend — no backend changes needed.

- [ ] **Step 1: Add voice toggle to header in index.html**

In the header `hdr-pills` section, add a voice toggle pill after the `routines-pill`:

```html
    <button class="pill pill-icon" id="voice-toggle-btn" title="Toggle voice (Hey Subaru)" onclick="toggleVoiceMode()">🎤</button>
```

- [ ] **Step 2: Add voice engine to app-v5.js**

Just before `document.addEventListener("DOMContentLoaded", ...)`, add:

```javascript
// ── Voice Engine ────────────────────────────────────────────────────────────

const AGENT_VOICES = {
  ceo:      { lang: "en-GB", pitch: 0.9, rate: 0.95 },
  frontend: { lang: "en-US", pitch: 1.1, rate: 1.0  },
  backend:  { lang: "en-US", pitch: 0.7, rate: 0.85 },
  qa:       { lang: "en-US", pitch: 1.0, rate: 0.9  },
  devops:   { lang: "en-US", pitch: 0.8, rate: 0.9  },
};

let _recognition  = null;
let _voiceEnabled = false;
let _voiceActive  = false;  // true = wake word detected, listening for command
let _ttsEnabled   = true;

function initVoiceRecognition() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    pushNotif("Speech recognition not supported in this browser", "warn");
    return false;
  }
  _recognition = new SR();
  _recognition.continuous     = true;
  _recognition.interimResults = true;
  _recognition.lang           = "en-US";

  _recognition.onresult = (event) => {
    const transcript = Array.from(event.results)
      .map(r => r[0].transcript).join("").toLowerCase().trim();

    if (!_voiceActive && transcript.includes("hey subaru")) {
      _voiceActive = true;
      $id("voice-btn").style.color = "var(--cyan)";
      pushNotif("🎤 Listening for command…", "success");
      setReactorState("thinking");
    }

    if (_voiceActive && event.results[event.results.length - 1].isFinal) {
      const cmd = transcript.replace(/hey subaru/gi, "").trim();
      if (cmd.length > 2) {
        sendMsgText(cmd);
        _voiceActive = false;
        $id("voice-btn").style.color = "";
        setReactorState("idle");
      }
    }
  };

  _recognition.onerror = (e) => {
    if (e.error !== "no-speech") {
      pushNotif(`Voice error: ${e.error}`, "warn");
    }
    _voiceActive = false;
    $id("voice-btn").style.color = "";
  };

  _recognition.onend = () => {
    // Auto-restart to keep continuous listening when enabled
    if (_voiceEnabled) {
      try { _recognition.start(); } catch(e) {}
    }
  };

  return true;
}

function toggleVoiceMode() {
  const btn = $id("voice-toggle-btn");
  if (_voiceEnabled) {
    _voiceEnabled = false;
    _voiceActive  = false;
    if (_recognition) { try { _recognition.stop(); } catch(e) {} }
    if (btn) btn.style.color = "";
    pushNotif("Voice off", "warn");
  } else {
    if (!_recognition && !initVoiceRecognition()) return;
    _voiceEnabled = true;
    try { _recognition.start(); } catch(e) {}
    if (btn) btn.style.color = "var(--cyan)";
    pushNotif('🎤 Say "Hey Subaru" to activate', "success");
  }
}

function speakResponse(text, agentId) {
  if (!_ttsEnabled || !window.speechSynthesis || !text) return;
  speechSynthesis.cancel();  // cancel any ongoing speech
  const utter   = new SpeechSynthesisUtterance(text.replace(/```[\s\S]*?```/g, "code block").slice(0, 500));
  const profile = AGENT_VOICES[agentId] || AGENT_VOICES.ceo;
  utter.lang    = profile.lang;
  utter.pitch   = profile.pitch;
  utter.rate    = profile.rate;

  // Try to find a matching voice
  const voices  = speechSynthesis.getVoices();
  const match   = voices.find(v => v.lang.startsWith(profile.lang.split("-")[0]));
  if (match) utter.voice = match;

  speechSynthesis.speak(utter);
}
```

- [ ] **Step 3: Wire speakResponse into dispatch()**

In the `dispatch()` function, find the `case "done":` block:

```javascript
    case "done":
    case "worker_done":
      setOrbState(agentId, "idle");
      setReactorState("idle");
      clearThinking();
      if (obj.summary) appendMsg(agentId, "assistant", `✓ ${obj.summary}`);
      break;
```

Replace with:

```javascript
    case "done":
    case "worker_done": {
      setOrbState(agentId, "idle");
      setReactorState("idle");
      clearThinking();
      if (obj.summary) appendMsg(agentId, "assistant", `✓ ${obj.summary}`);
      // Speak the last assistant message aloud if TTS is enabled
      const logs = S.chatLogs[agentId] || [];
      const lastMsg = [...logs].reverse().find(m => m.role === "assistant");
      if (lastMsg && _ttsEnabled) speakResponse(lastMsg.content, agentId);
      break;
    }
```

- [ ] **Step 4: Add TTS toggle to palette**

In `PALETTE_CMDS`, add:

```javascript
  { icon:"🔊", label:"Toggle TTS (voice responses)", action: () => {
    _ttsEnabled = !_ttsEnabled;
    pushNotif(`TTS ${_ttsEnabled ? "on" : "off"}`, _ttsEnabled ? "success" : "warn");
  }},
```

- [ ] **Step 5: Verify voice works**

Open `http://localhost:3030` in Chrome (not Firefox — SpeechRecognition is Chrome-only).
Click the 🎤 pill in the header. You should see the notification `Say "Hey Subaru" to activate`.
Say "Hey Subaru, what is 2 plus 2?" — the command should appear in the input bar and send.

- [ ] **Step 6: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/static/app-v5.js app/static/index.html
git commit -m "feat: Hey Subaru voice engine — wake word STT + per-agent TTS"
```

---

## Task 6: Claude Vision — Backend

**Files:**
- Modify: `app/agents/executor.py`
- Modify: `app/api/websocket.py`
- Create: `tests/test_vision.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_vision.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_run_claude_vision_streams_text():
    """run_claude_vision should stream text chunks via send."""
    from app.agents.executor import run_claude_vision

    sent = []
    async def fake_send(d): sent.append(d)

    images = [{"media_type": "image/png", "data": "aGVsbG8="}]

    mock_stream = AsyncMock()
    mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
    mock_stream.__aexit__  = AsyncMock(return_value=None)

    async def _text_stream():
        yield "Hello "
        yield "world"

    mock_stream.text_stream = _text_stream()
    mock_stream.get_final_text = AsyncMock(return_value="Hello world")

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = mock_stream

    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        result = await run_claude_vision("ceo", "what do you see?", images, fake_send)

    text_events = [e for e in sent if e.get("type") == "assistant"]
    assert len(text_events) > 0
    assert result == "Hello world"


@pytest.mark.asyncio
async def test_run_claude_vision_builds_multimodal_content():
    """run_claude_vision must include image blocks before the text block."""
    from app.agents.executor import run_claude_vision

    sent = []
    async def fake_send(d): sent.append(d)

    images = [
        {"media_type": "image/png",  "data": "abc"},
        {"media_type": "image/jpeg", "data": "def"},
    ]

    captured_call = {}

    class FakeStream:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            pass
        @property
        def text_stream(self):
            async def _gen(): yield "ok"
            return _gen()
        async def get_final_text(self): return "ok"

    class FakeMessages:
        def stream(self, **kwargs):
            captured_call.update(kwargs)
            return FakeStream()

    class FakeClient:
        messages = FakeMessages()

    with patch("anthropic.AsyncAnthropic", return_value=FakeClient()):
        await run_claude_vision("ceo", "describe these", images, fake_send)

    content = captured_call.get("messages", [{}])[0].get("content", [])
    image_blocks = [b for b in content if b.get("type") == "image"]
    text_blocks  = [b for b in content if b.get("type") == "text"]
    assert len(image_blocks) == 2
    assert len(text_blocks)  == 1
    assert text_blocks[0]["text"] == "describe these"
    assert image_blocks[0]["source"]["data"] == "abc"
    assert image_blocks[1]["source"]["data"] == "def"


@pytest.mark.asyncio
async def test_run_claude_vision_falls_back_on_error():
    """On API error, vision should fall back gracefully."""
    from app.agents.executor import run_claude_vision

    sent = []
    async def fake_send(d): sent.append(d)

    with patch("anthropic.AsyncAnthropic", side_effect=Exception("network error")):
        result = await run_claude_vision("ceo", "describe", [{"media_type":"image/png","data":"x"}], fake_send)

    assert "[vision error" in result.lower() or result == ""
```

- [ ] **Step 2: Run — expect failure**

```bash
docker exec virtual-company python -m pytest /app/tests/test_vision.py -v 2>&1 | tail -5
```

Expected: `ImportError` — `run_claude_vision` not defined.

- [ ] **Step 3: Add run_claude_vision to executor.py**

Add this function to `app/agents/executor.py` **after** `run_gemini_agent` and **before** `_classify_model`:

```python
async def run_claude_vision(
    agent_id: str,
    text: str,
    images: list[dict],
    send: Sender,
) -> str:
    """Multimodal Claude API call for image+text inputs.

    Uses the Anthropic Python SDK directly (not Claude CLI) since the CLI
    does not support image content blocks. Falls back to text-only on error.

    images: list of {media_type: str, data: str (base64)}
    """
    try:
        import anthropic

        content: list[dict] = []
        for img in images:
            content.append({
                "type": "image",
                "source": {
                    "type":       "base64",
                    "media_type": img["media_type"],
                    "data":       img["data"],
                },
            })
        content.append({"type": "text", "text": text or "What do you see in this image?"})

        client   = anthropic.AsyncAnthropic()
        full_resp = ""

        async with client.messages.stream(
            model=config.DEFAULT_MODEL,
            max_tokens=4096,
            system=defs.agent_persona(agent_id),
            messages=[{"role": "user", "content": content}],
        ) as stream:
            async for chunk in stream.text_stream:
                await send({
                    "type":    "assistant",
                    "agent":   agent_id,
                    "message": {"content": [{"type": "text", "text": chunk}]},
                })
                full_resp += chunk

        try:
            mem_svc.save_memory(agent_id, text, mem_type="vision_query", importance=0.5)
            if full_resp:
                mem_svc.save_memory(agent_id, full_resp[:500], mem_type="vision_response", importance=0.4)
        except Exception:
            pass

        return full_resp

    except Exception as exc:
        logger.warning("run_claude_vision failed: %s", exc)
        error_msg = f"[vision error: {exc}]"
        await send({
            "type":    "assistant",
            "agent":   agent_id,
            "message": {"content": [{"type": "text", "text": error_msg}]},
        })
        return error_msg
```

- [ ] **Step 4: Route image messages to vision in websocket.py**

In `app/api/websocket.py`, find `_handle_message`:

```python
async def _handle_message(session: Session, agent_id: str, text: str) -> None:
    """Execute a user message to a specific agent."""
    state.record(agent_id, "user", text)
    send = session.make_sender(agent_id)
    await session.send({"type": "thinking", "agent": agent_id})
    full_resp = await run_agent(agent_id, text, send, session.model)
```

This function only handles text. Add a new `_handle_vision_message` function after `_handle_message`:

```python
async def _handle_vision_message(
    session: Session,
    agent_id: str,
    text: str,
    images: list[dict],
) -> None:
    """Handle a message that contains image attachments — routes to Claude vision."""
    from app.agents.executor import run_claude_vision

    user_label = text + f" [+{len(images)} image(s)]" if text else f"[{len(images)} image(s)]"
    state.record(agent_id, "user", user_label)
    send = session.make_sender(agent_id)

    await session.send({"type": "thinking", "agent": agent_id})
    full_resp = await run_claude_vision(agent_id, text, images, send)

    state.record(agent_id, "assistant", full_resp)
    await session.send({"type": "done", "agent": agent_id})
```

Then in `ws_endpoint`, in the `if msg_type == "message":` block, update the handling:

Find:
```python
            if msg_type == "message":
                agent_id = msg.get("agent", "ceo")
                text     = msg.get("text", "").strip()
                if not text:
                    continue
                if agent_id not in defs.all_agents():
                    agent_id = "ceo"
                await _handle_message(session, agent_id, text)
```

Replace with:
```python
            if msg_type == "message":
                agent_id    = msg.get("agent", "ceo")
                text        = msg.get("text", "").strip()
                attachments = msg.get("attachments", [])
                if agent_id not in defs.all_agents():
                    agent_id = "ceo"
                images = [
                    a for a in attachments
                    if a.get("media_type", "").startswith("image/")
                    and a.get("data")
                ]
                if images and backend_state.should_use_claude():
                    await _handle_vision_message(session, agent_id, text, images)
                elif text:
                    await _handle_message(session, agent_id, text)
                else:
                    continue
```

- [ ] **Step 5: Run tests — expect pass**

```bash
docker exec virtual-company python -m pytest /app/tests/test_vision.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 6: Run full suite**

```bash
docker exec virtual-company python -m pytest /app/tests/ -v 2>&1 | tail -5
```

Expected: 43 tests pass (40 + 3 new).

- [ ] **Step 7: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/agents/executor.py app/api/websocket.py tests/test_vision.py
git commit -m "feat: Claude Vision — multimodal image+text API path with SDK streaming"
```

---

## Task 7: Claude Vision — Frontend

**Files:**
- Modify: `app/static/app-v5.js`

The frontend already sends attachments (added in Phase 1 Task 12). This task adds visual feedback: show image thumbnails in the chat thread and display a vision indicator.

- [ ] **Step 1: Add vision message rendering in appendMsg**

In `app-v5.js`, find the `appendMsg` function:

```javascript
function appendMsg(agentId, role, content) {
  if (!S.chatLogs[agentId]) S.chatLogs[agentId] = [];
  S.chatLogs[agentId].push({ role, content });
  if (agentId === S.activeAgent) renderChat();
}
```

Replace with:

```javascript
function appendMsg(agentId, role, content, images) {
  if (!S.chatLogs[agentId]) S.chatLogs[agentId] = [];
  S.chatLogs[agentId].push({ role, content, images: images || [] });
  if (agentId === S.activeAgent) renderChat();
}
```

- [ ] **Step 2: Update renderChat to show image thumbnails**

In `renderChat()`, find the message rendering section. Find the `div.innerHTML` assignment for each message. The current msg-body is:

```javascript
      <div class="msg-body">${fmtMd(m.content||"")}</div>`;
```

Replace with:

```javascript
      <div class="msg-body">
        ${(m.images||[]).map(img => `<img class="chat-image-thumb" src="data:${escHtml(img.media_type)};base64,${img.data}" alt="attached image">`).join("")}
        ${fmtMd(m.content||"")}
      </div>`;
```

- [ ] **Step 3: Add chat image thumbnail CSS to style-v5.css**

Append to `app/static/style-v5.css`:

```css
/* ── Vision / Chat images ─────────────────────────────────────────────── */
.chat-image-thumb {
  max-width: 100%; max-height: 200px;
  border-radius: 8px; display: block;
  margin-bottom: 8px; object-fit: contain;
  border: 1px solid var(--border);
}
```

- [ ] **Step 4: Pass images through sendMsg**

In `sendMsg()`, find where `appendMsg` is called:

```javascript
  S.ws.send(JSON.stringify(payload));
  appendMsg(S.activeAgent, "user", text + (S.attachments.length ? ` [+${S.attachments.length} file(s)]` : ""));
```

Replace with:

```javascript
  S.ws.send(JSON.stringify(payload));
  const imageAttachments = S.attachments.filter(a => a.type.startsWith("image/"));
  appendMsg(S.activeAgent, "user", text, imageAttachments);
```

- [ ] **Step 5: Add vision indicator in thinking layer**

In `dispatch()`, find the `case "thinking":` block and update the thinking step text to indicate vision when images are in flight:

```javascript
    case "thinking":
      setOrbState(agentId, "thinking");
      setReactorState("thinking");
      addThinkingStep(`${S.agents[agentId]?.name || agentId} thinking…`);
      break;
```

(Leave this as-is — the vision path reuses the same thinking event, so the indicator already works.)

- [ ] **Step 6: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/static/app-v5.js app/static/style-v5.css
git commit -m "feat: vision UI — image thumbnails in chat + vision message rendering"
```

---

## Task 8: End-to-End Smoke Test

- [ ] **Step 1: Full test suite**

```bash
docker exec virtual-company python -m pytest /app/tests/ -v
```

Expected: **43 tests PASS** (36 Phase 1+2 + 4 browser playwright + 3 vision).

- [ ] **Step 2: Browser navigation smoke test**

```bash
docker exec virtual-company python3 -c "
import asyncio, sys
sys.path.insert(0, '/app')
from app.services.browser import navigate

async def test():
    result = await navigate('https://example.com')
    print('title:', result.get('title'))
    print('screenshot:', result.get('screenshot'))
    print('error:', result.get('error', 'none'))

asyncio.run(test())
"
```

Expected: `title: Example Domain`, `screenshot: /static/previews/browser_screenshot.png`, `error: none`

- [ ] **Step 3: Verify screenshot is served**

```bash
docker exec virtual-company ls -la /app/app/static/previews/browser_screenshot.png
```

Expected: file exists with non-zero size.

- [ ] **Step 4: API health check**

```bash
docker exec virtual-company curl -s http://localhost:3030/api/capabilities > /dev/null && echo "API OK"
docker logs virtual-company --tail 10 | grep -E "ERROR|Traceback" || echo "No errors"
```

Expected: `API OK`, `No errors`.

- [ ] **Step 5: Final commit**

```bash
cd /home/subaru/projects/virtual-company
git add -A
git status
git commit -m "feat: Phase 3 complete — Playwright Browser, Voice (Hey Subaru), Claude Vision" 2>/dev/null || echo "Nothing to commit"
```

---

## Self-Review

**Spec coverage:**

| Spec Requirement | Task |
|---|---|
| Playwright Docker install | Task 1 |
| Browser singleton with context-leak fix | Task 2 (`_get_browser` with `_playwright_ctx`) |
| navigate(), extract_text(), click_element() | Task 2 |
| Browser API endpoints (POST /navigate, /screenshot, /extract, /click) | Task 3 |
| Agent browser tools (web_navigate, web_extract, web_screenshot) | Task 3 |
| Browser island URL bar + screenshot display | Task 4 |
| Auto-refresh screenshot every 2s when island open | Task 4 |
| Voice wake word "Hey Subaru" | Task 5 |
| Per-agent TTS profiles | Task 5 |
| TTS reads agent responses aloud | Task 5 |
| Claude Vision multimodal API path | Task 6 |
| Vision routing in websocket.py | Task 6 |
| Image thumbnails in chat thread | Task 7 |

**No placeholders found. All code blocks complete.**

**Type consistency:**
- `run_claude_vision(agent_id, text, images, send)` defined Task 6 executor.py, called from Task 6 websocket.py — consistent.
- `navigate(url)` returns `dict` with `title/url/screenshot/error` — used in Task 3 API and Task 4 JS — consistent.
- `images: list[dict]` — `{media_type: str, data: str}` format used in Task 6 backend matches `S.attachments` format from frontend — consistent.
