import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_make_call_tool_returns_call_id():
    """make_call returns a dict with call_id and status."""
    with patch("app.agents.tools.run_outbound_call", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"call_id": "abc-123", "status": "dialing", "call_control_id": "ctrl-1"}
        from app.agents.tools import make_call
        result = await make_call(number="+919876543210", goal="Book a table", language="en")
    assert result["call_id"] == "abc-123"
    assert result["status"] == "dialing"


@pytest.mark.asyncio
async def test_handle_make_call_tags_fires_and_strips(monkeypatch):
    """[MAKE_CALL: ...] in agent output is executed backend-agnostically:
    the tag is stripped from the text and run_outbound_call is invoked."""
    import asyncio
    from app.agents import tools
    called = {}

    async def fake_run(number, goal, language="en", voice=""):
        called.update(number=number, goal=goal, language=language)
        return {"call_id": "abc-123", "status": "dialing", "call_control_id": "ctrl-1"}

    monkeypatch.setattr(tools, "run_outbound_call", fake_run)
    sent = []
    async def send(d): sent.append(d)

    text = "Sure, dialing now. [MAKE_CALL: +919876543210 | Book a table for 2 at 7pm | en]"
    cleaned, fired = await tools.handle_make_call_tags(text, send)

    assert fired is True
    assert "[MAKE_CALL" not in cleaned
    await asyncio.sleep(0.05)  # let the background task run
    assert called == {"number": "+919876543210", "goal": "Book a table for 2 at 7pm", "language": "en"}


@pytest.mark.asyncio
async def test_handle_make_call_tags_no_tag_is_noop():
    from app.agents import tools
    async def send(d): pass
    text = "What number should I call and what's the goal?"
    cleaned, fired = await tools.handle_make_call_tags(text, send)
    assert fired is False
    assert cleaned == text


@pytest.mark.asyncio
async def test_handle_make_call_tags_empty_number_does_not_fire(monkeypatch):
    """An empty number means the agent is still gathering info — don't dial."""
    from app.agents import tools
    fired_flag = {"v": False}
    async def fake_run(*a, **k):
        fired_flag["v"] = True
        return {}
    monkeypatch.setattr(tools, "run_outbound_call", fake_run)
    async def send(d): pass
    cleaned, fired = await tools.handle_make_call_tags("[MAKE_CALL:  | some goal | en]", send)
    assert fired is False
    assert fired_flag["v"] is False


def test_call_agent_is_known_worker():
    """call_agent must be a registered LangGraph worker."""
    from app.graph.nexus_graph import _KNOWN_AGENTS
    assert "call_agent" in _KNOWN_AGENTS


def test_ceo_can_delegate_to_call_agent():
    """CEO persona must list call_agent so it delegates phone-call requests
    instead of replying that it has no calling tool."""
    from app.agents import definitions as defs
    persona = defs.agent_persona("ceo")
    assert "[DELEGATE:call_agent]" in persona


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


@pytest.mark.asyncio
async def test_run_outbound_call_requires_telnyx_key(monkeypatch):
    import app.config as cfg
    from app.agents import tools
    monkeypatch.setattr(cfg, "TELNYX_API_KEY", "")
    res = await tools.run_outbound_call(number="+1", goal="hi", language="en")
    assert "error" in res
    assert "TELNYX_API_KEY" in res["error"]
