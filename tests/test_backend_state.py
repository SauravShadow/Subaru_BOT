import pytest
from datetime import datetime, timedelta


def _fresh():
    """Return the backend_state module with reset globals."""
    import app.agents.backend_state as m
    m._quota_exhausted_at = None
    m._gemini_failed_at   = None
    m._current_backend    = "claude"
    return m


def test_initial_state_uses_claude():
    m = _fresh()
    assert m.get_current_backend() == "claude"
    assert m.should_use_claude() is True
    assert m.should_use_gemini() is False


def test_mark_quota_exhausted_switches_to_gemini():
    m = _fresh()
    changed = m.mark_quota_exhausted()
    assert changed is True
    assert m.get_current_backend() == "gemini"
    assert m.should_use_claude() is False
    assert m.should_use_gemini() is True


def test_mark_gemini_failed_switches_to_tgpt():
    m = _fresh()
    m.mark_quota_exhausted()
    changed = m.mark_gemini_failed()
    assert changed is True
    assert m.get_current_backend() == "tgpt"
    assert m.should_use_gemini() is False


def test_claude_recovery_clears_gemini_too():
    m = _fresh()
    m.mark_quota_exhausted()
    m.mark_gemini_failed()
    changed = m.mark_claude_recovered()
    assert changed is True
    assert m.get_current_backend() == "claude"
    assert m.should_use_claude() is True
    assert m.should_use_gemini() is False


def test_no_duplicate_change_events():
    m = _fresh()
    m.mark_quota_exhausted()
    changed = m.mark_quota_exhausted()  # second call
    assert changed is False


def test_gemini_retry_window():
    m = _fresh()
    m.mark_quota_exhausted()
    m.mark_gemini_failed()
    # Fake gemini_failed_at to be old enough (now in seconds, not minutes)
    m._gemini_failed_at = datetime.now() - timedelta(seconds=m.GEMINI_RETRY_SECONDS + 1)
    assert m.should_use_gemini() is True


def test_status_dict_includes_all_tiers():
    m = _fresh()
    d = m.status_dict()
    assert "backend" in d
    assert "quota_ok" in d
    assert "gemini_ok" in d
