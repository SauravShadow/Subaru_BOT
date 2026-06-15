import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def _event(event_type, payload):
    return {"data": {"event_type": event_type, "payload": payload}}


def test_outbound_call_returns_call_id(client):
    with patch("app.agents.tools.run_outbound_call", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"call_id": "test-call-1", "status": "dialing", "call_control_id": "ctrl-1"}
        resp = client.post("/api/calls/outbound", json={
            "number": "+919876543210",
            "goal": "Book a table for 2 at 7pm",
            "language": "en",
        })
    assert resp.status_code == 200
    assert resp.json()["call_id"] == "test-call-1"
    assert resp.json()["status"] == "dialing"


def test_audio_endpoint_serves_wav(client):
    from app.agents.call_prep import _AUDIO_DIR
    wav_dir = _AUDIO_DIR / "call-xyz"
    wav_dir.mkdir(parents=True, exist_ok=True)
    (wav_dir / "0.wav").write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")
    resp = client.get("/api/calls/audio/call-xyz/0")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/wav"


def test_audio_endpoint_404_for_missing(client):
    resp = client.get("/api/calls/audio/nonexistent-call/0")
    assert resp.status_code == 404


def test_webhook_answered_plays_opening(client):
    from app.services import call_store, telephony
    from app.services.call_store import ScriptEntry
    sess = call_store.create_session("wh-out", "outbound", "+1234", "goal", "en", "en-US-GuyNeural")
    sess.script = [ScriptEntry(idx=0, question="", answer="Hello!", audio_path="/tmp/x/0.wav", used=False)]
    call_store.bind_call_control_id("ctrl-out", "wh-out")

    ev = MagicMock()
    ev.data.event_type = "call.answered"
    ev.data.payload.call_control_id = "ctrl-out"
    ev.data.payload.direction = "outgoing"
    ev.data.payload.client_state = telephony.encode_client_state("wh-out")

    with patch("app.api.router.telephony.verify_webhook", return_value=ev), \
         patch("app.api.router.telephony.play_audio") as mock_play, \
         patch("app.api.router.telephony.start_transcription") as mock_tr:
        resp = client.post("/api/calls/webhook",
                           data=json.dumps(_event("call.answered", {})),
                           headers={"telnyx-signature-ed25519": "s", "telnyx-timestamp": "1"})
    assert resp.status_code == 200
    assert mock_play.called
    assert mock_tr.called


def test_webhook_hangup_ends_session(client):
    from app.services import call_store, telephony
    call_store.create_session("wh-end", "outbound", "+1", "goal", "en", "v")
    call_store.bind_call_control_id("ctrl-end", "wh-end")
    ev = MagicMock()
    ev.data.event_type = "call.hangup"
    ev.data.payload.call_control_id = "ctrl-end"
    ev.data.payload.client_state = telephony.encode_client_state("wh-end")

    with patch("app.api.router.telephony.verify_webhook", return_value=ev), \
         patch("app.api.router.call_store.end_session") as mock_end, \
         patch("app.api.router.cleanup_call_audio") as mock_cleanup:
        resp = client.post("/api/calls/webhook",
                           data=json.dumps(_event("call.hangup", {})),
                           headers={"telnyx-signature-ed25519": "s", "telnyx-timestamp": "1"})
    assert resp.status_code == 200
    assert mock_end.called
