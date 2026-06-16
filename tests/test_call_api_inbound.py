import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def _post(client, ev):
    return client.post("/api/calls/webhook",
                       data=json.dumps({"data": {}}),
                       headers={"telnyx-signature-ed25519": "s", "telnyx-timestamp": "1"})


def test_inbound_initiated_answers_call(client):
    from app.services import telephony
    ev = MagicMock()
    ev.data.event_type = "call.initiated"
    ev.data.payload.call_control_id = "ctrl-in"
    ev.data.payload.direction = "incoming"
    ev.data.payload.from_ = "+919876543210"
    ev.data.payload.client_state = ""

    with patch("app.api.router.telephony.verify_webhook", return_value=ev), \
         patch("app.api.router.telephony.answer_call") as mock_answer:
        resp = _post(client, ev)
    assert resp.status_code == 200
    assert mock_answer.called
    from app.services import call_store
    assert call_store.get_session("ctrl-in") is not None


def test_inbound_answered_speaks_greeting(client):
    from app.services import call_store, telephony
    call_store.create_session("ctrl-in2", "inbound", "+1", "inbound call", "en", "v")
    call_store.bind_call_control_id("ctrl-in2", "ctrl-in2")
    ev = MagicMock()
    ev.data.event_type = "call.answered"
    ev.data.payload.call_control_id = "ctrl-in2"
    ev.data.payload.direction = "incoming"
    ev.data.payload.client_state = telephony.encode_client_state("ctrl-in2")

    with patch("app.api.router.telephony.verify_webhook", return_value=ev), \
         patch("app.api.router.telephony.speak_text") as mock_speak, \
         patch("app.api.router.telephony.start_transcription"):
        resp = _post(client, ev)
    assert resp.status_code == 200
    assert mock_speak.called
    assert "NEXUS" in mock_speak.call_args[0][1] or "NEXUS" in str(mock_speak.call_args)


def test_transcription_drives_reply(client):
    from app.services import call_store, telephony
    call_store.create_session("ctrl-in3", "inbound", "+1", "inbound call", "en", "v")
    call_store.bind_call_control_id("ctrl-in3", "ctrl-in3")
    ev = MagicMock()
    ev.data.event_type = "call.transcription"
    ev.data.payload.call_control_id = "ctrl-in3"
    ev.data.payload.direction = "incoming"
    ev.data.payload.client_state = telephony.encode_client_state("ctrl-in3")
    ev.data.payload.transcription_data.transcript = "What is my project status?"
    ev.data.payload.transcription_data.is_final = True

    with patch("app.api.router.telephony.verify_webhook", return_value=ev), \
         patch("app.api.router._live_reply", new_callable=AsyncMock) as mock_reply, \
         patch("app.api.router.telephony.speak_text") as mock_speak:
        mock_reply.return_value = "I can help with that."
        resp = _post(client, ev)
    assert resp.status_code == 200
    assert mock_speak.called
