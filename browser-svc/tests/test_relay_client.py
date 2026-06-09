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


def test_relay_client_configures_logging_handler():
    import logging
    import importlib
    import sys

    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    for h in root.handlers[:]:
        root.removeHandler(h)

    try:
        if "relay_client" in sys.modules:
            del sys.modules["relay_client"]
        import relay_client
        assert root.handlers, (
            "relay_client must call logging.basicConfig so its logger.info/warning "
            "calls are emitted to docker logs"
        )
    finally:
        for h in root.handlers[:]:
            root.removeHandler(h)
        for h in saved_handlers:
            root.addHandler(h)
        if "relay_client" in sys.modules:
            del sys.modules["relay_client"]
