import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_generate_standup_prompt_contains_sections():
    """Standup prompt must include all three state sections."""
    from app.services.standup import generate_standup_prompt

    mock_state = MagicMock()
    mock_state.load_projects.return_value = [
        {"name": "TradingBot", "status": "active"}
    ]
    mock_state.work_queue = [
        {"agent": "backend", "task": "Fix auth bug", "status": "pending"}
    ]
    mock_state.task_history = [
        {"summary": "Deployed new UI", "status": "completed"}
    ]

    with patch("app.services.standup.state", mock_state):
        prompt = await generate_standup_prompt()

    assert "TradingBot" in prompt
    assert "Fix auth bug" in prompt
    assert "Deployed new UI" in prompt


@pytest.mark.asyncio
async def test_generate_standup_prompt_empty_state():
    """Prompt generates when no projects/queue/history."""
    from app.services.standup import generate_standup_prompt

    mock_state = MagicMock()
    mock_state.load_projects.return_value = []
    mock_state.work_queue = []
    mock_state.task_history = []

    with patch("app.services.standup.state", mock_state):
        prompt = await generate_standup_prompt()

    assert isinstance(prompt, str)
    assert len(prompt) > 50


@pytest.mark.asyncio
async def test_run_morning_standup_calls_ceo_agent():
    """run_morning_standup must invoke run_agent with agent_id='ceo'."""
    from app.services.standup import run_morning_standup

    mock_state = MagicMock()
    mock_state.load_projects.return_value = []
    mock_state.work_queue = []
    mock_state.task_history = []

    with patch("app.services.standup.state", mock_state), \
         patch("app.services.standup.run_agent", new=AsyncMock(return_value="briefing")) as mock_run, \
         patch("app.services.standup.broadcast_event", new=AsyncMock()):
        await run_morning_standup()
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == "ceo"
