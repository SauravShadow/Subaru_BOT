"""Tests for bark_client — verifies timeout/None fallback without hitting real sidecar."""
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_speak_returns_base64_on_success():
    from app.services import bark_client
    mock_resp = AsyncMock()
    mock_resp.json = MagicMock(return_value={"audio": "dGVzdA=="})
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", return_value=mock_resp):
        result = await bark_client.speak("Hello", "calm")
    assert result == "dGVzdA=="


@pytest.mark.asyncio
async def test_speak_returns_none_on_timeout():
    from app.services import bark_client
    with patch("httpx.AsyncClient.post", side_effect=httpx.TimeoutException("timeout")):
        result = await bark_client.speak("Hello", "calm")
    assert result is None


@pytest.mark.asyncio
async def test_sing_returns_base64_on_success():
    from app.services import bark_client
    mock_resp = AsyncMock()
    mock_resp.json = MagicMock(return_value={"audio": "c2luZw=="})
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", return_value=mock_resp):
        result = await bark_client.sing("La la la", "hip hop")
    assert result == "c2luZw=="


@pytest.mark.asyncio
async def test_sing_returns_none_on_connection_error():
    from app.services import bark_client
    with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("refused")):
        result = await bark_client.sing("La la la", "hip hop")
    assert result is None


@pytest.mark.asyncio
async def test_get_filler_returns_base64():
    from app.services import bark_client
    mock_resp = AsyncMock()
    mock_resp.json = MagicMock(return_value={"audio": "ZmlsbGVy"})
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        result = await bark_client.get_filler("sing me a song")
    assert result == "ZmlsbGVy"


@pytest.mark.asyncio
async def test_get_filler_returns_none_when_bark_down():
    from app.services import bark_client
    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("refused")):
        result = await bark_client.get_filler("any context")
    assert result is None
