"""
Browser service.

Provides:
- write_preview(html)     — write agent HTML to live preview iframe (no Playwright needed)
- navigate(url)           — headless Chromium navigation + screenshot
- extract_text(url, sel)  — scrape text from a CSS selector
- click_element(url, sel) — click an element and screenshot result
- take_screenshot(url?)   — screenshot current or new URL
- _get_browser()          — singleton Playwright browser (auto-reconnects)
"""
import asyncio
import logging
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────────
PREVIEW_FILE    = Path("/app/app/static/previews/index.html")
SCREENSHOT_FILE = Path("/app/app/static/previews/browser_screenshot.png")

# ── Playwright singleton ───────────────────────────────────────────────────────
_playwright_ctx = None   # holds the async context manager
_browser        = None   # holds the Browser instance


async def _get_browser():
    """Return a connected Playwright Chromium browser, recreating if disconnected."""
    global _playwright_ctx, _browser

    if _browser is not None and _browser.is_connected():
        return _browser

    # Close stale context before creating a new one (fixes context leak)
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


# ── Design preview (no Playwright needed) ─────────────────────────────────────

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
    """Navigate to URL, take screenshot. Returns {title, url, screenshot} or {url, error}."""
    page = None
    try:
        browser = await _get_browser()
        page    = await browser.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        title   = await page.title()
        SCREENSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(SCREENSHOT_FILE))
        return {
            "title":      title,
            "url":        url,
            "screenshot": "/static/previews/browser_screenshot.png",
        }
    except Exception as exc:
        logger.warning("navigate(%s) failed: %s", url, exc)
        return {"url": url, "error": str(exc)}
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass


async def take_screenshot(url: Optional[str] = None) -> dict:
    """Screenshot the current browser state (optionally navigate first)."""
    if url:
        return await navigate(url)
    if not SCREENSHOT_FILE.exists():
        return {"error": "No screenshot yet — navigate to a URL first"}
    return {"screenshot": "/static/previews/browser_screenshot.png"}


async def extract_text(url: str, selector: str) -> str:
    """Fetch a page and return innerText of the first matching CSS selector."""
    page = None
    try:
        browser = await _get_browser()
        page    = await browser.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        text    = await page.inner_text(selector)
        return text
    except Exception as exc:
        logger.warning("extract_text failed: %s", exc)
        return f"[extract_text error: {exc}]"
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass


async def click_element(url: str, selector: str) -> dict:
    """Navigate to URL, click an element, take screenshot."""
    page = None
    try:
        browser = await _get_browser()
        page    = await browser.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await page.click(selector, timeout=5000)
        await asyncio.sleep(0.5)
        SCREENSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(SCREENSHOT_FILE))
        title    = await page.title()
        page_url = page.url
        return {
            "title":      title,
            "url":        page_url,
            "screenshot": "/static/previews/browser_screenshot.png",
        }
    except Exception as exc:
        logger.warning("click_element failed: %s", exc)
        return {"error": str(exc)}
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass
