import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.call_store import ScriptEntry
from app.agents.call_prep import match_utterance, generate_script_prompt


def _entry(idx, question, answer):
    return ScriptEntry(idx=idx, question=question, answer=answer, audio_path="", used=False)


def test_match_utterance_exact():
    script = [
        _entry(0, "How many people?", "2 people please."),
        _entry(1, "What time would you like?", "7pm please."),
    ]
    match = match_utterance("how many people", script)
    assert match is not None
    assert match.idx == 0


def test_match_utterance_fuzzy():
    script = [
        _entry(0, "Can I get your name?", "Sure, it's Saurav."),
        _entry(1, "Any dietary restrictions?", "No restrictions, thank you."),
    ]
    match = match_utterance("what is your name please", script)
    assert match is not None
    assert match.idx == 0


def test_match_utterance_no_match():
    script = [
        _entry(0, "How many people?", "2 people please."),
    ]
    match = match_utterance("please hold the line", script, threshold=0.6)
    assert match is None


def test_match_utterance_skips_used():
    script = [
        _entry(0, "How many people?", "2 people."),
        _entry(1, "What time?", "7pm."),
    ]
    script[0].used = True
    match = match_utterance("how many people", script)
    # Should not match idx=0 (used), fallback to no match or idx=1
    assert match is None or match.idx != 0


def test_generate_script_prompt_contains_goal():
    prompt = generate_script_prompt(
        goal="Book a table for 2 at 7pm at Spice Garden restaurant",
        language="en",
    )
    assert "Book a table" in prompt
    assert "JSON" in prompt
