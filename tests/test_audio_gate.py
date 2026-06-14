"""CEO-only voice gate — workers must never emit audio."""
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_worker_speak_emits_no_audio():
    from app.output.handlers import speak
    send = AsyncMock()
    with patch("app.services.bark_client.speak", new_callable=AsyncMock) as bark:
        bark.return_value = "BASE64AUDIO"
        text, audio_sent = await speak.handle("Hello | emotion: calm", "backend", send)
    assert audio_sent is False
    assert text == "Hello"
    bark.assert_not_called()
    audio_calls = [c for c in send.call_args_list if c[0][0].get("type") == "audio"]
    assert audio_calls == []


@pytest.mark.asyncio
async def test_ceo_speak_emits_audio():
    from app.output.handlers import speak
    send = AsyncMock()
    with patch("app.services.bark_client.speak", new_callable=AsyncMock) as bark:
        bark.return_value = "BASE64AUDIO"
        text, audio_sent = await speak.handle("Hello | emotion: calm", "ceo", send)
    assert audio_sent is True
    assert text == "Hello"
    audio_calls = [c for c in send.call_args_list if c[0][0].get("type") == "audio"]
    assert len(audio_calls) == 1


@pytest.mark.asyncio
async def test_worker_sing_emits_no_audio():
    from app.output.handlers import sing
    send = AsyncMock()
    with patch("app.services.bark_client.sing", new_callable=AsyncMock) as bark:
        bark.return_value = "BASE64AUDIO"
        lyrics, audio_sent = await sing.handle("la la | style: pop", "frontend", send)
    assert audio_sent is False
    bark.assert_not_called()


def test_gemini_prompt_speak_mandate_is_ceo_only():
    from app.agents.runner import _build_gemini_prompt
    ceo_prompt = _build_gemini_prompt("ceo", "hi")
    worker_prompt = _build_gemini_prompt("backend", "hi")
    assert "[SPEAK:" in ceo_prompt
    assert "MANDATORY" in ceo_prompt
    # Workers must NOT be told to speak
    assert "[SPEAK:" not in worker_prompt
