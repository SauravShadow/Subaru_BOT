import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_run_agent_uses_gemini_when_claude_exhausted():
    """When Claude is exhausted, run_agent routes to run_gemini_agent."""
    import app.agents.backend_state as bs
    bs._quota_exhausted_at = None
    bs._gemini_failed_at   = None
    bs._current_backend    = "claude"
    bs.mark_quota_exhausted()   # Claude → exhausted, backend = "gemini"

    from app.agents import executor
    sent = []
    async def fake_send(d): sent.append(d)

    with patch.object(executor, "run_gemini_agent", new=AsyncMock(return_value="gemini reply")) as mock_g:
        result = await executor.run_agent("ceo", "hello", fake_send)
        mock_g.assert_called_once()
        assert result == "gemini reply"

    # reset
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

    from app.agents import executor
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
