import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from langgraph.checkpoint.memory import MemorySaver
from app.graph.workers.base import make_worker_graph, _extract_artifacts


def test_extract_artifacts_single():
    text = "Done! [ARTIFACT: api_base | http://localhost:8090]"
    result = _extract_artifacts(text)
    assert result == {"api_base": "http://localhost:8090"}


def test_extract_artifacts_multiple():
    text = "[ARTIFACT: port | 8090] and [ARTIFACT: db_url | sqlite:///app.db]"
    result = _extract_artifacts(text)
    assert result["port"] == "8090"
    assert result["db_url"] == "sqlite:///app.db"


def test_extract_artifacts_empty():
    text = "Task complete. No artifacts."
    result = _extract_artifacts(text)
    assert result == {}


@pytest.mark.asyncio
async def test_worker_graph_runs_successfully():
    with patch("app.graph.workers.base.run_agent", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "API built. [ARTIFACT: api_base | http://localhost:8090]"
        with patch("app.output.pipeline.process", new_callable=AsyncMock):
            graph = make_worker_graph("backend")
            config = {"configurable": {"thread_id": "test-001", "model": "claude"}}
            state = {
                "task": "build the API",
                "agent_id": "backend",
                "model": "claude",
                "artifacts": {},
                "messages": [],
                "result": "",
                "new_artifacts": {},
            }
            result = await graph.ainvoke(state, config)
            assert mock_run.called
            assert result["new_artifacts"].get("api_base") == "http://localhost:8090"
