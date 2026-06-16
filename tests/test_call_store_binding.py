from app.services import call_store


def test_bind_and_resolve_call_control_id():
    call_store.create_session("cid-1", "outbound", "+1", "goal", "en", "v")
    call_store.bind_call_control_id("ctrl-1", "cid-1")
    assert call_store.resolve_call_id("ctrl-1") == "cid-1"


def test_resolve_unknown_returns_none():
    assert call_store.resolve_call_id("nope") is None


def test_session_has_call_control_id_field():
    sess = call_store.create_session("cid-2", "outbound", "+1", "goal", "en", "v")
    assert sess.telnyx_call_control_id is None


def test_session_has_live_turn_fields():
    s = call_store.create_session("cid-live", "outbound", "+1", "g", "en", "v")
    assert s.is_speaking is False
    assert s.last_interim_text == ""
    assert s.last_interim_at == 0.0
    assert s.pending_caller_text is None
    assert s.responded_text == ""
