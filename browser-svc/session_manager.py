import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page


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
    context: Optional[BrowserContext] = field(default=None, repr=False)
    page: Optional[Page] = field(default=None, repr=False)
    cdp_session: Optional[object] = field(default=None, repr=False)


class SessionManager:
    NUM_SLOTS = 5

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
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def acquire(self, slot_id: int) -> SlotInfo:
        async with self._lock:
            slot = self._slots[slot_id]
            if slot.state == SlotState.BUSY:
                raise RuntimeError(f"Slot {slot_id} is already busy")
            if slot.context is None:
                slot.context = await self._browser.new_context(
                    viewport={"width": 1280, "height": 900},
                )
                slot.page = await slot.context.new_page()
            slot.state = SlotState.BUSY
            return slot

    async def release(self, slot_id: int):
        async with self._lock:
            slot = self._slots[slot_id]
            slot.state = SlotState.IDLE
            slot.url = ""
            slot.action = ""

    def status(self) -> list[dict]:
        return [
            {"slot_id": s.slot_id, "state": s.state.value, "url": s.url, "action": s.action}
            for s in self._slots
        ]

    def find_free_slot(self, exclude: int = -1) -> Optional[int]:
        for s in self._slots:
            if s.slot_id != exclude and s.state == SlotState.IDLE:
                return s.slot_id
        return None

    async def start_screencast(self, slot_id: int, relay) -> None:
        slot = self._slots[slot_id]
        if slot.page is None or slot.cdp_session is not None:
            return
        cdp = await slot.context.new_cdp_session(slot.page)
        slot.cdp_session = cdp

        async def on_frame(event):
            relay.push({
                "type": "browser_frame",
                "slot": slot_id,
                "frame": event["data"],
                "url": slot.url,
                "action": slot.action,
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

    async def stop_screencast(self, slot_id: int) -> None:
        slot = self._slots[slot_id]
        if slot.cdp_session is None:
            return
        try:
            await slot.cdp_session.send("Page.stopScreencast")
        except Exception:
            pass
        slot.cdp_session = None


session_manager = SessionManager()
