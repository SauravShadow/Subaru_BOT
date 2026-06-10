# tests/graph/test_ceo_node.py
import pytest
from app.graph.nodes.ceo import parse_delegations_from_response


def test_parse_single_delegation():
    text = "Let's do it!\n[DELEGATE:backend] Build the REST API."
    result = parse_delegations_from_response(text)
    assert result == [{"agent": "backend", "task": "Build the REST API."}]


def test_parse_multiple_delegations():
    text = (
        "Kicking off.\n"
        "[DELEGATE:backend] Build API endpoints.\n"
        "[DELEGATE:frontend] Build the React UI."
    )
    result = parse_delegations_from_response(text)
    assert len(result) == 2
    assert result[0] == {"agent": "backend", "task": "Build API endpoints."}
    assert result[1] == {"agent": "frontend", "task": "Build the React UI."}


def test_parse_no_delegations():
    text = "I'll handle this directly. No workers needed."
    result = parse_delegations_from_response(text)
    assert result == []


def test_inline_mention_not_parsed():
    text = "Say the word and I'll get [DELEGATE:browser] Maya on it."
    result = parse_delegations_from_response(text)
    assert result == []


def test_invalid_agent_skipped():
    text = "[DELEGATE:nonexistent] Some task."
    result = parse_delegations_from_response(text)
    assert result == []


def test_multiline_task_captured():
    text = "[DELEGATE:backend] Build the API.\nMake it RESTful with pagination."
    result = parse_delegations_from_response(text)
    assert len(result) == 1
    assert "pagination" in result[0]["task"]
