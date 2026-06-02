"""Tests for OutputPipeline — verifies tag dispatch and display text stripping."""
import pytest
import re
from unittest.mock import AsyncMock, MagicMock, patch


def _make_handler(tag: str, return_text: str = "", bark_ok: bool = False):
    h = MagicMock()
    h.TAG = tag
    h.PATTERN = re.compile(rf'\[{tag}:\s*(.*?)\]', re.DOTALL)
    h.handle = AsyncMock(return_value=(return_text, bark_ok))
    return h


@pytest.mark.asyncio
async def test_pipeline_dispatches_speak_tag():
    from app.output import pipeline
    send = AsyncMock()
    speak_handler = _make_handler("SPEAK", "Hello world", bark_ok=True)

    with patch.dict("app.output.registry.REGISTRY", {"SPEAK": speak_handler}, clear=True):
        with patch("app.output.registry.get_registry", return_value={"SPEAK": speak_handler}):
            await pipeline.process("[SPEAK: Hello world | emotion: calm]", "ceo", send)

    speak_handler.handle.assert_called_once()
    args = speak_handler.handle.call_args[0]
    assert "Hello world" in args[0]


@pytest.mark.asyncio
async def test_pipeline_strips_tag_from_display():
    from app.output import pipeline
    send = AsyncMock()
    speak_handler = _make_handler("SPEAK", "cleaned text", bark_ok=True)

    with patch("app.output.registry.get_registry", return_value={"SPEAK": speak_handler}):
        await pipeline.process("[SPEAK: cleaned text | emotion: calm]", "ceo", send)

    calls = [c[0][0] for c in send.call_args_list if c[0][0].get("type") == "assistant"]
    assert any("cleaned text" in str(c) for c in calls)
    assert not any("[SPEAK:" in str(c) for c in calls)


@pytest.mark.asyncio
async def test_pipeline_sets_bark_ok_true_when_audio_sent():
    from app.output import pipeline
    send = AsyncMock()
    speak_handler = _make_handler("SPEAK", "hi", bark_ok=True)

    with patch("app.output.registry.get_registry", return_value={"SPEAK": speak_handler}):
        await pipeline.process("[SPEAK: hi | emotion: excited]", "ceo", send)

    assistant_calls = [c[0][0] for c in send.call_args_list if c[0][0].get("type") == "assistant"]
    assert any(c.get("bark_ok") is True for c in assistant_calls)


@pytest.mark.asyncio
async def test_pipeline_sets_bark_ok_false_when_no_audio():
    from app.output import pipeline
    send = AsyncMock()
    speak_handler = _make_handler("SPEAK", "hi", bark_ok=False)

    with patch("app.output.registry.get_registry", return_value={"SPEAK": speak_handler}):
        await pipeline.process("[SPEAK: hi | emotion: calm]", "ceo", send)

    assistant_calls = [c[0][0] for c in send.call_args_list if c[0][0].get("type") == "assistant"]
    assert any(c.get("bark_ok") is False for c in assistant_calls)


@pytest.mark.asyncio
async def test_pipeline_handles_no_tags():
    from app.output import pipeline
    send = AsyncMock()

    with patch("app.output.registry.get_registry", return_value={}):
        await pipeline.process("Plain text with no tags", "ceo", send)

    assistant_calls = [c[0][0] for c in send.call_args_list if c[0][0].get("type") == "assistant"]
    assert len(assistant_calls) == 1
    assert assistant_calls[0]["message"]["content"][0]["text"] == "Plain text with no tags"


@pytest.mark.asyncio
async def test_pipeline_empty_display_sends_nothing():
    from app.output import pipeline
    send = AsyncMock()
    speak_handler = _make_handler("SPEAK", "", bark_ok=True)

    with patch("app.output.registry.get_registry", return_value={"SPEAK": speak_handler}):
        await pipeline.process("[SPEAK: hello | emotion: calm]", "ceo", send)

    assistant_calls = [c[0][0] for c in send.call_args_list if c[0][0].get("type") == "assistant"]
    assert len(assistant_calls) == 0
