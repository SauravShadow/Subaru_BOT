# app/graph/nodes/wrapup.py
"""CEO wrap-up node — speaks a single summary of worker results, then ends."""
import logging

from langchain_core.runnables import RunnableConfig

from app.agents.runner import run_claude_agent
from app.graph.state import NexusState
from app.graph import broadcast
from app.output import pipeline

logger = logging.getLogger(__name__)


async def ceo_wrapup_node(state: NexusState, config: RunnableConfig) -> dict:
    thread_id = config.get("configurable", {}).get("thread_id", "")

    async def send(data: dict) -> None:
        await broadcast.send(thread_id, data)

    results = state.get("worker_results", [])
    if not results:
        return {"ceo_verdict": "done", "revision_notes": ""}

    results_text = "\n".join(
        f"[{r['agent']}]: {r['result'][:500]}" for r in results
    )
    prompt = (
        f"The team just finished working on this task:\n\nTASK: {state['task']}\n\n"
        f"WORKER RESULTS:\n{results_text}\n\n"
        "Give the user a short, warm spoken wrap-up (2-3 sentences) of what the "
        "team accomplished. Speak it with a [SPEAK: ... | emotion: ...] tag."
    )
    response = await run_claude_agent("ceo", prompt, send)
    await pipeline.process(response, "ceo", send)
    return {"ceo_verdict": "done", "revision_notes": "", "ceo_response": response}
