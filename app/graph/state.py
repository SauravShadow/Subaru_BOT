"""Shared state TypedDicts for all NEXUS LangGraph graphs."""
import operator
from typing import Annotated, Literal
from typing_extensions import TypedDict
from langgraph.graph import add_messages


class NexusState(TypedDict):
    task: str
    source: Literal["browser", "api"]
    session_id: str
    model: str

    ceo_response: str
    delegations: list[dict]
    artifacts: dict

    worker_results: Annotated[list[dict], operator.add]

    ceo_verdict: Literal["approved", "revise", "delegate_more", "done"]
    revision_notes: str

    worker_progress: dict  # {agent_id: {"step": int, "checkpoints": list[str]}}


class WorkerState(TypedDict):
    task: str
    agent_id: str
    model: str
    artifacts: dict
    messages: Annotated[list, add_messages]
    result: str
    new_artifacts: dict


class EmailState(TypedDict):
    email: dict
    is_owner: bool
    verified: bool
    plan: str
    user_reply: str
    execution_result: str
    port_used: str
    subdomain: str
    sent_message_ids: list[str]
