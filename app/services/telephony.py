"""Twilio SDK wrapper — TwiML builders, outbound dialer, webhook validator."""
import logging
from typing import Optional

from twilio.rest import Client
from twilio.request_validator import RequestValidator
from twilio.twiml.voice_response import VoiceResponse, Gather, Play, Say

from app import config

logger = logging.getLogger(__name__)

_GATHER_TIMEOUT  = 8    # seconds of silence before timeout
_GATHER_LANGUAGE = "en-US"


def _get_client() -> Client:
    if not config.TWILIO_ACCOUNT_SID or not config.TWILIO_AUTH_TOKEN:
        raise RuntimeError("TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN not configured")
    return Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)


def build_play_and_gather(audio_url: str, gather_action: str,
                          language: str = _GATHER_LANGUAGE) -> str:
    """TwiML: play pre-rendered audio then listen for speech."""
    resp = VoiceResponse()
    gather = Gather(
        input="speech",
        timeout=_GATHER_TIMEOUT,
        action=gather_action,
        method="POST",
        language=language,
    )
    gather.play(audio_url)
    resp.append(gather)
    return str(resp)


def build_say_and_gather(text: str, gather_action: str,
                         language: str = _GATHER_LANGUAGE) -> str:
    """TwiML: speak text via Twilio TTS then listen for speech."""
    resp = VoiceResponse()
    gather = Gather(
        input="speech",
        timeout=_GATHER_TIMEOUT,
        action=gather_action,
        method="POST",
        language=language,
    )
    gather.say(text, language=language)
    resp.append(gather)
    return str(resp)


def build_hangup(final_text: str = "", language: str = _GATHER_LANGUAGE) -> str:
    """TwiML: optionally say a closing line then hang up."""
    resp = VoiceResponse()
    if final_text:
        resp.say(final_text, language=language)
    resp.hangup()
    return str(resp)


def dial_outbound(to: str, call_id: str, webhook_url: str) -> str:
    """Dial a number via Twilio. Returns the call SID."""
    client = _get_client()
    if not config.TWILIO_PHONE_NUMBER:
        raise RuntimeError("TWILIO_PHONE_NUMBER not configured")
    call = client.calls.create(
        to=to,
        from_=config.TWILIO_PHONE_NUMBER,
        url=webhook_url,
        method="POST",
    )
    logger.info("Dialed %s → SID %s", to, call.sid)
    return call.sid


def validate_twilio_request(url: str, params: dict, signature: str) -> bool:
    """Verify the X-Twilio-Signature header to confirm the webhook is genuine."""
    validator = RequestValidator(config.TWILIO_AUTH_TOKEN)
    return validator.validate(url, params, signature)
