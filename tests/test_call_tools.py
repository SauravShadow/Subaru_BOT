import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_make_call_tool_returns_call_id():
    """make_call returns a dict with call_id and status."""
    with patch("app.agents.tools.run_outbound_call", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"call_id": "abc-123", "status": "dialing", "twilio_sid": "CA999"}
        from app.agents.tools import make_call
        result = await make_call(number="+919876543210", goal="Book a table", language="en")
    assert result["call_id"] == "abc-123"
    assert result["status"] == "dialing"


def test_parse_make_call_tag():
    """[MAKE_CALL: number | goal | language] parses into make_call tool args."""
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("[MAKE_CALL: +919876543210 | Book a table for 2 at 7pm | en]")
    assert tool == "make_call"
    assert args["number"] == "+919876543210"
    assert args["goal"] == "Book a table for 2 at 7pm"
    assert args["language"] == "en"


def test_parse_make_call_tag_defaults_language():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("[MAKE_CALL: +14155550100 | Ask about store hours]")
    assert tool == "make_call"
    assert args["language"] == "en"


def test_call_agent_is_known_worker():
    """call_agent must be a registered LangGraph worker."""
    from app.graph.nexus_graph import _KNOWN_AGENTS
    assert "call_agent" in _KNOWN_AGENTS


@pytest.mark.asyncio
async def test_get_call_transcript_tool():
    """get_call_transcript returns transcript for a known call_id."""
    with patch("app.agents.tools.call_store") as mock_store:
        mock_store.get_transcript.return_value = {
            "id": "abc-123",
            "goal": "Book a table",
            "transcript": [{"speaker": "nexus", "text": "Hello!"}],
        }
        from app.agents.tools import get_call_transcript
        result = await get_call_transcript(call_id="abc-123")
    assert result["id"] == "abc-123"
    assert len(result["transcript"]) == 1
