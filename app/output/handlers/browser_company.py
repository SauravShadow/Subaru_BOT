"""BROWSER_COMPANY handler — dispatches [BROWSER_COMPANY: Company Name] to browser-svc."""
import asyncio
import logging
import re
from typing import Callable, Awaitable

from app.services.browser_svc import call_browser_svc

logger  = logging.getLogger(__name__)
TAG     = "BROWSER_COMPANY"
PATTERN = re.compile(r'\[BROWSER_COMPANY:\s*([^\]]+)\]')

Sender = Callable[[dict], Awaitable[None]]


async def handle(args: str, agent_id: str, send: Sender) -> tuple[str, bool]:
    company = args.strip()
    await send({"type": "tool_call", "agent": agent_id,
                "tool": "browser_company", "label": "Searching company careers page",
                "path": company[:60]})
    asyncio.create_task(call_browser_svc("browser_company", {"company": company}))
    return f"🏢 Looking for roles at {company}...", False
