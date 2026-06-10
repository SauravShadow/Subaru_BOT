# app/graph/nodes/ceo.py
"""CEO (Subaru Natsuki) graph node — planning and delegation."""
import logging
import re

from app.agents.runner import run_claude_agent
from app.graph.state import NexusState
from app.graph import broadcast

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


async def ceo_node(state: NexusState, config: dict) -> dict:
    thread_id = config.get("configurable", {}).get("thread_id", "")
    model = config.get("configurable", {}).get("model", "claude")

    async def send(data: dict) -> None:
        await broadcast.send(thread_id, data)

    task = state["task"]
    if state.get("revision_notes"):
        task = f"{task}\n\n[REVISION REQUESTED]\n{state['revision_notes']}"

    response = await run_claude_agent("ceo", task, send)
    delegations = parse_delegations_from_response(response)

    return {
        "ceo_response": response,
        "delegations": delegations,
    }
