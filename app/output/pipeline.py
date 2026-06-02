"""OutputPipeline — post-processes every LLM response.

Scans for registered output tags, dispatches each to its handler,
strips tags from the display text, and sends a single assistant message
with bark_ok flag for frontend TTS fallback logic.
"""
import logging
from typing import Callable, Awaitable

from app.output import registry as _reg

logger = logging.getLogger(__name__)

Sender = Callable[[dict], Awaitable[None]]


async def process(text: str, agent_id: str, send: Sender) -> str:
    """
    Process all registered output tags in `text`.

    For each tag found:
      - Calls handler.handle(args, agent_id, send)
      - handler returns (display_text, bark_ok)
      - Replaces the raw tag in display with display_text
      - Tracks whether any handler delivered audio (bark_ok)

    Sends a single {type: "assistant"} message with bark_ok flag.
    Returns the cleaned display text.
    """
    reg = _reg.get_registry()
    _reg.REGISTRY.update(reg)

    display = text
    bark_ok = False

    for tag_name, handler in reg.items():
        matches = list(handler.PATTERN.finditer(text))
        for match in matches:
            try:
                # Handlers with 2 capture groups (e.g. EMAIL_USER) get groups joined by \x00
                if match.lastindex and match.lastindex >= 2:
                    handler_args = match.group(1) + "\x00" + (match.group(2) or "")
                else:
                    handler_args = match.group(1)
                result_text, audio_sent = await handler.handle(
                    handler_args, agent_id, send
                )
                display = handler.PATTERN.sub(result_text, display, count=1)
                if audio_sent:
                    bark_ok = True
            except Exception as exc:
                logger.error("Handler %s failed: %s", tag_name, exc)
                display = handler.PATTERN.sub("", display, count=1)

    display = display.strip()
    if display:
        await send({
            "type":    "assistant",
            "agent":   agent_id,
            "message": {"content": [{"type": "text", "text": display}]},
            "bark_ok": bark_ok,
        })
    return display
