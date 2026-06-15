import pytest
from datetime import datetime
from app.services.call_store import (
    CallSession, ScriptEntry, Turn,
    create_session, get_session, add_turn,
    end_session, search_calls, get_call_history,
)
# NOTE: ScriptEntry is the canonical definition — call_prep.py imports from here


def _make_session(call_id="test-123"):
    return create_session(
        call_id=call_id,
        direction="outbound",
        number="+919876543210",
        goal="Book a table for 2 at 7pm",
        language="en",
        speaker="en-US-GuyNeural",
    )


def test_create_and_get_session():
    sess = _make_session("sess-1")
    assert sess.call_id == "sess-1"
    assert sess.status == "prep"
    retrieved = get_session("sess-1")
    assert retrieved is not None
    assert retrieved.number == "+919876543210"


def test_add_turn():
    _make_session("sess-2")
    add_turn("sess-2", speaker="them", text="Hello how can I help?")
    add_turn("sess-2", speaker="nexus", text="Hi, booking table for 2.")
    sess = get_session("sess-2")
    assert len(sess.transcript) == 2
    assert sess.transcript[0].speaker == "them"
    assert sess.transcript[1].text == "Hi, booking table for 2."


def test_end_session_writes_to_sqlite(tmp_path, monkeypatch):
    import app.config as cfg
    monkeypatch.setattr(cfg, "MEMORY_DB", tmp_path / "test.db")
    from app.services import call_store
    monkeypatch.setattr(call_store, "_init_db", lambda: call_store._init_db_path(tmp_path / "test.db"))
    call_store._init_db()

    _make_session("sess-3")
    add_turn("sess-3", "them", "How many people?")
    add_turn("sess-3", "nexus", "2 people please.")
    end_session("sess-3", outcome="success", summary="Table booked for 2 at 7pm.")

    assert get_session("sess-3") is None  # removed from in-memory

    history = get_call_history()
    assert any(c["id"] == "sess-3" for c in history)
    row = next(c for c in history if c["id"] == "sess-3")
    assert row["summary"] == "Table booked for 2 at 7pm."


def test_search_calls(tmp_path, monkeypatch):
    import app.config as cfg
    monkeypatch.setattr(cfg, "MEMORY_DB", tmp_path / "test2.db")
    from app.services import call_store
    call_store._init_db()

    create_session("s4", "outbound", "+1234567890", "Book flight to Mumbai", "en", "en-US-GuyNeural")
    add_turn("s4", "them", "What date?")
    add_turn("s4", "nexus", "20th June please.")
    end_session("s4", "success", "Flight enquiry done.")

    results = search_calls("Mumbai")
    assert any(r["id"] == "s4" for r in results)
