import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def test_inbound_call_returns_twiml_greeting(client):
    with patch("app.api.router.validate_twilio_request", return_value=True):
        resp = client.post("/api/calls/inbound", data={
            "CallSid": "CA_inbound_001",
            "From": "+919876543210",
            "To": "+12025551234",
        })
    assert resp.status_code == 200
    content = resp.text
    assert "<Say" in content or "<Gather" in content
    assert "NEXUS" in content or "nexus" in content.lower()


def test_inbound_respond_returns_twiml(client):
    """After caller speaks, respond returns Say+Gather TwiML."""
    from app.services.call_store import create_session
    create_session("in-001", "inbound", "+919876543210", "inbound call", "en", "en-US-GuyNeural")

    with patch("app.api.router.validate_twilio_request", return_value=True):
        with patch("app.api.router._inbound_agent_reply", new_callable=AsyncMock) as mock_reply:
            mock_reply.return_value = "I can help with that. What else do you need?"
            resp = client.post("/api/calls/inbound/respond", data={
                "CallSid": "CA_inbound_001",
                "SpeechResult": "What is the status of my project?",
                "call_id": "in-001",
            })
    assert resp.status_code == 200
    assert "I can help" in resp.text
