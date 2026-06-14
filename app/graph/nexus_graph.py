# app/graph/nexus_graph.py
"""Compiled nexus_graph — WebSocket-driven real-time orchestration graph."""
import logging

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

from app.graph.state import NexusState
from app.graph.nodes.ceo import ceo_node
from app.graph.nodes.wrapup import ceo_wrapup_node
from app.graph.workers.base import make_worker_graph

logger = logging.getLogger(__name__)

_KNOWN_AGENTS = ["backend", "frontend", "qa", "devops", "browser"]
_worker_subgraphs: dict = {}


def _get_worker_subgraph(agent_id: str):
    if agent_id not in _worker_subgraphs:
        _worker_subgraphs[agent_id] = make_worker_graph(agent_id)
    return _worker_subgraphs[agent_id]


def route_after_ceo(state: NexusState):
    """Fan out to worker subgraphs or end if CEO handled directly."""
    delegations = state.get("delegations", [])
    if not delegations:
        return END
    return [
        Send(
            d["agent"],
            {
                "task": d["task"],
                "agent_id": d["agent"],
                "model": state["model"],
                "artifacts": state.get("artifacts", {}),
                "messages": [],
                "result": "",
                "new_artifacts": {},
            },
        )
        for d in delegations
        if d["agent"] in _KNOWN_AGENTS
    ]


def build_nexus_graph(checkpointer):
    graph = StateGraph(NexusState)

    graph.add_node("ceo_node", ceo_node)
    graph.add_node("ceo_wrapup_node", ceo_wrapup_node)

    for agent_id in _KNOWN_AGENTS:
        graph.add_node(agent_id, _get_worker_subgraph(agent_id))

    graph.add_edge(START, "ceo_node")
    graph.add_conditional_edges("ceo_node", route_after_ceo, [END] + _KNOWN_AGENTS)

    for agent_id in _KNOWN_AGENTS:
        graph.add_edge(agent_id, "ceo_wrapup_node")

    graph.add_edge("ceo_wrapup_node", END)

    return graph.compile(checkpointer=checkpointer)
