"""Worker subgraph factory — one compiled subgraph per agent."""
import logging
import re

from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END

from app.graph.state import WorkerState
from app.graph.nodes.output import output_node
from app.graph import broadcast
from app.agents.runner import run_agent

logger = logging.getLogger(__name__)

_ARTIFACT_RE = re.compile(r'\[ARTIFACT:\s*([^|]+)\s*\|\s*([^\]]+)\]')


def _extract_artifacts(text: str) -> dict:
    return {
        m.group(1).strip(): m.group(2).strip()
        for m in _ARTIFACT_RE.finditer(text)
    }


def _make_worker_node(agent_id: str):
    async def worker_node(state: WorkerState, config: RunnableConfig) -> dict:
        thread_id = config.get("configurable", {}).get("thread_id", "")
        model = config.get("configurable", {}).get("model", "claude")

        async def send(data: dict) -> None:
            await broadcast.send(thread_id, data)

        result = await run_agent(agent_id, state["task"], send, model)
        # Execute any [MAKE_CALL] action tag backend-agnostically (like [DELEGATE]).
        from app.agents.tools import handle_make_call_tags
        result, _called = await handle_make_call_tags(result, send)
        return {
            "result": result,
            "new_artifacts": _extract_artifacts(result),
        }

    worker_node.__name__ = f"worker_node_{agent_id}"
    return worker_node


def make_worker_graph(agent_id: str):
    """Build and compile a worker subgraph for the given agent."""
    graph = StateGraph(WorkerState)
    graph.add_node("worker_node", _make_worker_node(agent_id))
    graph.add_node("output_node", output_node)
    graph.add_edge(START, "worker_node")
    graph.add_edge("worker_node", "output_node")
    graph.add_edge("output_node", END)
    return graph.compile()
