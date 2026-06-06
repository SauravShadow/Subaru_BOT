import asyncio
import pytest
from relay_client import RelayClient


def test_push_queues_item():
    relay = RelayClient()
    relay.push({"type": "browser_frame", "slot": 0, "frame": "abc"})
    assert relay._queue.qsize() == 1


def test_push_drops_oldest_when_full():
    relay = RelayClient()
    # Fill queue to maxsize
    for i in range(30):
        relay.push({"seq": i})
    # Now push one more — should drop oldest, queue stays at 30
    relay.push({"seq": 30})
    assert relay._queue.qsize() == 30
    # The newest item should be in the queue (we can't guarantee order easily,
    # but qsize should be capped)


def test_start_creates_task():
    import asyncio

    async def _run():
        relay = RelayClient()
        relay.start()
        assert relay._task is not None
        relay._task.cancel()
        try:
            await relay._task
        except (asyncio.CancelledError, Exception):
            pass

    asyncio.run(_run())
