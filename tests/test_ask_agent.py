import pytest
from unittest.mock import AsyncMock, patch


def test_parse_ask_agent_tag():
    """[ASK:ceo] should parse to ask_agent tool with target and question."""
    from app.agents.tools import parse_tool_call
    text = "I need clarification.\n[ASK:ceo] Should I use PostgreSQL or SQLite for this feature?"
    tool_type, tool_args = parse_tool_call(text)
    assert tool_type == "ask_agent"
    assert tool_args["target"] == "ceo"
    assert "PostgreSQL" in tool_args["question"]


def test_parse_ask_agent_multiline_question():
    """[ASK:backend] with multiline question captures full question."""
    from app.agents.tools import parse_tool_call
    text = "[ASK:backend] What is the current database schema?\nAnd what tables exist?"
    tool_type, tool_args = parse_tool_call(text)
    assert tool_type == "ask_agent"
    assert tool_args["target"] == "backend"
    assert "database schema" in tool_args["question"]


def test_parse_ask_agent_not_confused_with_bash():
    """[BASH:...] should still parse as bash, not ask_agent."""
    from app.agents.tools import parse_tool_call
    text = "[BASH: ls -la /app]"
    tool_type, tool_args = parse_tool_call(text)
    assert tool_type == "bash"


@pytest.mark.asyncio
async def test_execute_ask_agent_calls_run_agent():
    """_execute_tool should call run_agent on the target agent and return its response."""
    from app.agents import runner as executor

    sent = []
    async def fake_send(d): sent.append(d)

    with patch.object(executor, "run_agent", new=AsyncMock(return_value="Use SQLite.")) as mock_run:
        result = await executor._execute_tool(
            "backend", "ask_agent", {"target": "ceo", "question": "SQLite or Postgres?"}, fake_send
        )
        mock_run.assert_called_once_with("ceo", "SQLite or Postgres?", fake_send)
        assert "SQLite" in result


@pytest.mark.asyncio
async def test_execute_ask_agent_timeout_returns_fallback():
    """When target agent times out, return a descriptive fallback (don't raise)."""
    import asyncio
    from app.agents import runner as executor

    sent = []
    async def fake_send(d): sent.append(d)

    async def _slow(*a, **kw):
        await asyncio.sleep(999)

    with patch.object(executor, "run_agent", new=_slow):
        with patch("app.agents.runner._ASK_TIMEOUT", 0.05):
            result = await executor._execute_tool(
                "backend", "ask_agent", {"target": "ceo", "question": "hello?"}, fake_send
            )
    assert "timed out" in result.lower() or "no reply" in result.lower()
