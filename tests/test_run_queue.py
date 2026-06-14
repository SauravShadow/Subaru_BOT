"""Global FIFO run queue — serial execution + queued notice."""
import asyncio
import pytest


@pytest.mark.asyncio
async def test_jobs_run_serially_in_order():
    from app.api.run_queue import RunQueue
    q = RunQueue()
    order = []

    async def make(n):
        order.append(("start", n))
        await asyncio.sleep(0.02)
        order.append(("end", n))

    async def notify(_): pass

    await q.enqueue({"coro_factory": lambda: make(1), "label": "one"}, notify)
    await q.enqueue({"coro_factory": lambda: make(2), "label": "two"}, notify)
    await q.join()

    assert order == [("start", 1), ("end", 1), ("start", 2), ("end", 2)]


@pytest.mark.asyncio
async def test_second_job_gets_queued_notice():
    from app.api.run_queue import RunQueue
    q = RunQueue()
    notices = []

    async def slow():
        await asyncio.sleep(0.05)

    async def notify(data):
        notices.append(data)

    await q.enqueue({"coro_factory": slow, "label": "first"}, notify)
    await asyncio.sleep(0.005)
    await q.enqueue({"coro_factory": slow, "label": "second"}, notify)
    await q.join()

    queued = [n for n in notices if n.get("type") == "queued"]
    assert len(queued) == 1
    assert queued[0]["task"] == "second"
    assert queued[0]["position"] >= 1


@pytest.mark.asyncio
async def test_first_job_gets_no_queued_notice():
    from app.api.run_queue import RunQueue
    q = RunQueue()
    notices = []

    async def quick():
        return None

    async def notify(data):
        notices.append(data)

    await q.enqueue({"coro_factory": quick, "label": "only"}, notify)
    await q.join()
    assert [n for n in notices if n.get("type") == "queued"] == []


@pytest.mark.asyncio
async def test_clear_flushes_pending():
    from app.api.run_queue import RunQueue
    q = RunQueue()
    ran = []

    async def slow():
        await asyncio.sleep(0.05)
        ran.append("slow")

    async def never():
        ran.append("never")

    async def notify(_): pass

    await q.enqueue({"coro_factory": slow, "label": "a"}, notify)
    await asyncio.sleep(0.005)
    await q.enqueue({"coro_factory": never, "label": "b"}, notify)
    q.clear()
    await asyncio.sleep(0.1)
    assert "never" not in ran
