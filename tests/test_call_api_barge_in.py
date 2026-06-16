import json, pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)

def _ev(client, etype, ccid, cid, **payload):
    from app.services import telephony
    ev = MagicMock()
    ev.data.event_type = etype
    ev.data.payload.call_control_id = ccid
    ev.data.payload.direction = "outgoing"
    ev.data.payload.client_state = telephony.encode_client_state(cid)
    for k, v in payload.items():
        setattr(ev.data.payload, k, v)
    with patch("app.api.router.telephony.verify_webhook", return_value=ev):
        return client.post("/api/calls/webhook", data=json.dumps({"data": {}}),
                           headers={"telnyx-signature-ed25519": "s", "telnyx-timestamp": "1"})

def test_speak_started_ended_toggles_is_speaking(client):
    from app.services import call_store
    call_store.create_session("spk", "outbound", "+1", "g", "en", "v")
    call_store.bind_call_control_id("c-spk", "spk")
    _ev(client, "call.speak.started", "c-spk", "spk")
    assert call_store.get_session("spk").is_speaking is True
    _ev(client, "call.speak.ended", "c-spk", "spk")
    assert call_store.get_session("spk").is_speaking is False
