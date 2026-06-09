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


@pytest.mark.asyncio
async def test_browser_apply_handler_dispatches_and_returns_status(monkeypatch):
    import asyncio
    from app.output.handlers import browser_apply
    send = AsyncMock()
    dispatched = {}

    async def fake_call_browser_svc(tool_type, tool_args):
        dispatched["tool_type"] = tool_type
        dispatched["tool_args"] = tool_args
        return "[browser-svc: queued]"

    monkeypatch.setattr(browser_apply, "call_browser_svc", fake_call_browser_svc)
    text, bark_ok = await browser_apply.handle("https://linkedin.com/jobs/123", "maya", send)
    await asyncio.sleep(0)

    assert bark_ok is False
    assert "https://linkedin.com/jobs/123" in text
    assert dispatched == {"tool_type": "browser_apply", "tool_args": {"url": "https://linkedin.com/jobs/123"}}
    send.assert_called_once()
    assert send.call_args[0][0] == {
        "type": "tool_call", "agent": "maya", "tool": "browser_apply",
        "label": "Applying to job", "path": "https://linkedin.com/jobs/123",
    }


def test_browser_apply_pattern_matches_full_tag():
    from app.output.handlers import browser_apply
    sample = "[BROWSER_APPLY: https://linkedin.com/jobs/123]"
    m = browser_apply.PATTERN.search(sample)
    assert m is not None
    assert m.group(1).strip() == "https://linkedin.com/jobs/123"


@pytest.mark.asyncio
async def test_browser_discover_handler_dispatches_parsed_args(monkeypatch):
    import asyncio
    from app.output.handlers import browser_discover
    send = AsyncMock()
    dispatched = {}

    async def fake_call_browser_svc(tool_type, tool_args):
        dispatched["tool_type"] = tool_type
        dispatched["tool_args"] = tool_args
        return "[browser-svc: queued]"

    monkeypatch.setattr(browser_discover, "call_browser_svc", fake_call_browser_svc)
    text, bark_ok = await browser_discover.handle("Python backend | linkedin | Bangalore", "maya", send)
    await asyncio.sleep(0)

    assert bark_ok is False
    assert "Python backend" in text and "linkedin" in text and "Bangalore" in text
    assert dispatched["tool_type"] == "browser_discover"
    assert dispatched["tool_args"] == {
        "keywords": "Python backend", "platform": "linkedin", "location": "Bangalore",
    }
    send.assert_called_once()
    assert send.call_args[0][0]["tool"] == "browser_discover"


def test_browser_discover_pattern_matches_full_tag():
    from app.output.handlers import browser_discover
    sample = "[BROWSER_DISCOVER: Python backend | linkedin | Bangalore]"
    m = browser_discover.PATTERN.search(sample)
    assert m is not None
    assert "Python backend" in m.group(1)
