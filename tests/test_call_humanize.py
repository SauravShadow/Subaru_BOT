import time
from app.api import router

def test_normalize():
    assert router._normalize("  Hello,  World! ") == "hello world"
    assert router._normalize("") == ""

def test_silence_should_fire():
    class S:
        last_interim_text = "book a table"
        last_interim_at = 1000.0
        responded_text = ""
    s = S()
    assert router._silence_should_fire(s, now=1000.75) is True
    assert router._silence_should_fire(s, now=1000.40) is False
    s.responded_text = "book a table"
    assert router._silence_should_fire(s, now=1002.0) is False
    s.responded_text = ""
    s.last_interim_text = ""
    assert router._silence_should_fire(s, now=1002.0) is False

def test_pick_filler_returns_short_phrase():
    from app.agents.call_prep import pick_filler
    f = pick_filler()
    assert isinstance(f, str) and 0 < len(f) <= 40

def test_sanitize_ssml_wraps_and_detects():
    from app.agents.call_prep import sanitize_ssml
    payload, ptype = sanitize_ssml('Sure<break time="200ms"/> now.')
    assert ptype == "ssml" and payload.startswith("<speak>") and payload.endswith("</speak>")
    payload2, ptype2 = sanitize_ssml("just plain text")
    assert ptype2 == "text" and payload2 == "just plain text"
    payload3, ptype3 = sanitize_ssml("<speak>bad <oops></speak>")
    assert ptype3 == "text"   # malformed XML -> fall back to plain
