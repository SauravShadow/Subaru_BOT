import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_run_agent_uses_gemini_when_claude_exhausted():
    """When Claude is exhausted, coding tasks fall back to Gemini (not tgpt)."""
    import app.agents.backend_state as bs
    bs._quota_exhausted_at = None
    bs._gemini_failed_at   = None
    bs._current_backend    = "claude"
    bs.mark_quota_exhausted()   # Claude → exhausted

    from app.agents import runner as executor
    sent = []
    async def fake_send(d): sent.append(d)

    # Claude-classified prompt (coding) + Gemini available → falls back to Gemini
    with patch.object(bs, "gemini_available", return_value=True):
        with patch.object(executor, "run_gemini_agent", new=AsyncMock(return_value="gemini reply")) as mock_g:
            result = await executor.run_agent("ceo", "debug this python function", fake_send)
            mock_g.assert_called_once()
            assert result == "gemini reply"

    bs.mark_claude_recovered()


@pytest.mark.asyncio
async def test_classify_model_routes_correctly():
    """Task classifier routes by type: long/chitchat → gemini, code/logic → claude."""
    from app.agents.runner import _classify_model

    assert _classify_model("write a python class for async http requests") == "claude"
    assert _classify_model("debug this traceback") == "claude"
    assert _classify_model("step by step instructions") == "claude"
    assert _classify_model("hi") == "gemini"           # short chitchat
    assert _classify_model("x" * 9000) == "gemini"    # long context


@pytest.mark.asyncio
async def test_run_agent_prefers_gemini_for_chitchat():
    """Short chitchat prompts route to Gemini when it's available."""
    import app.agents.backend_state as bs
    bs._quota_exhausted_at = None
    bs._gemini_failed_at   = None
    bs._current_backend    = "claude"

    from app.agents import runner as executor
    sent = []
    async def fake_send(d): sent.append(d)

    with patch.object(bs, "gemini_available", return_value=True):
        with patch.object(executor, "run_gemini_agent", new=AsyncMock(return_value="gemini reply")) as mock_g:
            result = await executor.run_agent("ceo", "hi", fake_send)
            mock_g.assert_called_once()
            assert result == "gemini reply"

    bs.mark_claude_recovered()


@pytest.mark.asyncio
async def test_run_gemini_agent_falls_back_on_error():
    """When Gemini raises, it falls back to tgpt and marks gemini failed."""
    import sys
    import app.agents.backend_state as bs
    bs._quota_exhausted_at = None
    bs._gemini_failed_at   = None
    bs._current_backend    = "claude"
    bs.mark_quota_exhausted()

    from app.agents import runner as executor
    sent = []
    async def fake_send(d): sent.append(d)

    # Mock the entire google.genai module so the deferred import works cleanly
    mock_genai = MagicMock()
    mock_genai.Client.return_value.models.generate_content.side_effect = Exception("api error")

    with patch.dict(sys.modules, {"google": MagicMock(genai=mock_genai), "google.genai": mock_genai}):
        with patch.object(executor, "run_tgpt_agent", new=AsyncMock(return_value="tgpt reply")):
            result = await executor.run_gemini_agent("ceo", "hello", fake_send)
            assert result == "tgpt reply"
            assert bs.get_current_backend() == "tgpt"

    bs.mark_claude_recovered()


def test_gemini_prompt_carves_exception_for_agents_with_safe_tags():
    """Maya's prompt must explicitly permit her [BROWSER_*] tags, not blanket-ban them."""
    from app.agents.runner import _build_gemini_prompt
    prompt = _build_gemini_prompt("browser", "find backend roles and apply")
    assert "[BROWSER_APPLY:" in prompt
    assert "[BROWSER_DISCOVER:" in prompt
    assert "MUST use your role-specific action tags" in prompt
    assert "Do NOT output [BASH:], [READ:], [WRITE:], [DELEGATE:]" in prompt

def test_gemini_prompt_keeps_blanket_ban_for_agents_without_safe_tags():
    """An agent with no gemini_safe_tags gets the original blanket instruction, unchanged."""
    from app.agents.runner import _build_gemini_prompt
    prompt = _build_gemini_prompt("ceo", "what's the status of the deploy")
    assert "Do NOT output [BASH:], [READ:], [WRITE:]," in prompt
    assert "or similar execution tool tags" in prompt
    assert "MUST use your role-specific action tags" not in prompt
