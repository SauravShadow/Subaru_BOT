# tests/graph/test_email_graph.py
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from app.graph.email.nodes import (
    verify_node, route_after_verify,
    _is_trusted,
)
from app.graph.state import EmailState


def _make_email_state(**overrides) -> EmailState:
    base: EmailState = {
        "email": {
            "from_email": "sauravsubaru@gmail.com",
            "subject": "Deploy my site",
            "body": "Please deploy.",
            "message_id": "msg-001",
            "in_reply_to": None,
            "references": [],
        },
        "is_owner": True,
        "verified": False,
        "plan": "",
        "user_reply": "",
        "execution_result": "",
        "port_used": "",
        "subdomain": "",
        "sent_message_ids": [],
    }
    base.update(overrides)
    return base


def test_is_trusted_owner_email():
    import os
    os.environ["USER_EMAIL"] = "sauravsubaru@gmail.com"
    assert _is_trusted("sauravsubaru@gmail.com") is True


def test_is_trusted_unknown_email():
    assert _is_trusted("stranger@example.com") is False


def test_route_after_verify_trusted():
    state = _make_email_state(is_owner=True)
    assert route_after_verify(state) == "plan_node"


def test_route_after_verify_untrusted():
    state = _make_email_state(is_owner=False)
    assert route_after_verify(state) == "send_challenge_node"


@pytest.mark.asyncio
async def test_verify_node_sets_verified_for_owner():
    state = _make_email_state(is_owner=True)
    result = await verify_node(state, {})
    assert result["verified"] is True


@pytest.mark.asyncio
async def test_verify_node_sets_unverified_for_unknown():
    state = _make_email_state(is_owner=False)
    state["email"] = {**state["email"], "from_email": "stranger@example.com"}
    result = await verify_node(state, {})
    assert result["verified"] is False
