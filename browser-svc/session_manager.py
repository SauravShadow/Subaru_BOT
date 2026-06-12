import asyncio
import os
import socket
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from urllib.parse import urlparse

from patchright.async_api import async_playwright, Browser, BrowserContext, Page

import logging
logger = logging.getLogger(__name__)


def _proxy_reachable(proxy_url: str, timeout: float = 2.0) -> bool:
    try:
        parsed = urlparse(proxy_url)
        host = parsed.hostname
        port = parsed.port or 1080
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class SlotState(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    ERROR = "error"


@dataclass
class SlotInfo:
    slot_id: int
    state: SlotState = SlotState.IDLE
    url: str = ""
    action: str = ""
    blocked_reason: str = ""
    resume_event: asyncio.Event = field(default=None, repr=False)
    context: Optional[BrowserContext] = field(default=None, repr=False)
    page: Optional[Page] = field(default=None, repr=False)
    cdp_session: Optional[object] = field(default=None, repr=False)


class SessionManager:
    NUM_SLOTS = 4

    def __init__(self):
        self._slots: list[SlotInfo] = [SlotInfo(i) for i in range(self.NUM_SLOTS)]
        self._browser: Optional[Browser] = None
        self._pw = None
        self._lock = asyncio.Lock()

    async def start(self):
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

    async def stop(self):
        for slot in self._slots:
            if slot.context is not None:
                try:
                    await slot.context.close()
                except Exception:
                    pass
                slot.context = None
                slot.page = None
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def _get_or_create_page_unlocked(self, slot_id: int) -> Page:
        slot = self._slots[slot_id]
        if slot.context is None:
            from stealth import random_ua, apply_stealth
            ua = random_ua()
            ctx_kwargs = {
                "viewport": {"width": 1280, "height": 900},
                "user_agent": ua,
                # Match sec-ch-ua to the actual Chromium version shipped by patchright 1.60.x
                # (Chrome 148). Mismatching version with UA is an Akamai detection signal.
                "extra_http_headers": {
                    "sec-ch-ua": '"Google Chrome";v="148", "Chromium";v="148", "Not_A Brand";v="99"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"',
                },
            }
            proxy_url = os.environ.get("BROWSER_PROXY_URL")
            if proxy_url and _proxy_reachable(proxy_url):
                ctx_kwargs["proxy"] = {"server": proxy_url}
                logger.info("Using proxy: %s", proxy_url)
            elif proxy_url:
                logger.warning("Proxy %s unreachable — using direct connection", proxy_url)
            slot.context = await self._browser.new_context(**ctx_kwargs)
            try:
                # patchright handles binary-level stealth; no JS patching needed
                slot.page = await slot.context.new_page()
            except Exception:
                await slot.context.close()
                slot.context = None
                raise
        return slot.page

    async def acquire(self, slot_id: int) -> SlotInfo:
        async with self._lock:
            slot = self._slots[slot_id]
            if slot.state == SlotState.BUSY:
                raise RuntimeError(f"Slot {slot_id} is already busy")
            await self._get_or_create_page_unlocked(slot_id)
            slot.state = SlotState.BUSY
            return slot

    async def release(self, slot_id: int):
        async with self._lock:
            slot = self._slots[slot_id]
            slot.state = SlotState.IDLE
            slot.url = ""
            slot.action = ""
            slot.blocked_reason = ""
            if slot.resume_event is not None:
                slot.resume_event.clear()

    def status(self) -> list[dict]:
        return [
            {"slot_id": s.slot_id, "state": s.state.value, "url": s.url, "action": s.action, "blocked_reason": s.blocked_reason}
            for s in self._slots
        ]

    def find_free_slot(self, exclude: int = -1) -> Optional[int]:
        for s in self._slots:
            if s.slot_id != exclude and s.state == SlotState.IDLE:
                return s.slot_id
        return None

    async def mark_blocked(self, slot_id: int, reason: str) -> None:
        async with self._lock:
            slot = self._slots[slot_id]
            if slot.resume_event is None:
                slot.resume_event = asyncio.Event()
            slot.blocked_reason = reason
            slot.resume_event.clear()

    async def wait_for_resume(self, slot_id: int) -> None:
        evt = self._slots[slot_id].resume_event
        if evt is not None:
            await evt.wait()

    def resume(self, slot_id: int) -> bool:
        slot = self._slots[slot_id]
        if not slot.blocked_reason:
            return False
        slot.blocked_reason = ""
        if slot.resume_event is not None:
            slot.resume_event.set()
        return True

    async def _start_screencast_unlocked(self, slot_id: int, relay) -> None:
        slot = self._slots[slot_id]
        if slot.page is None:
            raise RuntimeError(f"Slot {slot_id} has no page — cannot start screencast")
        if slot.cdp_session is not None:
            return
        cdp = await slot.context.new_cdp_session(slot.page)
        slot.cdp_session = cdp

        async def on_frame(event):
            relay.push({
                "type": "browser_frame",
                "slot": slot_id,
                "frame": event["data"],
                "url": slot.url or slot.page.url,
                "action": slot.action or "Interactive Mode",
            })
            try:
                await cdp.send("Page.screencastFrameAck", {"sessionId": event["sessionId"]})
            except Exception:
                pass

        cdp.on("Page.screencastFrame", on_frame)
        await cdp.send("Page.startScreencast", {
            "format": "jpeg",
            "quality": 60,
            "maxWidth": 1280,
            "maxHeight": 800,
            "everyNthFrame": 1,
        })

    async def start_screencast(self, slot_id: int, relay) -> None:
        async with self._lock:
            await self._start_screencast_unlocked(slot_id, relay)

    async def ensure_interactive(self, slot_id: int, relay) -> Page:
        async with self._lock:
            page = await self._get_or_create_page_unlocked(slot_id)
            await self._start_screencast_unlocked(slot_id, relay)
            return page

    async def stop_screencast(self, slot_id: int) -> None:
        async with self._lock:
            slot = self._slots[slot_id]
            if slot.cdp_session is None:
                return
            cdp = slot.cdp_session
            slot.cdp_session = None

        try:
            await cdp.send("Page.stopScreencast")
        except Exception:
            pass


session_manager = SessionManager()
