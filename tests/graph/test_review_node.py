import pytest
from pydantic import ValidationError
from app.graph.nodes.review import ReviewDecision, build_review_prompt
from app.graph.state import NexusState


def _make_state(**overrides) -> NexusState:
    base: NexusState = {
        "task": "build REST API",
        "source": "browser",
        "session_id": "test",
        "model": "claude",
        "ceo_response": "Delegated to backend",
        "delegations": [],
        "artifacts": {},
        "worker_results": [{"agent": "backend", "result": "API built at :8090"}],
        "ceo_verdict": "approved",
        "revision_notes": "",
        "worker_progress": {},
    }
    base.update(overrides)
    return base


def test_review_decision_valid_fields():
    d = ReviewDecision(verdict="approved", notes="Good work")
    assert d.verdict == "approved"
    assert d.notes == "Good work"


def test_review_decision_all_verdicts():
    for verdict in ["approved", "revise", "delegate_more", "done"]:
        d = ReviewDecision(verdict=verdict, notes="test")
        assert d.verdict == verdict


def test_review_decision_invalid_verdict_raises():
    with pytest.raises(ValidationError):
        ReviewDecision(verdict="wrong", notes="test")


def test_build_review_prompt_includes_task():
    state = _make_state()
    prompt = build_review_prompt(state)
    assert "build REST API" in prompt


def test_build_review_prompt_includes_worker_result():
    state = _make_state()
    prompt = build_review_prompt(state)
    assert "API built at :8090" in prompt


def test_build_review_prompt_includes_revision_notes():
    state = _make_state(revision_notes="Need better error handling")
    prompt = build_review_prompt(state)
    assert "Need better error handling" in prompt
