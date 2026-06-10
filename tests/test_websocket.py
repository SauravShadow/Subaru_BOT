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
