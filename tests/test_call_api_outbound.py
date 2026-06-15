import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def test_outbound_call_returns_call_id(client):
    with patch("app.agents.tools.run_outbound_call", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"call_id": "test-call-1", "status": "dialing", "twilio_sid": "CA123"}
        resp = client.post("/api/calls/outbound", json={
            "number": "+919876543210",
            "goal": "Book a table for 2 at 7pm",
            "language": "en",
        })
    assert resp.status_code == 200
    assert resp.json()["call_id"] == "test-call-1"
    assert resp.json()["status"] == "dialing"


def test_audio_endpoint_serves_wav(client, tmp_path):
    import base64
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


def test_gather_webhook_returns_twiml(client):
    from app.services.call_store import create_session, ScriptEntry
    sess = create_session("wh-test", "outbound", "+1234", "test goal", "en", "en-US-GuyNeural")
    sess.script = [
        ScriptEntry(idx=0, question="", answer="Hello!", audio_path="/tmp/nexus_calls/wh-test/0.wav", used=False),
        ScriptEntry(idx=1, question="How many people?", answer="2 people.", audio_path="/tmp/nexus_calls/wh-test/1.wav", used=False),
    ]
    import os; os.makedirs("/tmp/nexus_calls/wh-test", exist_ok=True)
    open("/tmp/nexus_calls/wh-test/0.wav", "wb").write(b"RIFF")

    with patch("app.api.router.validate_twilio_request", return_value=True):
        resp = client.post("/api/calls/gather", data={
            "CallSid": "CA999",
            "SpeechResult": "",
            "call_id": "wh-test",
            "turn": "0",
        })
    assert resp.status_code == 200
    assert "xml" in resp.headers["content-type"]
