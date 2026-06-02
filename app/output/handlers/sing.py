"""SING handler — converts [SING: lyrics | style: X] to Bark singing audio."""
import re
import logging
from typing import Callable, Awaitable

from app.services import bark_client

logger  = logging.getLogger(__name__)
TAG     = "SING"
PATTERN = re.compile(r'\[SING:\s*(.*?)\]', re.DOTALL)

Sender = Callable[[dict], Awaitable[None]]


def _parse_sing_args(args: str) -> tuple[str, str]:
    """Split 'lyrics | style: X' → (lyrics, style). Defaults to expressive."""
    if " | style:" in args:
        parts  = args.split(" | style:", 1)
        lyrics = parts[0].strip()
        style  = parts[1].strip()
    else:
        lyrics = args.strip()
        style  = "expressive"
    return lyrics, style


async def handle(args: str, agent_id: str, send: Sender) -> tuple[str, bool]:
    lyrics, style = _parse_sing_args(args)
    audio = await bark_client.sing(lyrics, style)
    if audio:
        await send({"type": "audio", "mode": "sing", "data": audio})
        return "", True
    # Bark unavailable — show lyrics as text
    return lyrics, False
