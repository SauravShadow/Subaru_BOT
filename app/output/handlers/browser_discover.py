"""BROWSER_DISCOVER handler — dispatches [BROWSER_DISCOVER: keywords | platform | location]."""
import asyncio
import logging
import re
from typing import Callable, Awaitable

from app.agents.tools import parse_browser_discover_args
from app.services.browser_svc import call_browser_svc

logger  = logging.getLogger(__name__)
TAG     = "BROWSER_DISCOVER"
PATTERN = re.compile(r'\[BROWSER_DISCOVER:\s*([^\]]+)\]')

Sender = Callable[[dict], Awaitable[None]]


async def handle(args: str, agent_id: str, send: Sender) -> tuple[str, bool]:
    parsed = parse_browser_discover_args(args)
    await send({"type": "tool_call", "agent": agent_id,
                "tool": "browser_discover", "label": "Searching for jobs",
                "path": f"{parsed['keywords']} ({parsed['platform']})"[:60]})
    asyncio.create_task(call_browser_svc("browser_discover", parsed))
    return (
        f"🔎 Searching {parsed['platform']} for {parsed['keywords']} "
        f"in {parsed['location']}..."
    ), False
