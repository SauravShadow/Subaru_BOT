import asyncio
import pytest
from relay_client import RelayClient


def test_push_queues_item():
    relay = RelayClient()
    relay.push({"type": "browser_frame", "slot": 0, "frame": "abc"})
    assert relay._queue.qsize() == 1


def test_push_drops_oldest_when_full():
    relay = RelayClient()
    for i in range(30):
        relay.push({"seq": i})
    relay.push({"seq": 30})
    assert relay._queue.qsize() == 30
    items = []
    while not relay._queue.empty():
        items.append(relay._queue.get_nowait())
    seqs = [item["seq"] for item in items]
    assert 0 not in seqs, "oldest item should have been dropped"
    assert 30 in seqs, "newest item should be present"


def test_start_creates_task():
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
