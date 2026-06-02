# Persistent Browser + Web Interaction Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give agents a persistent browser session with full web interaction tools (click, type, wait, read) and a credential vault so they can log in to sites and extract information fluently.

**Architecture:** Refactor `browser.py` to maintain a single persistent Playwright page across calls (instead of open/close per operation). Add four new tool tags (`WEB_CLICK`, `WEB_TYPE`, `WEB_WAIT`, `WEB_GET_TEXT`) parsed in `tools.py` and dispatched in `executor.py`. Credential vault resolves `$CRED_*` references in `WEB_TYPE` from env vars — agents never see plaintext secrets. Update agent personas so CEO and workers know the new syntax.

**Tech Stack:** Python 3.12, Playwright async API, pytest, existing FastAPI app at `/home/subaru/projects/virtual-company`

---

## Context You Must Know

- Working directory: `/home/subaru/projects/virtual-company`
- App runs inside Docker container but source is mounted from host; Python files auto-reload in ~3s
- Key files: `app/services/browser.py`, `app/agents/tools.py`, `app/agents/executor.py`, `app/agents/definitions.py`, `app/config.py`
- Test suite: `tests/` — run with `python3 -m pytest tests/ -q` (44 pass, 11 pre-existing failures for missing modules — those are expected)
- `browser.py` currently opens a **new page per operation and closes it** — sessions are lost between calls
- `click_element(url, selector)` already exists in `browser.py` but is **not wired** in tools.py/executor.py
- `extract_text(url, selector)` takes a URL and navigates each time — will be updated to use persistent page
- Credential vault: env vars named `CRED_{NAME}` (e.g. `CRED_GMAIL_USER=me@gmail.com`) — agents write `$CRED_GMAIL_USER` in WEB_TYPE args

---

## File Map

| File | What changes |
|------|-------------|
| `app/services/browser.py` | Add `_current_page` global + `_get_page()`, refactor all ops to use it, add `type_text()`, `wait_for_element()`, `get_page_text()`, update `click_element()` and `extract_text()` signatures |
| `app/config.py` | Add `get_credential(name)` function |
| `app/agents/tools.py` | Add parsers for `WEB_CLICK`, `WEB_TYPE`, `WEB_WAIT`, `WEB_GET_TEXT`; update `WEB_EXTRACT` to not require URL |
| `app/agents/executor.py` | Add tool icons/labels + dispatch handlers for 4 new tools; update `web_extract` handler |
| `app/agents/definitions.py` | Add WEB TOOLS docs to CEO persona and backend worker extra |
| `tests/test_browser_persistent.py` | New test file — persistent page, new operations |
| `tests/test_web_tools_parser.py` | New test file — new tool parsers + credential vault |

---

## Task 1: Credential Vault in config.py

**Files:**
- Modify: `app/config.py`
- Test: `tests/test_web_tools_parser.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_web_tools_parser.py`:

```python
import os
from unittest.mock import patch


def test_get_credential_found():
    with patch.dict(os.environ, {"CRED_GMAIL_USER": "user@gmail.com"}):
        from app.config import get_credential
        assert get_credential("GMAIL_USER") == "user@gmail.com"


def test_get_credential_case_insensitive():
    with patch.dict(os.environ, {"CRED_MY_KEY": "secret"}):
        from app.config import get_credential
        assert get_credential("my_key") == "secret"


def test_get_credential_missing_returns_empty():
    from app.config import get_credential
    assert get_credential("DOES_NOT_EXIST_XYZ") == ""
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/subaru/projects/virtual-company && python3 -m pytest tests/test_web_tools_parser.py -v
```
Expected: `AttributeError: module 'app.config' has no attribute 'get_credential'`

- [ ] **Step 3: Add `get_credential` to config.py**

In `app/config.py`, append after the last line:

```python

def get_credential(name: str) -> str:
    """Resolve CRED_{NAME} from env. Agents use $CRED_NAME in WEB_TYPE args."""
    return os.environ.get(f"CRED_{name.upper().replace('-', '_')}", "")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/subaru/projects/virtual-company && python3 -m pytest tests/test_web_tools_parser.py::test_get_credential_found tests/test_web_tools_parser.py::test_get_credential_case_insensitive tests/test_web_tools_parser.py::test_get_credential_missing_returns_empty -v
```
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/config.py tests/test_web_tools_parser.py
git commit -m "feat: credential vault — get_credential() resolves CRED_* env vars"
```

---

## Task 2: Refactor browser.py — Persistent Session + New Operations

**Files:**
- Modify: `app/services/browser.py` (full rewrite)
- Test: `tests/test_browser_persistent.py` (create)

The key change: instead of each function creating and closing its own page, all operations share `_current_page`. `_get_page()` returns it (creating if None/closed).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_browser_persistent.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from pathlib import Path


@pytest.fixture(autouse=True)
def reset_browser_state():
    """Reset persistent page state between tests."""
    import app.services.browser as bsvc
    bsvc._current_page = None
    bsvc._browser = None
    bsvc._playwright_ctx = None
    yield
    bsvc._current_page = None
    bsvc._browser = None
    bsvc._playwright_ctx = None


def _make_mock_page(title="Test Page", url="https://example.com", text="page text"):
    page = AsyncMock()
    page.is_closed.return_value = False
    page.title = AsyncMock(return_value=title)
    page.url = url
    page.inner_text = AsyncMock(return_value=text)
    page.goto = AsyncMock()
    page.screenshot = AsyncMock()
    page.click = AsyncMock()
    page.fill = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.set_extra_http_headers = AsyncMock()
    return page


@pytest.mark.asyncio
async def test_navigate_reuses_page_on_second_call(tmp_path):
    """_get_page() returns the same page object on second navigate call."""
    mock_page = _make_mock_page()
    mock_browser = AsyncMock()
    mock_browser.is_connected.return_value = True
    mock_browser.new_page = AsyncMock(return_value=mock_page)

    with patch("app.services.browser._get_browser", return_value=mock_browser), \
         patch("app.services.browser.SCREENSHOT_FILE", tmp_path / "shot.png"):
        from app.services.browser import navigate, _get_page
        await navigate("https://example.com")
        await navigate("https://other.com")

    # new_page() called only once — persistent session
    assert mock_browser.new_page.call_count == 1


@pytest.mark.asyncio
async def test_navigate_creates_new_page_if_closed(tmp_path):
    """If current page is closed, _get_page() opens a fresh one."""
    import app.services.browser as bsvc
    closed_page = _make_mock_page()
    closed_page.is_closed.return_value = True
    bsvc._current_page = closed_page

    fresh_page = _make_mock_page()
    mock_browser = AsyncMock()
    mock_browser.is_connected.return_value = True
    mock_browser.new_page = AsyncMock(return_value=fresh_page)

    with patch("app.services.browser._get_browser", return_value=mock_browser), \
         patch("app.services.browser.SCREENSHOT_FILE", tmp_path / "shot.png"):
        from app.services.browser import navigate
        result = await navigate("https://example.com")

    assert mock_browser.new_page.call_count == 1
    assert "error" not in result


@pytest.mark.asyncio
async def test_type_text_calls_fill():
    """type_text(selector, text) calls page.fill with correct args."""
    mock_page = _make_mock_page()
    import app.services.browser as bsvc
    bsvc._current_page = mock_page

    with patch("app.services.browser._get_browser"):
        from app.services.browser import type_text
        result = await type_text("#email", "user@example.com")

    mock_page.fill.assert_called_once_with("#email", "user@example.com")
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_type_text_returns_error_on_failure():
    mock_page = _make_mock_page()
    mock_page.fill = AsyncMock(side_effect=Exception("selector not found"))
    import app.services.browser as bsvc
    bsvc._current_page = mock_page

    with patch("app.services.browser._get_browser"):
        from app.services.browser import type_text
        result = await type_text("#missing", "value")

    assert "error" in result


@pytest.mark.asyncio
async def test_click_element_uses_persistent_page(tmp_path):
    """click_element(selector) uses current page, not a new one."""
    mock_page = _make_mock_page()
    import app.services.browser as bsvc
    bsvc._current_page = mock_page

    with patch("app.services.browser._get_browser"), \
         patch("app.services.browser.SCREENSHOT_FILE", tmp_path / "shot.png"):
        from app.services.browser import click_element
        result = await click_element("#submit")

    mock_page.click.assert_called_once_with("#submit", timeout=5000)
    assert "screenshot" in result


@pytest.mark.asyncio
async def test_wait_for_element_success():
    mock_page = _make_mock_page()
    import app.services.browser as bsvc
    bsvc._current_page = mock_page

    with patch("app.services.browser._get_browser"):
        from app.services.browser import wait_for_element
        result = await wait_for_element(".dashboard")

    mock_page.wait_for_selector.assert_called_once_with(".dashboard", timeout=10000)
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_wait_for_element_timeout():
    mock_page = _make_mock_page()
    mock_page.wait_for_selector = AsyncMock(side_effect=Exception("timeout"))
    import app.services.browser as bsvc
    bsvc._current_page = mock_page

    with patch("app.services.browser._get_browser"):
        from app.services.browser import wait_for_element
        result = await wait_for_element(".missing")

    assert "error" in result


@pytest.mark.asyncio
async def test_get_page_text_returns_body_text():
    mock_page = _make_mock_page(text="Welcome to the dashboard")
    import app.services.browser as bsvc
    bsvc._current_page = mock_page

    with patch("app.services.browser._get_browser"):
        from app.services.browser import get_page_text
        result = await get_page_text()

    mock_page.inner_text.assert_called_once_with("body")
    assert result["text"] == "Welcome to the dashboard"
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_extract_text_uses_selector_on_current_page():
    mock_page = _make_mock_page(text="main content here")
    import app.services.browser as bsvc
    bsvc._current_page = mock_page

    with patch("app.services.browser._get_browser"):
        from app.services.browser import extract_text
        result = await extract_text(".main-content")

    mock_page.inner_text.assert_called_once_with(".main-content")
    assert result == "main content here"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/subaru/projects/virtual-company && python3 -m pytest tests/test_browser_persistent.py -v 2>&1 | head -30
```
Expected: Multiple failures — `_current_page` doesn't exist, `type_text` not defined, etc.

- [ ] **Step 3: Rewrite browser.py with persistent session**

Replace the entire content of `app/services/browser.py` with:

```python
"""
Browser service — persistent Playwright session.

Maintains a single page across operations so login sessions, cookies, and
form state are preserved between tool calls.

Public API:
  write_preview(html)           — write HTML to live design preview (no Playwright)
  navigate(url)                 — navigate persistent page to URL, screenshot
  click_element(selector)       — click element on current page, screenshot
  type_text(selector, text)     — fill form field on current page
  wait_for_element(selector)    — wait for CSS selector to appear
  get_page_text()               — get visible text of current page
  extract_text(selector)        — get innerText of CSS selector on current page
  take_screenshot(url?)         — screenshot current or new URL
"""
import asyncio
import logging
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

PREVIEW_FILE    = Path("/app/app/static/previews/index.html")
SCREENSHOT_FILE = Path("/app/app/static/previews/browser_screenshot.png")

_playwright_ctx = None
_browser        = None
_current_page   = None   # persistent page — shared across all operations


async def _get_browser():
    """Return a connected Playwright Chromium browser, recreating if disconnected."""
    global _playwright_ctx, _browser

    if _browser is not None and _browser.is_connected():
        return _browser

    if _playwright_ctx is not None:
        try:
            await _playwright_ctx.__aexit__(None, None, None)
        except Exception:
            pass
        _playwright_ctx = None

    _playwright_ctx = async_playwright()
    pw       = await _playwright_ctx.__aenter__()
    _browser = await pw.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    logger.info("Playwright Chromium browser started.")
    return _browser


async def _get_page():
    """Return the persistent page, creating a new one if needed or if closed."""
    global _current_page
    browser = await _get_browser()
    if _current_page is None or _current_page.is_closed():
        _current_page = await browser.new_page()
        await _current_page.set_extra_http_headers({
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        })
        logger.info("New persistent browser page created.")
    return _current_page


# ── Design preview (no Playwright needed) ────────────────────────────────────

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


# ── Playwright operations (all use persistent page) ──────────────────────────

async def navigate(url: str) -> dict:
    """Navigate persistent page to URL and take screenshot."""
    try:
        page = await _get_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        title = await page.title()
        SCREENSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(SCREENSHOT_FILE))
        return {
            "title":      title,
            "url":        page.url,
            "screenshot": "/static/previews/browser_screenshot.png",
        }
    except Exception as exc:
        logger.warning("navigate(%s) failed: %s", url, exc)
        return {"url": url, "error": str(exc)}


async def click_element(selector: str) -> dict:
    """Click element on current page and screenshot the result."""
    try:
        page = await _get_page()
        await page.click(selector, timeout=5000)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:
            pass  # click may not trigger navigation
        SCREENSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(SCREENSHOT_FILE))
        return {
            "url":        page.url,
            "title":      await page.title(),
            "screenshot": "/static/previews/browser_screenshot.png",
        }
    except Exception as exc:
        logger.warning("click_element(%s) failed: %s", selector, exc)
        return {"error": str(exc)}


async def type_text(selector: str, text: str) -> dict:
    """Fill a form field on the current page."""
    try:
        page = await _get_page()
        await page.fill(selector, text)
        return {"ok": True, "selector": selector}
    except Exception as exc:
        logger.warning("type_text(%s) failed: %s", selector, exc)
        return {"error": str(exc)}


async def wait_for_element(selector: str, timeout: int = 10000) -> dict:
    """Wait for a CSS selector to appear on the current page."""
    try:
        page = await _get_page()
        await page.wait_for_selector(selector, timeout=timeout)
        return {"ok": True, "selector": selector}
    except Exception as exc:
        logger.warning("wait_for_element(%s) failed: %s", selector, exc)
        return {"error": f"Element '{selector}' not found within timeout: {exc}"}


async def get_page_text() -> dict:
    """Get all visible text from the current page (up to 8000 chars)."""
    try:
        page = await _get_page()
        text = await page.inner_text("body")
        return {
            "ok":    True,
            "text":  text[:8000],
            "url":   page.url,
            "title": await page.title(),
        }
    except Exception as exc:
        logger.warning("get_page_text failed: %s", exc)
        return {"error": str(exc)}


async def extract_text(selector: str = "body") -> str:
    """Get innerText of a CSS selector on the current page."""
    try:
        page = await _get_page()
        return await page.inner_text(selector)
    except Exception as exc:
        logger.warning("extract_text(%s) failed: %s", selector, exc)
        return f"[extract_text error: {exc}]"


async def take_screenshot(url: Optional[str] = None) -> dict:
    """Screenshot the current page, optionally navigating first."""
    if url:
        return await navigate(url)
    if not SCREENSHOT_FILE.exists():
        return {"error": "No screenshot yet — navigate to a URL first"}
    return {"screenshot": "/static/previews/browser_screenshot.png"}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/subaru/projects/virtual-company && python3 -m pytest tests/test_browser_persistent.py -v
```
Expected: All 9 tests PASS

- [ ] **Step 5: Verify existing browser tests still pass**

```bash
cd /home/subaru/projects/virtual-company && python3 -m pytest tests/test_browser.py -v
```
Expected: 3 PASS (write_preview tests)

- [ ] **Step 6: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/services/browser.py tests/test_browser_persistent.py
git commit -m "feat: persistent browser session with click, type, wait, get_text operations"
```

---

## Task 3: New Tool Parsers in tools.py + Update WEB_EXTRACT

**Files:**
- Modify: `app/agents/tools.py` (lines ~200–213)
- Test: `tests/test_web_tools_parser.py` (add to existing)

New tool tags agents can use:
- `[WEB_CLICK:#selector]` — click element on current page
- `[WEB_TYPE:#selector:value]` — fill field; value can be `$CRED_NAME` to use vault
- `[WEB_WAIT:.selector]` — wait for element to appear
- `[WEB_GET_TEXT]` — get all visible text from current page
- `[WEB_EXTRACT:selector]` — extract text from selector (updated: no URL needed, uses current page)

- [ ] **Step 1: Add tests to test_web_tools_parser.py**

Append to `tests/test_web_tools_parser.py`:

```python
def test_parse_web_click_id_selector():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("do the thing [WEB_CLICK:#submit-btn] now")
    assert tool == "web_click"
    assert args["selector"] == "#submit-btn"


def test_parse_web_click_class_selector():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("[WEB_CLICK:.login-button]")
    assert tool == "web_click"
    assert args["selector"] == ".login-button"


def test_parse_web_type_plain_text():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("[WEB_TYPE:#email:user@example.com]")
    assert tool == "web_type"
    assert args["selector"] == "#email"
    assert args["text"] == "user@example.com"


def test_parse_web_type_credential_reference():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("[WEB_TYPE:#password:$CRED_GMAIL_PASS]")
    assert tool == "web_type"
    assert args["selector"] == "#password"
    assert args["text"] == "$CRED_GMAIL_PASS"


def test_parse_web_wait():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("[WEB_WAIT:.dashboard-loaded]")
    assert tool == "web_wait"
    assert args["selector"] == ".dashboard-loaded"


def test_parse_web_get_text():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("[WEB_GET_TEXT]")
    assert tool == "web_get_text"
    assert args == {}


def test_parse_web_extract_selector_only():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("[WEB_EXTRACT:.result-table]")
    assert tool == "web_extract"
    assert args["selector"] == ".result-table"
    assert "url" not in args or args.get("url") == ""
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/subaru/projects/virtual-company && python3 -m pytest tests/test_web_tools_parser.py -v -k "parse_web"
```
Expected: 7 failures — parsers not defined yet

- [ ] **Step 3: Add new parsers and update WEB_EXTRACT in tools.py**

In `app/agents/tools.py`, find the WEB_NAVIGATE block (around line 200):

```python
    m = re.search(r'\[WEB_NAVIGATE:\s*(\S+)\]', text)
    if m:
        return "web_navigate", {"url": m.group(1).strip()}

    m = re.search(r'\[WEB_EXTRACT:\s*(.*?)\]', text, re.DOTALL)
    if m:
        parts    = m.group(1).strip().split(None, 1)
        url      = parts[0] if parts else ""
        selector = parts[1] if len(parts) > 1 else "body"
        return "web_extract", {"url": url, "selector": selector}

    m = re.search(r'\[WEB_SCREENSHOT\]', text)
    if m:
        return "web_screenshot", {}
```

Replace with:

```python
    m = re.search(r'\[WEB_NAVIGATE:\s*(\S+)\]', text)
    if m:
        return "web_navigate", {"url": m.group(1).strip()}

    m = re.search(r'\[WEB_CLICK:\s*([^\]]+)\]', text)
    if m:
        return "web_click", {"selector": m.group(1).strip()}

    m = re.search(r'\[WEB_TYPE:\s*([^:\]]+):\s*([^\]]+)\]', text)
    if m:
        return "web_type", {"selector": m.group(1).strip(), "text": m.group(2).strip()}

    m = re.search(r'\[WEB_WAIT:\s*([^\]]+)\]', text)
    if m:
        return "web_wait", {"selector": m.group(1).strip()}

    m = re.search(r'\[WEB_GET_TEXT\]', text)
    if m:
        return "web_get_text", {}

    m = re.search(r'\[WEB_EXTRACT:\s*([^\]]*)\]', text)
    if m:
        raw = m.group(1).strip()
        # Legacy format: "url selector" — if first token looks like a URL, keep compat
        parts = raw.split(None, 1)
        if parts and parts[0].startswith(("http://", "https://")):
            return "web_extract", {"url": parts[0], "selector": parts[1] if len(parts) > 1 else "body"}
        return "web_extract", {"url": "", "selector": raw or "body"}

    m = re.search(r'\[WEB_SCREENSHOT\]', text)
    if m:
        return "web_screenshot", {}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/subaru/projects/virtual-company && python3 -m pytest tests/test_web_tools_parser.py -v
```
Expected: All 10 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/agents/tools.py tests/test_web_tools_parser.py
git commit -m "feat: add WEB_CLICK, WEB_TYPE, WEB_WAIT, WEB_GET_TEXT tool parsers"
```

---

## Task 4: Wire New Tools in executor.py

**Files:**
- Modify: `app/agents/executor.py`

Wire the four new tools into the executor dispatch. Also update `web_extract` handler to use the new no-URL signature. Add credential resolution for `WEB_TYPE`.

- [ ] **Step 1: Add new tool icons and labels**

In `app/agents/executor.py`, find the tool icons dict (around line 816):

```python
        "web_navigate":   "🌐",
        "web_screenshot": "📸",
        "web_extract":    "🔍",
```

Replace with:

```python
        "web_navigate":   "🌐",
        "web_screenshot": "📸",
        "web_extract":    "🔍",
        "web_click":      "🖱",
        "web_type":       "⌨",
        "web_wait":       "⏳",
        "web_get_text":   "📄",
```

- [ ] **Step 2: Add new tool labels**

Find the tool labels dict (around line 832):

```python
        "web_navigate":   "Navigating Browser",
        "web_screenshot": "Taking Screenshot",
        "web_extract":    "Extracting Text",
```

Replace with:

```python
        "web_navigate":   "Navigating Browser",
        "web_screenshot": "Taking Screenshot",
        "web_extract":    "Extracting Text",
        "web_click":      "Clicking Element",
        "web_type":       "Typing Text",
        "web_wait":       "Waiting for Element",
        "web_get_text":   "Reading Page",
```

- [ ] **Step 3: Update web_extract handler + add new handlers**

Find the `web_extract` handler (around line 894):

```python
        elif tool_type == "web_extract":
            from app.services.browser import extract_text as _ex
            url      = tool_args.get("url", "")
            selector = tool_args.get("selector", "body")
            result   = await _ex(url, selector)
```

Replace with:

```python
        elif tool_type == "web_extract":
            from app.services.browser import extract_text as _ex
            from app.services.browser import navigate as _nav
            url      = tool_args.get("url", "")
            selector = tool_args.get("selector", "body")
            if url:
                await _nav(url)   # navigate first for legacy url-selector format
            result = await _ex(selector)

        elif tool_type == "web_click":
            from app.services.browser import click_element as _click
            from app.api.websocket import broadcast_event
            selector = tool_args.get("selector", "")
            result_d = await _click(selector)
            result   = str(result_d)
            if result_d.get("screenshot"):
                asyncio.create_task(broadcast_event({
                    "type":       "browser_navigated",
                    "screenshot": result_d.get("screenshot", ""),
                    "title":      result_d.get("title", ""),
                    "url":        result_d.get("url", ""),
                }))

        elif tool_type == "web_type":
            from app.services.browser import type_text as _type
            from app import config as _cfg
            selector = tool_args.get("selector", "")
            raw_text = tool_args.get("text", "")
            if raw_text.startswith("$CRED_"):
                cred_key = raw_text[6:]          # strip "$CRED_"
                resolved = _cfg.get_credential(cred_key)
                if not resolved:
                    result = f"[web_type: credential '{raw_text}' not set — add CRED_{cred_key} to env]"
                else:
                    result_d = await _type(selector, resolved)
                    result   = str(result_d) + " [credential used]"
            else:
                result_d = await _type(selector, raw_text)
                result   = str(result_d)

        elif tool_type == "web_wait":
            from app.services.browser import wait_for_element as _wait
            selector = tool_args.get("selector", "body")
            result_d = await _wait(selector)
            result   = str(result_d)

        elif tool_type == "web_get_text":
            from app.services.browser import get_page_text as _gpt
            from app.api.websocket import broadcast_event
            result_d = await _gpt()
            result   = str(result_d)
            if result_d.get("screenshot"):
                asyncio.create_task(broadcast_event({
                    "type":       "browser_navigated",
                    "screenshot": result_d.get("screenshot", ""),
                    "title":      result_d.get("title", ""),
                    "url":        result_d.get("url", ""),
                }))
```

- [ ] **Step 4: Run full test suite**

```bash
cd /home/subaru/projects/virtual-company && python3 -m pytest tests/ -q
```
Expected: 44 + (new tests from tasks 1-3) pass, 11 pre-existing failures unchanged.

- [ ] **Step 5: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/agents/executor.py
git commit -m "feat: wire WEB_CLICK, WEB_TYPE, WEB_WAIT, WEB_GET_TEXT in executor"
```

---

## Task 5: Update Agent Personas — Web Tool Docs

**Files:**
- Modify: `app/agents/definitions.py`

Agents need to know the new tool syntax. Add a WEB TOOLS section to the CEO persona and to the backend worker's `extra` string.

- [ ] **Step 1: Add WEB TOOLS to CEO persona**

In `app/agents/definitions.py`, find the end of `_ceo_persona()` — the line with `USER_EMAIL`:

```python
  • User email: {config.USER_EMAIL or "(not configured)"}"""
```

Replace with:

```python
  • User email: {config.USER_EMAIL or "(not configured)"}

WEB TOOLS (use in sequence for login flows):
  [WEB_NAVIGATE:https://site.com]    — open URL in persistent browser session
  [WEB_CLICK:#selector]              — click button/link on current page
  [WEB_TYPE:#selector:value]         — fill form field; use $CRED_NAME for secrets
  [WEB_WAIT:.selector]               — wait for element to appear (after navigation/click)
  [WEB_GET_TEXT]                     — read all visible text from current page
  [WEB_EXTRACT:.selector]            — read text from specific CSS selector
  [WEB_SCREENSHOT]                   — take screenshot of current page

  CREDENTIAL VAULT: sensitive values like passwords are stored as env vars.
  Use $CRED_NAME in WEB_TYPE — system resolves it automatically, value never exposed.
  Example login flow:
    [WEB_NAVIGATE:https://gmail.com]
    [WEB_TYPE:#identifierId:$CRED_GMAIL_USER]
    [WEB_CLICK:#identifierNext]
    [WEB_WAIT:#password]
    [WEB_TYPE:input[name="Passwd"]:$CRED_GMAIL_PASS]
    [WEB_CLICK:#passwordNext]
    [WEB_WAIT:.inbox]
    [WEB_GET_TEXT]"""
```

- [ ] **Step 2: Add WEB TOOLS to backend worker extra**

In `app/agents/definitions.py`, find the backend worker's extra string — the `[ASK:ceo]` line at the end:

```python
For inter-agent questions:
  [ASK:ceo] Your question here   — CEO will reply; their answer is injected back""",
```

Replace with:

```python
For inter-agent questions:
  [ASK:ceo] Your question here   — CEO will reply; their answer is injected back

WEB TOOLS (persistent browser session — cookies/session preserved between calls):
  [WEB_NAVIGATE:https://url]     — go to URL
  [WEB_CLICK:#selector]          — click element on current page
  [WEB_TYPE:#selector:value]     — type into field; $CRED_NAME resolves from env vault
  [WEB_WAIT:.selector]           — wait for element (use after navigation or click)
  [WEB_GET_TEXT]                 — get all visible text from current page
  [WEB_EXTRACT:.selector]        — get text from CSS selector on current page
  [WEB_SCREENSHOT]               — screenshot current state""",
```

- [ ] **Step 3: Verify app still loads**

```bash
cd /home/subaru/projects/virtual-company && python3 -c "from app.agents.definitions import AGENT_DEFS; print('OK', list(AGENT_DEFS.keys()))"
```
Expected: `OK ['ceo', 'backend', 'frontend', 'qa', 'devops']`

- [ ] **Step 4: Run full test suite**

```bash
cd /home/subaru/projects/virtual-company && python3 -m pytest tests/ -q
```
Expected: all passing tests still pass, no new failures.

- [ ] **Step 5: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/agents/definitions.py
git commit -m "docs: add WEB TOOLS + credential vault syntax to agent personas"
```
