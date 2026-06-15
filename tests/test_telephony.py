import pytest
from unittest.mock import MagicMock, patch
from app.services.telephony import (
    build_play_and_gather, build_say_and_gather,
    build_hangup, dial_outbound, validate_twilio_request,
)


def test_build_play_and_gather_contains_play_url():
    twiml = build_play_and_gather(
        audio_url="https://example.com/api/calls/audio/abc/0",
        gather_action="https://example.com/api/calls/gather?call_id=abc&turn=1",
    )
    assert "<Play>" in twiml
    assert "audio/abc/0" in twiml
    assert "<Gather" in twiml
    # Twilio XML-escapes the action URL's ampersand (& -> &amp;); check escaping-agnostically
    assert "gather?call_id=abc" in twiml
    assert "turn=1" in twiml


def test_build_say_and_gather_contains_text():
    twiml = build_say_and_gather(
        text="Sorry, I didn't catch that.",
        gather_action="https://example.com/api/calls/gather?call_id=abc&turn=2",
        language="en-US",
    )
    assert "Sorry, I didn't catch that." in twiml
    assert "<Say" in twiml
    assert "<Gather" in twiml


def test_build_hangup():
    twiml = build_hangup(final_text="Thank you, goodbye!")
    assert "<Hangup" in twiml
    assert "Thank you, goodbye!" in twiml


def test_dial_outbound_calls_twilio(monkeypatch):
    import app.config as cfg
    monkeypatch.setattr(cfg, "TWILIO_PHONE_NUMBER", "+15551234567")
    mock_call = MagicMock()
    mock_call.sid = "CA1234567890"
    mock_client = MagicMock()
    mock_client.calls.create.return_value = mock_call

    with patch("app.services.telephony._get_client", return_value=mock_client):
        sid = dial_outbound(
            to="+919876543210",
            call_id="call-abc",
            webhook_url="https://example.com/api/calls/gather?call_id=call-abc&turn=0",
        )

    assert sid == "CA1234567890"
    mock_client.calls.create.assert_called_once()
    call_kwargs = mock_client.calls.create.call_args[1]
    assert call_kwargs["to"] == "+919876543210"
    assert "gather?call_id=call-abc&turn=0" in call_kwargs["url"]


def test_validate_twilio_request_calls_validator():
    with patch("app.services.telephony.RequestValidator") as mock_rv:
        instance = mock_rv.return_value
        instance.validate.return_value = True
        result = validate_twilio_request(
            url="https://example.com/api/calls/gather",
            params={"CallSid": "CA123"},
            signature="abc123",
        )
    assert result is True
