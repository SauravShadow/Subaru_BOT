"""CEO wrap-up node — speaks a single summary after workers finish."""
import pytest
from unittest.mock import AsyncMock, patch
from langchain_core.runnables import RunnableConfig


@pytest.mark.asyncio
async def test_wrapup_runs_ceo_and_processes_once():
    from app.graph.nodes import wrapup
    state = {
        "task": "build a books site",
        "worker_results": [{"agent": "backend", "result": "[DONE: API ready]"}],
    }
    config = RunnableConfig(configurable={"thread_id": "t-wrap", "model": "claude"})

    with patch.object(wrapup, "run_claude_agent", new_callable=AsyncMock) as run_ceo, \
         patch.object(wrapup.pipeline, "process", new_callable=AsyncMock) as proc, \
         patch("app.graph.broadcast.send", new_callable=AsyncMock):
        run_ceo.return_value = "[SPEAK: All done — the team shipped the API. | emotion: excited]"
        out = await wrapup.ceo_wrapup_node(state, config)

    run_ceo.assert_called_once()
    assert run_ceo.call_args[0][0] == "ceo"
    proc.assert_called_once()
    assert proc.call_args[0][1] == "ceo"
    assert out["ceo_verdict"] == "done"


@pytest.mark.asyncio
async def test_wrapup_skips_when_no_results():
    from app.graph.nodes import wrapup
    state = {"task": "noop", "worker_results": []}
    config = RunnableConfig(configurable={"thread_id": "t-wrap2", "model": "claude"})

    with patch.object(wrapup, "run_claude_agent", new_callable=AsyncMock) as run_ceo, \
         patch.object(wrapup.pipeline, "process", new_callable=AsyncMock):
        out = await wrapup.ceo_wrapup_node(state, config)

    run_ceo.assert_not_called()
    assert out["ceo_verdict"] == "done"
