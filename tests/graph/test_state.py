# tests/graph/test_state.py
import operator
import pytest
from typing import get_type_hints
from app.graph.state import NexusState, WorkerState, EmailState

def test_nexus_state_has_required_keys():
    state: NexusState = {
        "task": "build an API",
        "source": "browser",
        "session_id": "test-123",
        "model": "claude",
        "ceo_response": "",
        "delegations": [],
        "artifacts": {},
        "worker_results": [],
        "ceo_verdict": "approved",
        "revision_notes": "",
        "worker_progress": {},
    }
    assert state["task"] == "build an API"
    assert state["worker_results"] == []
    assert state["worker_progress"] == {}

def test_worker_state_has_required_keys():
    state: WorkerState = {
        "task": "build routes",
        "agent_id": "backend",
        "model": "claude",
        "artifacts": {},
        "messages": [],
        "result": "",
        "new_artifacts": {},
    }
    assert state["agent_id"] == "backend"
    assert state["messages"] == []

def test_email_state_has_required_keys():
    state: EmailState = {
        "email": {"from_email": "user@test.com", "subject": "test"},
        "is_owner": True,
        "verified": False,
        "plan": "",
        "user_reply": "",
        "execution_result": "",
        "port_used": "",
        "subdomain": "",
        "sent_message_ids": [],
    }
    assert state["is_owner"] is True
    assert state["sent_message_ids"] == []
