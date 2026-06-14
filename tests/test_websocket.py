"""Tests for browser-result relay helpers in app.api.websocket (LangGraph rewrite)."""
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_handle_browser_result_broadcasts_event():
    from app.api import websocket as ws_module

    with patch.object(ws_module, "broadcast_event", new_callable=AsyncMock) as mock_broadcast:
        await ws_module.handle_browser_result({
            "type": "browser_result", "agent_id": "maya", "slot_id": 2,
            "tool": "browser_apply",
            "result": "Stripe — Backend Engineer: applied (https://linkedin.com/jobs/123)",
        }, model="claude")

    mock_broadcast.assert_called_once()
    assert mock_broadcast.call_args[0][0] == {
        "type": "browser_result", "agent_id": "maya", "slot_id": 2,
        "tool": "browser_apply",
        "result": "Stripe — Backend Engineer: applied (https://linkedin.com/jobs/123)",
    }


@pytest.mark.asyncio
async def test_handle_browser_blocker_resolved_broadcasts_event():
    from app.api import websocket as ws_module

    payload = {
        "type": "browser_blocker_resolved",
        "agent_id": "maya",
        "site": "naukri.com",
        "blocker_type": "login_wall",
        "resolution": "user took over in interactive mode and resumed manually",
        "timestamp": "2026-06-08T10:00:00",
    }

    with patch.object(ws_module, "broadcast_event", new_callable=AsyncMock) as mock_broadcast:
        await ws_module.handle_browser_blocker_resolved(payload)

    mock_broadcast.assert_called_once_with(payload)


@pytest.mark.asyncio
async def test_run_direct_calls_worker_and_broadcasts_lifecycle(monkeypatch):
    from app.api import websocket as ws_module

    events = []

    async def fake_broadcast(data):
        events.append(data)

    called = {}

    async def fake_run_agent(agent_id, prompt, send, model="claude"):
        called["agent"] = agent_id
        called["prompt"] = prompt
        return "done"

    monkeypatch.setattr(ws_module, "broadcast_event", fake_broadcast)
    import app.agents.runner as runner
    monkeypatch.setattr(runner, "run_agent", fake_run_agent)

    await ws_module._run_direct("backend", "fix the API", "claude")

    assert called["agent"] == "backend"
    types = [e["type"] for e in events]
    assert types[0] == "delegation"
    assert types[-1] == "worker_done"


@pytest.mark.asyncio
async def test_run_direct_rejects_unknown_agent(monkeypatch):
    from app.api import websocket as ws_module

    events = []

    async def fake_broadcast(data):
        events.append(data)

    monkeypatch.setattr(ws_module, "broadcast_event", fake_broadcast)
    await ws_module._run_direct("nonexistent_agent_xyz", "hi", "claude")
    assert events and events[0]["type"] == "error"


def test_translate_event_ignores_chat_model_stream():
    from app.api.websocket import _translate_event

    class _Chunk:
        content = "some streamed text"

    event = {
        "event": "on_chat_model_stream",
        "name": "ChatGoogleGenerativeAI",
        "metadata": {},
        "data": {"chunk": _Chunk()},
    }
    assert _translate_event(event, "t1") is None
