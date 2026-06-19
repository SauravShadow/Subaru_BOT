# app/graph/nodes/ceo.py
"""CEO (Subaru Natsuki) graph node — planning and delegation."""
import logging
import re

from langchain_core.runnables import RunnableConfig

from app.agents.runner import run_claude_agent
from app.graph.state import NexusState
from app.graph import broadcast
from app.output import pipeline
from app.services import goals as goal_store

logger = logging.getLogger(__name__)

_DELEGATE_RE = re.compile(
    r'^\[DELEGATE:(\w+)\]\s*(.*?)(?=^\[DELEGATE:|^\[EMAIL_USER:|\Z)',
    re.DOTALL | re.MULTILINE,
)


def parse_delegations_from_response(text: str) -> list[dict]:
    """Extract [DELEGATE:agent] task blocks; ignore inline mentions."""
    from app.agents.definitions import all_agents
    valid_agents = set(all_agents().keys())
    return [
        {"agent": m.group(1).strip(), "task": m.group(2).strip()}
        for m in _DELEGATE_RE.finditer(text)
        if m.group(1).strip() in valid_agents
    ]


def _build_goal_context() -> str:
    """Compact list of active goals injected into CEO planning prompts."""
    try:
        active = goal_store.get_goals(status="active", limit=10)
    except Exception:
        return ""
    if not active:
        return ""
    lines = []
    for g in active:
        deadline = g.get("deadline")
        suffix = f" (due {deadline})" if deadline else ""
        lines.append(f"  - {g['title']}{suffix}")
    return "ACTIVE GOALS:\n" + "\n".join(lines) + "\n\n"


async def ceo_node(state: NexusState, config: RunnableConfig) -> dict:
    thread_id = config.get("configurable", {}).get("thread_id", "")
    model = config.get("configurable", {}).get("model", "claude")

    async def send(data: dict) -> None:
        await broadcast.send(thread_id, data)

    task = state["task"]
    goal_context = _build_goal_context()
    if goal_context:
        task = f"{goal_context}{task}"
    if state.get("revision_notes"):
        task = f"{task}\n\n[REVISION REQUESTED]\n{state['revision_notes']}"

    response = await run_claude_agent("ceo", task, send)
    await pipeline.process(response, "ceo", send)
    delegations = parse_delegations_from_response(response)

    return {
        "ceo_response": response,
        "delegations": delegations,
    }
