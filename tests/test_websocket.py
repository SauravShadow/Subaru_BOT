"""Tests for the browser-result feedback loop in app.api.websocket."""
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_handle_browser_result_records_and_reinvokes_agent():
    from app.api import websocket as ws_module

    with patch.object(ws_module, "broadcast_event", new_callable=AsyncMock) as mock_broadcast, \
         patch.object(ws_module.state, "record") as mock_record, \
         patch.object(ws_module, "run_agent", new_callable=AsyncMock,
                      return_value="[DONE: 1 applied — Stripe backend role]") as mock_run_agent, \
         patch.object(ws_module.deleg_svc, "clean_response", side_effect=lambda x: x):

        await ws_module.handle_browser_result({
            "type": "browser_result", "agent_id": "maya", "slot_id": 2,
            "tool": "browser_apply",
            "result": "Stripe — Backend Engineer: applied (https://linkedin.com/jobs/123)",
        })

    # state.record called once for the synthetic user turn, once for Maya's reply
    assert mock_record.call_count == 2
    user_call, assistant_call = mock_record.call_args_list
    assert user_call.args[0] == "maya"
    assert user_call.args[1] == "user"
    assert "(slot 2)" in user_call.args[2]
    assert "Stripe — Backend Engineer: applied" in user_call.args[2]
    assert assistant_call.args == ("maya", "assistant", "[DONE: 1 applied — Stripe backend role]")

    mock_run_agent.assert_called_once()
    assert mock_run_agent.call_args[0][0] == "maya"
    assert "(slot 2)" in mock_run_agent.call_args[0][1]

    # broadcast_event used for thinking/done so the dashboard reflects the re-invocation
    broadcast_types = [c.args[0]["type"] for c in mock_broadcast.call_args_list]
    assert "thinking" in broadcast_types
    assert "done" in broadcast_types


@pytest.mark.asyncio
async def test_handle_browser_blocker_resolved_persists_a_retrievable_memory(tmp_path):
    from app.api import websocket as ws_module
    from app.services import memory as mem_svc

    original_db = mem_svc.DB_PATH
    mem_svc.DB_PATH = tmp_path / "test_memory.db"
    mem_svc.init_db()
    try:
        await ws_module.handle_browser_blocker_resolved({
            "type": "browser_blocker_resolved",
            "agent_id": "maya",
            "site": "naukri.com",
            "blocker_type": "login_wall",
            "resolution": "user took over in interactive mode and resumed manually",
            "timestamp": "2026-06-08T10:00:00",
        })
        results = mem_svc.get_relevant_memories("maya", "naukri.com login wall")
        assert any("naukri.com" in r and "login_wall" in r for r in results)
    finally:
        mem_svc.DB_PATH = original_db
