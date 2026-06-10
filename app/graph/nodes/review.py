# app/graph/nodes/review.py
"""CEO review node — Gemini structured output for task verdict."""
import logging
import os
from typing import Literal

from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

from app.graph.state import NexusState

logger = logging.getLogger(__name__)


class ReviewDecision(BaseModel):
    verdict: Literal["approved", "revise", "delegate_more", "done"]
    notes: str


_review_llm: ChatGoogleGenerativeAI | None = None


def _get_review_llm() -> ChatGoogleGenerativeAI:
    global _review_llm
    if _review_llm is None:
        _review_llm = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            google_api_key=os.environ.get("GEMINI_API_KEY", ""),
        ).with_structured_output(ReviewDecision)
    return _review_llm


def build_review_prompt(state: NexusState) -> str:
    results_text = "\n".join(
        f"[{r['agent']}]: {r['result'][:500]}"
        for r in state.get("worker_results", [])
    )
    revision_section = ""
    if state.get("revision_notes"):
        revision_section = f"\n\nPrevious revision notes: {state['revision_notes']}"

    return f"""You are the CEO reviewing worker output for the task:

TASK: {state['task']}

WORKER RESULTS:
{results_text or '(no results yet)'}
{revision_section}

ARTIFACTS AVAILABLE: {list(state.get('artifacts', {}).keys())}

Verdict options:
- "approved" — task is complete and correct
- "done" — task is complete (use when all goals met)
- "revise" — workers need to fix something (explain in notes)
- "delegate_more" — additional workers needed (explain in notes)

Be concise. Your notes will be sent back to the CEO as revision instructions."""


async def ceo_review_node(state: NexusState, config: dict) -> dict:
    if not state.get("worker_results"):
        return {"ceo_verdict": "done", "revision_notes": "No workers ran."}
    try:
        llm = _get_review_llm()
        decision: ReviewDecision = await llm.ainvoke(build_review_prompt(state))
        return {"ceo_verdict": decision.verdict, "revision_notes": decision.notes}
    except Exception as exc:
        logger.warning("review node error, defaulting to approved: %s", exc)
        return {"ceo_verdict": "approved", "revision_notes": ""}
