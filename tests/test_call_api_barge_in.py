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


@pytest.mark.asyncio
async def test_finalize_defers_while_speaking():
    from app.api import router
    from app.services import call_store
    s = call_store.create_session("bg", "outbound", "+1", "g", "en", "v")
    call_store.bind_call_control_id("c-bg", "bg")
    s.is_speaking = True
    with patch("app.api.router._respond_to_turn") as mock_resp:
        await router._finalize_turn("bg", "c-bg", "eight pm works")
    assert mock_resp.called is False
    assert s.pending_caller_text == "eight pm works"


@pytest.mark.asyncio
async def test_finalize_accumulates_pending_across_finals_while_speaking():
    """Multiple finals during AI speech must be kept (accumulated), not overwritten —
    otherwise earlier parts of what the caller said are lost (the 'left-out' bug)."""
    from app.api import router
    from app.services import call_store
    s = call_store.create_session("bg2", "outbound", "+1", "g", "en", "v")
    call_store.bind_call_control_id("c-bg2", "bg2")
    s.is_speaking = True
    with patch("app.api.router._respond_to_turn") as mock_resp:
        await router._finalize_turn("bg2", "c-bg2", "i need to reschedule")
        await router._finalize_turn("bg2", "c-bg2", "to next tuesday")
    assert mock_resp.called is False
    assert s.pending_caller_text == "i need to reschedule to next tuesday"


@pytest.mark.asyncio
async def test_finalize_skips_when_call_already_ended():
    """A late transcript flushed after hangup must NOT try to reply (Telnyx 422
    'Call has already ended') — guard on session status."""
    from app.api import router
    from app.services import call_store
    s = call_store.create_session("end1", "outbound", "+1", "g", "en", "v")
    call_store.bind_call_control_id("c-end1", "end1")
    s.status = "ended"
    with patch("app.api.router._respond_to_turn") as mock_resp:
        await router._finalize_turn("end1", "c-end1", "yes it is going good")
    assert mock_resp.called is False


@pytest.mark.asyncio
async def test_finalize_pending_ignores_duplicate_final_while_speaking():
    """A repeated/substring final must not double-append."""
    from app.api import router
    from app.services import call_store
    s = call_store.create_session("bg3", "outbound", "+1", "g", "en", "v")
    call_store.bind_call_control_id("c-bg3", "bg3")
    s.is_speaking = True
    with patch("app.api.router._respond_to_turn"):
        await router._finalize_turn("bg3", "c-bg3", "hello there")
        await router._finalize_turn("bg3", "c-bg3", "hello there")
    assert s.pending_caller_text == "hello there"
