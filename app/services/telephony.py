"""Telnyx Call Control wrapper — outbound dialer, call-control commands, webhook verify."""
import base64
import logging
from typing import Optional

from telnyx import Telnyx
from telnyx.lib.webhook_verification import verify_webhook_signature

from app import config

logger = logging.getLogger(__name__)

_TRANSCRIPTION_TRACKS = "inbound"  # transcribe the remote party, not our own TTS


def _get_client() -> Telnyx:
    if not config.TELNYX_API_KEY:
        raise RuntimeError("TELNYX_API_KEY not configured")
    return Telnyx(api_key=config.TELNYX_API_KEY, public_key=config.TELNYX_PUBLIC_KEY or None)


def encode_client_state(call_id: str) -> str:
    """Telnyx requires client_state to be base64-encoded."""
    return base64.b64encode((call_id or "").encode()).decode()


def decode_client_state(token: Optional[str]) -> str:
    if not token:
        return ""
    try:
        return base64.b64decode(token).decode()
    except Exception:
        return ""


def dial_outbound(to: str, call_id: str, webhook_url: str) -> str:
    """Dial a number via Telnyx Call Control. Returns the call_control_id."""
    if not config.TELNYX_PHONE_NUMBER:
        raise RuntimeError("TELNYX_PHONE_NUMBER not configured")
    if not config.TELNYX_CONNECTION_ID:
        raise RuntimeError("TELNYX_CONNECTION_ID not configured")
    client = _get_client()
    resp = client.calls.dial(
        connection_id=config.TELNYX_CONNECTION_ID,
        to=to,
        from_=config.TELNYX_PHONE_NUMBER,
        webhook_url=webhook_url,
        client_state=encode_client_state(call_id),
    )
    ccid = resp.data.call_control_id
    logger.info("Dialed %s → call_control_id %s", to, ccid)
    return ccid


def answer_call(call_control_id: str, call_id: str = "") -> None:
    _get_client().calls.actions.answer(
        call_control_id, client_state=encode_client_state(call_id)
    )


def play_audio(call_control_id: str, audio_url: str, call_id: str = "") -> None:
    """Play a pre-rendered WAV (Telnyx fetches audio_url)."""
    _get_client().calls.actions.start_playback(
        call_control_id, audio_url=audio_url, client_state=encode_client_state(call_id)
    )


def speak_text(call_control_id: str, text: str, language: str = "en",
               call_id: str = "") -> None:
    """Speak dynamic text via Telnyx TTS."""
    _get_client().calls.actions.speak(
        call_control_id,
        payload=text,
        voice=config.TELNYX_VOICE,
        language=language,
        client_state=encode_client_state(call_id),
    )


def start_transcription(call_control_id: str, language: str = "en") -> None:
    """Begin streaming STT on the remote party's audio (yields call.transcription events).

    NOTE: Telnyx's start_transcription has NO `language` arg (verified against
    telnyx 4.153.0); language is chosen via transcription_engine_config. We keep
    `language` in this wrapper's signature for call-site stability but forward only
    the track selection; the default engine handles language.
    """
    _get_client().calls.actions.start_transcription(
        call_control_id,
        transcription_tracks=_TRANSCRIPTION_TRACKS,
    )


def hangup_call(call_control_id: str) -> None:
    _get_client().calls.actions.hangup(call_control_id)


def verify_webhook(payload: str, headers: dict):
    """Verify the Telnyx Ed25519 signature and return the parsed event.

    When TELNYX_PUBLIC_KEY is configured, the Ed25519 signature is verified via
    Telnyx's verify_webhook_signature helper (raises WebhookVerificationError on an
    invalid/missing signature). When no public key is configured (e.g. signing not
    yet set up), the payload is parsed WITHOUT verification so the webhook still
    functions. Either way the raw body is parsed into a typed event via unsafe_unwrap.
    `payload` is the raw request body (str); `headers` must include
    telnyx-signature-ed25519 and telnyx-timestamp when verifying.
    """
    client = _get_client()
    if config.TELNYX_PUBLIC_KEY:
        verify_webhook_signature(payload, headers, config.TELNYX_PUBLIC_KEY)
    return client.webhooks.unsafe_unwrap(payload)
