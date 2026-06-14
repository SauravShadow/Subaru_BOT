# app/api/run_queue.py
"""Global FIFO run queue — the company runs one task at a time.

A single async consumer drains the queue serially. User messages and
scheduled routines both enqueue here, so nothing ever runs (or speaks)
concurrently. When a job is enqueued while another is active/waiting, the
provided `notify` callback receives a {"type": "queued", ...} message.
"""
import asyncio
import logging
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

Notify = Callable[[dict], Awaitable[None]]


class RunQueue:
    def __init__(self) -> None:
        self._queue: asyncio.Queue = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._current: asyncio.Task | None = None

    def start(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run_loop())

    async def enqueue(self, job: dict, notify: Notify) -> None:
        """job = {"coro_factory": () -> coroutine, "label": str}."""
        ahead = (1 if self._current is not None else 0) + self._queue.qsize()
        await self._queue.put(job)
        self.start()
        if ahead > 0:
            try:
                await notify({
                    "type": "queued",
                    "position": ahead,
                    "task": job.get("label", ""),
                    "agent": "ceo",
                })
            except Exception:
                logger.warning("queued-notice failed", exc_info=True)

    async def _run_loop(self) -> None:
        while True:
            job = await self._queue.get()
            self._current = asyncio.create_task(job["coro_factory"]())
            try:
                await self._current
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("run_queue job error")
            finally:
                self._current = None
                self._queue.task_done()

    def cancel_current(self) -> None:
        if self._current and not self._current.done():
            self._current.cancel()

    def clear(self) -> None:
        """Cancel the running job and drop everything still queued."""
        self.cancel_current()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break

    async def join(self) -> None:
        """Wait until the queue is fully drained (test helper)."""
        await self._queue.join()


_run_queue: RunQueue | None = None


def get_run_queue() -> RunQueue:
    global _run_queue
    if _run_queue is None:
        _run_queue = RunQueue()
    return _run_queue
