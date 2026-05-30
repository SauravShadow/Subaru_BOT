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
import inspect
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
    closed = _current_page is None
    if not closed:
        result = _current_page.is_closed()
        closed = (await result) if inspect.isawaitable(result) else result
    if closed:
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
