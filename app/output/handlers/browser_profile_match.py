"""BROWSER_PROFILE_MATCH handler — dispatches [BROWSER_PROFILE_MATCH] to browser-svc."""
import asyncio
import logging
import re
from typing import Callable, Awaitable

from app.services.browser_svc import call_browser_svc

logger  = logging.getLogger(__name__)
TAG     = "BROWSER_PROFILE_MATCH"
PATTERN = re.compile(r'\[(BROWSER_PROFILE_MATCH)\]')

Sender = Callable[[dict], Awaitable[None]]


async def handle(args: str, agent_id: str, send: Sender) -> tuple[str, bool]:
    await send({"type": "tool_call", "agent": agent_id,
                "tool": "browser_profile_match",
                "label": "Matching profile to target companies",
                "path": "target_companies"})
    asyncio.create_task(call_browser_svc("browser_profile_match", {}))
    return "🎯 Matching your profile against target companies...", False
