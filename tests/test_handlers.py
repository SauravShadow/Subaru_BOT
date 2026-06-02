"""Unit tests for speak and sing handlers."""
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_speak_handler_sends_audio_when_bark_works():
    from app.output.handlers import speak
    send = AsyncMock()
    with patch("app.services.bark_client.speak", return_value="dGVzdA=="):
        text, bark_ok = await speak.handle("Hello there | emotion: excited", "ceo", send)
    assert bark_ok is True
    send.assert_called_once()
    call_data = send.call_args[0][0]
    assert call_data["type"] == "audio"
    assert call_data["data"] == "dGVzdA=="
    assert call_data["mode"] == "speak"


@pytest.mark.asyncio
async def test_speak_handler_returns_text_and_false_when_bark_down():
    from app.output.handlers import speak
    send = AsyncMock()
    with patch("app.services.bark_client.speak", return_value=None):
        text, bark_ok = await speak.handle("Hello there | emotion: calm", "ceo", send)
    assert bark_ok is False
    assert "Hello there" in text
    send.assert_not_called()


@pytest.mark.asyncio
async def test_speak_handler_defaults_to_calm_when_no_emotion():
    from app.output.handlers import speak
    send = AsyncMock()
    with patch("app.services.bark_client.speak", return_value="abc") as mock_speak:
        await speak.handle("Just text no emotion tag", "ceo", send)
    mock_speak.assert_called_once_with("Just text no emotion tag", "calm")


@pytest.mark.asyncio
async def test_sing_handler_sends_audio_with_sing_mode():
    from app.output.handlers import sing
    send = AsyncMock()
    with patch("app.services.bark_client.sing", return_value="c2luZw=="):
        text, bark_ok = await sing.handle(
            "La la la\nSinging now | style: hip hop, fast", "ceo", send
        )
    assert bark_ok is True
    call_data = send.call_args[0][0]
    assert call_data["type"] == "audio"
    assert call_data["mode"] == "sing"


@pytest.mark.asyncio
async def test_sing_handler_returns_lyrics_as_text_when_bark_down():
    from app.output.handlers import sing
    send = AsyncMock()
    with patch("app.services.bark_client.sing", return_value=None):
        text, bark_ok = await sing.handle("La la la | style: pop", "ceo", send)
    assert bark_ok is False
    assert "La la la" in text
    send.assert_not_called()


def test_speak_pattern_matches_full_tag():
    from app.output.handlers import speak
    sample = "[SPEAK: Hello world | emotion: excited]"
    m = speak.PATTERN.search(sample)
    assert m is not None
    assert "Hello world" in m.group(1)


def test_sing_pattern_matches_multiline():
    from app.output.handlers import sing
    sample = "[SING: Look at the cash\nI'm bubbling | style: hip hop]"
    m = sing.PATTERN.search(sample)
    assert m is not None
    assert "bubbling" in m.group(1)
