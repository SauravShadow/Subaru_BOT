import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from session_manager import SessionManager, SlotState


@pytest.fixture
def sm():
    manager = SessionManager()
    mock_browser = AsyncMock()
    mock_context = AsyncMock()
    mock_page = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    manager._browser = mock_browser
    return manager


@pytest.mark.asyncio
async def test_initial_state_all_idle(sm):
    assert len(sm._slots) == 5
    assert all(s.state == SlotState.IDLE for s in sm._slots)


@pytest.mark.asyncio
async def test_acquire_marks_slot_busy(sm):
    slot = await sm.acquire(0)
    assert slot.state == SlotState.BUSY
    assert sm._slots[0].state == SlotState.BUSY


@pytest.mark.asyncio
async def test_acquire_busy_slot_raises(sm):
    await sm.acquire(1)
    with pytest.raises(RuntimeError, match="already busy"):
        await sm.acquire(1)


@pytest.mark.asyncio
async def test_release_marks_slot_idle(sm):
    await sm.acquire(2)
    await sm.release(2)
    assert sm._slots[2].state == SlotState.IDLE
    assert sm._slots[2].url == ""
    assert sm._slots[2].action == ""


@pytest.mark.asyncio
async def test_find_free_slot_skips_busy(sm):
    await sm.acquire(0)
    free = sm.find_free_slot()
    assert free == 1


@pytest.mark.asyncio
async def test_find_free_slot_returns_none_when_all_busy(sm):
    for i in range(5):
        await sm.acquire(i)
    assert sm.find_free_slot() is None


@pytest.mark.asyncio
async def test_status_returns_five_dicts(sm):
    statuses = sm.status()
    assert len(statuses) == 5
    for s in statuses:
        assert "slot_id" in s and "state" in s and "url" in s and "action" in s
