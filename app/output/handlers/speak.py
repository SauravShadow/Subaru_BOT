"""SPEAK handler — converts [SPEAK: text | emotion: X] to Bark TTS audio."""
import re
import logging
from typing import Callable, Awaitable

from app.services import bark_client

logger  = logging.getLogger(__name__)
TAG     = "SPEAK"
PATTERN = re.compile(r'\[SPEAK:\s*(.*?)\]', re.DOTALL)

Sender = Callable[[dict], Awaitable[None]]

_VALID_EMOTIONS = {"excited", "calm", "sad", "whisper", "energetic"}


def _parse_args(args: str) -> tuple[str, str]:
    """Split 'text | emotion: X' → (text, emotion). Defaults to calm."""
    lower = args.lower()
    if " | emotion:" in lower:
        idx     = lower.index(" | emotion:")
        text    = args[:idx].strip()
        emotion = args[idx + len(" | emotion:"):].strip().lower()
    else:
        text    = args.strip()
        emotion = "calm"
    if emotion not in _VALID_EMOTIONS:
        emotion = "calm"
    return text, emotion


async def handle(args: str, agent_id: str, send: Sender) -> tuple[str, bool]:
    text, emotion = _parse_args(args)
    audio = await bark_client.speak(text, emotion)
    if audio:
        await send({"type": "audio", "mode": "speak", "data": audio})
        return text, True
    return text, False
