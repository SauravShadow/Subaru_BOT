import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_run_claude_vision_streams_text():
    """run_claude_vision should stream text chunks via send."""
    import os
    from app.agents.executor import run_claude_vision

    sent = []
    async def fake_send(d): sent.append(d)

    images = [{"media_type": "image/png", "data": "aGVsbG8="}]

    mock_stream = AsyncMock()
    mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
    mock_stream.__aexit__  = AsyncMock(return_value=None)

    async def _text_stream():
        yield "Hello "
        yield "world"

    mock_stream.text_stream = _text_stream()
    mock_stream.get_final_text = AsyncMock(return_value="Hello world")

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = mock_stream

    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            result = await run_claude_vision("ceo", "what do you see?", images, fake_send)

    text_events = [e for e in sent if e.get("type") == "assistant"]
    assert len(text_events) > 0
    assert result == "Hello world"


@pytest.mark.asyncio
async def test_run_claude_vision_builds_multimodal_content():
    """run_claude_vision must put image blocks before the text block."""
    import os
    from app.agents.executor import run_claude_vision

    sent = []
    async def fake_send(d): sent.append(d)

    images = [
        {"media_type": "image/png",  "data": "abc"},
        {"media_type": "image/jpeg", "data": "def"},
    ]

    captured_call = {}

    class FakeStream:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        @property
        def text_stream(self):
            async def _gen(): yield "ok"
            return _gen()
        async def get_final_text(self): return "ok"

    class FakeMessages:
        def stream(self, **kwargs):
            captured_call.update(kwargs)
            return FakeStream()

    class FakeClient:
        messages = FakeMessages()

    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
        with patch("anthropic.AsyncAnthropic", return_value=FakeClient()):
            await run_claude_vision("ceo", "describe these", images, fake_send)

    content = captured_call.get("messages", [{}])[0].get("content", [])
    image_blocks = [b for b in content if b.get("type") == "image"]
    text_blocks  = [b for b in content if b.get("type") == "text"]
    assert len(image_blocks) == 2
    assert len(text_blocks)  == 1
    assert text_blocks[0]["text"] == "describe these"
    assert image_blocks[0]["source"]["data"] == "abc"
    assert image_blocks[1]["source"]["data"] == "def"


@pytest.mark.asyncio
async def test_run_claude_vision_falls_back_on_error():
    """On API error, vision should return an error string (not raise)."""
    from app.agents.executor import run_claude_vision

    sent = []
    async def fake_send(d): sent.append(d)

    with patch("anthropic.AsyncAnthropic", side_effect=Exception("network error")):
        result = await run_claude_vision("ceo", "describe", [{"media_type":"image/png","data":"x"}], fake_send)

    assert "[vision error" in result.lower()
