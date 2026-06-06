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


def test_parse_browser_discover_non_platform_second_part():
    tool, args = parse_tool_call("[BROWSER_DISCOVER: React developer | remote]")
    assert tool == "browser_discover"
    assert args["keywords"] == "React developer"
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


@pytest.mark.asyncio
async def test_call_browser_svc_slot_busy_409():
    with patch("app.services.browser_svc.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_response = AsyncMock()
        mock_response.status_code = 409
        mock_client.post = AsyncMock(return_value=mock_response)

        result = await call_browser_svc("browser_apply", {"url": "https://test.com"})

    assert "slot busy" in result
