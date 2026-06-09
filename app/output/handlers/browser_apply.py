"""BROWSER_APPLY handler — dispatches [BROWSER_APPLY: url] to browser-svc."""
import asyncio
import logging
import re
from typing import Callable, Awaitable

from app.services.browser_svc import call_browser_svc

logger  = logging.getLogger(__name__)
TAG     = "BROWSER_APPLY"
PATTERN = re.compile(r'\[BROWSER_APPLY:\s*([^\]]+)\]')

Sender = Callable[[dict], Awaitable[None]]


async def handle(args: str, agent_id: str, send: Sender) -> tuple[str, bool]:
    url = args.strip()
    await send({"type": "tool_call", "agent": agent_id,
                "tool": "browser_apply", "label": "Applying to job",
                "path": url[:60]})
    asyncio.create_task(call_browser_svc("browser_apply", {"url": url}))
    return f"🚀 Applying to {url}...", False
