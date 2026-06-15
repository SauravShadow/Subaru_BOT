import base64
import pytest
from unittest.mock import MagicMock, patch

import app.config as cfg
from app.services import telephony


def test_encode_decode_client_state_roundtrips():
    token = telephony.encode_client_state("call-abc")
    assert base64.b64decode(token).decode() == "call-abc"
    assert telephony.decode_client_state(token) == "call-abc"


def test_decode_client_state_handles_empty():
    assert telephony.decode_client_state("") == ""
    assert telephony.decode_client_state(None) == ""


def test_dial_outbound_calls_telnyx(monkeypatch):
    monkeypatch.setattr(cfg, "TELNYX_PHONE_NUMBER", "+15551234567")
    monkeypatch.setattr(cfg, "TELNYX_CONNECTION_ID", "conn-1")
    mock_resp = MagicMock()
    mock_resp.data.call_control_id = "ctrl-xyz"
    mock_client = MagicMock()
    mock_client.calls.dial.return_value = mock_resp

    with patch("app.services.telephony._get_client", return_value=mock_client):
        ccid = telephony.dial_outbound(
            to="+919876543210",
            call_id="call-abc",
            webhook_url="https://example.com/api/calls/webhook",
        )

    assert ccid == "ctrl-xyz"
    kwargs = mock_client.calls.dial.call_args[1]
    assert kwargs["to"] == "+919876543210"
    assert kwargs["from_"] == "+15551234567"
    assert kwargs["connection_id"] == "conn-1"
    assert kwargs["webhook_url"] == "https://example.com/api/calls/webhook"
    assert telephony.decode_client_state(kwargs["client_state"]) == "call-abc"


def test_play_audio_issues_start_playback():
    mock_client = MagicMock()
    with patch("app.services.telephony._get_client", return_value=mock_client):
        telephony.play_audio("ctrl-1", "https://x/audio/c/0", call_id="c")
    kwargs = mock_client.calls.actions.start_playback.call_args[1]
    args = mock_client.calls.actions.start_playback.call_args[0]
    assert args[0] == "ctrl-1"
    assert kwargs["audio_url"] == "https://x/audio/c/0"


def test_speak_text_issues_speak():
    mock_client = MagicMock()
    with patch("app.services.telephony._get_client", return_value=mock_client):
        telephony.speak_text("ctrl-1", "Hello there", language="en", call_id="c")
    args = mock_client.calls.actions.speak.call_args[0]
    kwargs = mock_client.calls.actions.speak.call_args[1]
    assert args[0] == "ctrl-1"
    assert kwargs["payload"] == "Hello there"
    assert kwargs["language"] == "en"


def test_answer_and_hangup_and_transcription():
    mock_client = MagicMock()
    with patch("app.services.telephony._get_client", return_value=mock_client):
        telephony.answer_call("ctrl-1", call_id="c")
        telephony.start_transcription("ctrl-1", language="en")
        telephony.hangup_call("ctrl-1")
    assert mock_client.calls.actions.answer.call_args[0][0] == "ctrl-1"
    assert mock_client.calls.actions.start_transcription.call_args[0][0] == "ctrl-1"
    assert mock_client.calls.actions.hangup.call_args[0][0] == "ctrl-1"


def test_verify_webhook_returns_event(monkeypatch):
    monkeypatch.setattr(cfg, "TELNYX_PUBLIC_KEY", "pub-key")
    mock_event = MagicMock()
    mock_client = MagicMock()
    mock_client.webhooks.unwrap.return_value = mock_event
    with patch("app.services.telephony._get_client", return_value=mock_client):
        ev = telephony.verify_webhook('{"x":1}', {"telnyx-signature-ed25519": "s"})
    assert ev is mock_event
    kwargs = mock_client.webhooks.unwrap.call_args[1]
    assert kwargs["key"] == "pub-key"
