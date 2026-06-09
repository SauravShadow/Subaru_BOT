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
    assert len(sm._slots) == 4
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
    assert free is not None
    assert free != 0


@pytest.mark.asyncio
async def test_find_free_slot_returns_none_when_all_busy(sm):
    for i in range(4):
        await sm.acquire(i)
    assert sm.find_free_slot() is None


@pytest.mark.asyncio
async def test_status_returns_four_dicts(sm):
    statuses = sm.status()
    assert len(statuses) == 4
    for s in statuses:
        assert "slot_id" in s and "state" in s and "url" in s and "action" in s


@pytest.mark.asyncio
async def test_mark_blocked_sets_reason_and_clears_resume_event(sm):
    await sm.acquire(0)
    # mark_blocked lazily creates the Event and clears it
    await sm.mark_blocked(0, "Naukri is showing a login page")
    assert sm._slots[0].blocked_reason == "Naukri is showing a login page"
    assert sm._slots[0].resume_event is not None
    assert not sm._slots[0].resume_event.is_set()


@pytest.mark.asyncio
async def test_resume_clears_reason_and_sets_event(sm):
    await sm.acquire(0)
    await sm.mark_blocked(0, "Captcha on LinkedIn")
    resumed = sm.resume(0)
    assert resumed is True
    assert sm._slots[0].blocked_reason == ""
    assert sm._slots[0].resume_event.is_set()


@pytest.mark.asyncio
async def test_resume_returns_false_when_slot_is_not_blocked(sm):
    await sm.acquire(0)
    assert sm.resume(0) is False


@pytest.mark.asyncio
async def test_status_reports_blocked_reason(sm):
    await sm.acquire(0)
    await sm.mark_blocked(0, "Login wall on naukri.com")
    statuses = sm.status()
    assert statuses[0]["blocked_reason"] == "Login wall on naukri.com"
    assert statuses[1]["blocked_reason"] == ""


@pytest.mark.asyncio
async def test_release_clears_blocked_state(sm):
    await sm.acquire(0)
    await sm.mark_blocked(0, "Captcha on LinkedIn")
    await sm.release(0)
    assert sm._slots[0].blocked_reason == ""
    assert sm._slots[0].resume_event.is_set() is False
