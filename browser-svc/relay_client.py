import asyncio
import json
import logging
import os

import websockets

logger = logging.getLogger(__name__)

NEXUS_WS_URL = os.environ.get(
    "NEXUS_WS_URL", "ws://virtual-company:3030/ws/browser-relay"
)


class RelayClient:
    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=30)
        self._task: asyncio.Task | None = None

    def push(self, data: dict) -> None:
        try:
            self._queue.put_nowait(data)
        except asyncio.QueueFull:
            # Drop oldest, insert newest
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(data)
            except Exception:
                pass

    def start(self):
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def _run(self):
        while True:
            try:
                async with websockets.connect(
                    NEXUS_WS_URL,
                    ping_interval=20,
                    ping_timeout=10,
                ) as ws:
                    logger.info("browser-relay connected to NEXUS")
                    while True:
                        try:
                            data = await asyncio.wait_for(
                                self._queue.get(), timeout=30
                            )
                        except asyncio.TimeoutError:
                            continue
                        await ws.send(json.dumps(data))
            except Exception as exc:
                logger.warning(
                    "browser-relay disconnected (%s) — retrying in 3s", exc
                )
                await asyncio.sleep(3)


relay = RelayClient()
