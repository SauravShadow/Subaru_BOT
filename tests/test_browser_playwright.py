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
    from app.services import browser as bmod

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
    bmod._browser = None
    bmod._playwright_ctx = None
