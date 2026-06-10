# app/graph/nodes/output.py
"""Output pipeline node — wraps pipeline.process() and extracts artifacts."""
import logging
import re

from langchain_core.runnables import RunnableConfig

from app.graph.state import WorkerState
from app.graph import broadcast
from app.output import pipeline

logger = logging.getLogger(__name__)

_ARTIFACT_RE = re.compile(r'\[ARTIFACT:\s*([^|]+)\s*\|\s*([^\]]+)\]')
_DONE_RE = re.compile(r'\[DONE:\s*([^\]]{1,120})\]')


def _extract_artifacts(text: str) -> dict:
    return {
        m.group(1).strip(): m.group(2).strip()
        for m in _ARTIFACT_RE.finditer(text)
    }


def _extract_summary(text: str) -> str:
    m = _DONE_RE.search(text)
    if m:
        return m.group(1).strip()
    return text.strip()[:120]


async def output_node(state: WorkerState, config: RunnableConfig) -> dict:
    thread_id = config.get("configurable", {}).get("thread_id", "")

    async def send(data: dict) -> None:
        await broadcast.send(thread_id, data)

    result = state.get("result", "")
    agent_id = state["agent_id"]

    try:
        await pipeline.process(result, agent_id, send)
    except Exception as exc:
        logger.warning("output pipeline error for %s: %s", agent_id, exc)

    return {
        "new_artifacts": _extract_artifacts(result),
        "result": result,
    }
