import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx


@pytest.mark.asyncio
async def test_speak_passes_voice_param():
    """speak() must forward the voice kwarg to bark-svc."""
    from app.services import bark_client
    captured = {}

    async def fake_post(url, json=None, timeout=None):
        captured.update(json or {})
        resp = AsyncMock()
        resp.json = MagicMock(return_value={"audio": "dGVzdA=="})
        resp.raise_for_status = MagicMock()
        return resp

    with patch("httpx.AsyncClient.post", side_effect=fake_post):
        await bark_client.speak("Hello world", "calm", voice="en-US-GuyNeural")

    assert captured.get("voice") == "en-US-GuyNeural"


@pytest.mark.asyncio
async def test_speak_omits_voice_when_none():
    """speak() without voice kwarg still works (backward compat)."""
    from app.services import bark_client
    captured = {}

    async def fake_post(url, json=None, timeout=None):
        captured.update(json or {})
        resp = AsyncMock()
        resp.json = MagicMock(return_value={"audio": "dGVzdA=="})
        resp.raise_for_status = MagicMock()
        return resp

    with patch("httpx.AsyncClient.post", side_effect=fake_post):
        await bark_client.speak("Hello world", "calm")

    assert "voice" not in captured
