import pytest
from unittest.mock import AsyncMock, MagicMock, patch
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
        from app.services.browser import navigate
        await navigate("https://example.com")
        await navigate("https://other.com")

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
