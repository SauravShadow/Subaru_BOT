import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# Prevent actual Playwright/WebSocket startup during tests
with patch("session_manager.async_playwright"), \
     patch("relay_client.websockets"):
    from main import app

from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    import main as m
    from session_manager import SlotInfo

    # Point to temp profile file so tests are isolated
    original_profile = m.PROFILE_PATH
    tmp_profile = tmp_path / "browser_profile.json"
    profile_data = {
        "name": "Test User", "email": "t@t.com", "phone": "",
        "linkedin": "", "experience_years": 3, "notice_period": "1 month",
        "target_roles": ["SWE"], "target_companies": ["Test Corp"],
        "skills": ["Python"], "location_preference": "Remote",
    }
    tmp_profile.write_text(json.dumps(profile_data))
    m.PROFILE_PATH = tmp_profile

    fake_slot = SlotInfo(slot_id=1)
    fake_slot.page = MagicMock()

    with patch("main.session_manager.start", new_callable=AsyncMock), \
         patch("main.session_manager.stop", new_callable=AsyncMock), \
         patch("main.relay.start"), \
         patch("main.session_manager.acquire", new_callable=AsyncMock, return_value=fake_slot), \
         patch("main.session_manager.release", new_callable=AsyncMock), \
         patch("main.session_manager.start_screencast", new_callable=AsyncMock), \
         patch("main.session_manager.stop_screencast", new_callable=AsyncMock), \
         patch("job_workflow.load_profile", return_value=profile_data), \
         patch("job_workflow.discover_jobs_linkedin", new_callable=AsyncMock, return_value=[]), \
         patch("job_workflow.discover_jobs_indeed", new_callable=AsyncMock, return_value=[]), \
         patch("job_workflow.discover_company_roles", new_callable=AsyncMock, return_value=[]):
        with TestClient(app) as c:
            yield c
    m.PROFILE_PATH = original_profile


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "slots": 4}


def test_get_slots(client):
    r = client.get("/slots")
    assert r.status_code == 200
    slots = r.json()
    assert len(slots) == 4
    assert all(s["state"] == "idle" for s in slots)


def test_get_profile(client):
    r = client.get("/profile")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "Test User"
    assert data["email"] == "t@t.com"


def test_get_profile_not_found(client, tmp_path):
    import main as m
    original = m.PROFILE_PATH
    m.PROFILE_PATH = tmp_path / "nonexistent.json"
    r = client.get("/profile")
    m.PROFILE_PATH = original
    assert r.status_code == 404


def test_patch_profile(client):
    r = client.patch("/profile", json={"phone": "9999999999", "experience_years": 5})
    assert r.status_code == 200
    data = r.json()
    assert data["phone"] == "9999999999"
    assert data["experience_years"] == 5
    # Existing fields preserved
    assert data["name"] == "Test User"


def test_apply_invalid_slot_negative(client):
    r = client.post("/apply", json={"url": "https://linkedin.com/jobs/123", "slot_id": -1})
    assert r.status_code == 400


def test_apply_invalid_slot_four(client):
    r = client.post("/apply", json={"url": "https://linkedin.com/jobs/123", "slot_id": 4})
    assert r.status_code == 400


def test_apply_queues_job(client):
    r = client.post("/apply", json={"url": "https://linkedin.com/jobs/123", "slot_id": 1})
    assert r.status_code == 200
    data = r.json()
    assert data["queued"] is True
    assert data["slot_id"] == 1


def test_apply_without_slot_id_picks_free_slot(client):
    r = client.post("/apply", json={"url": "https://linkedin.com/jobs/123"})
    assert r.status_code == 200
    data = r.json()
    assert data["queued"] is True
    assert data["slot_id"] == 0


def test_apply_returns_409_when_no_free_slot(client):
    import main as m
    with patch.object(m.session_manager, "find_free_slot", return_value=None):
        r = client.post("/apply", json={"url": "https://linkedin.com/jobs/123"})
    assert r.status_code == 409
    assert r.json()["detail"] == "No free slot available"


def test_discover_queues_job(client):
    r = client.post("/discover", json={"keywords": "Python backend", "platform": "linkedin"})
    assert r.status_code == 200
    assert r.json()["queued"] is True


def test_company_apply_queues(client):
    r = client.post("/company-apply", json={"company": "Stripe"})
    assert r.status_code == 200
    assert r.json()["queued"] is True


def test_profile_match_queues(client):
    r = client.post("/profile-match", json={})
    assert r.status_code == 200
    assert r.json()["queued"] is True


@pytest.mark.asyncio
async def test_apply_on_slot_pushes_browser_result(client):
    import main as m
    from session_manager import SlotInfo
    from job_workflow import ApplyResult

    fake_result = ApplyResult(
        url="https://linkedin.com/jobs/123", company="Stripe", role="Backend Engineer",
        status="applied",
    )
    fake_slot = SlotInfo(slot_id=2)

    with patch("job_workflow.apply_to_job", new_callable=AsyncMock, return_value=fake_result), \
         patch.object(m.relay, "push") as mock_push:
        await m._apply_on_slot(fake_slot, "https://linkedin.com/jobs/123", True)

    mock_push.assert_called_once()
    assert mock_push.call_args[0][0] == {
        "type": "browser_result",
        "agent_id": "maya",
        "slot_id": 2,
        "tool": "browser_apply",
        "result": "Stripe — Backend Engineer: applied (https://linkedin.com/jobs/123)",
    }


def test_ensure_interactive_starts_screencast_and_returns_ok(client):
    import main as m
    with patch.object(m.session_manager, "ensure_interactive", new_callable=AsyncMock) as mock_ensure:
        r = client.post("/slots/2/ensure-interactive")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    mock_ensure.assert_called_once_with(2, m.relay)


def test_ensure_interactive_rejects_out_of_range_slot(client):
    r = client.post("/slots/4/ensure-interactive")
    assert r.status_code == 400


def test_resume_signals_a_blocked_slot(client):
    import main as m
    with patch.object(m.session_manager, "resume", return_value=True) as mock_resume:
        r = client.post("/slots/2/resume")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    mock_resume.assert_called_once_with(2)


def test_resume_rejects_a_slot_that_is_not_blocked(client):
    import main as m
    with patch.object(m.session_manager, "resume", return_value=False):
        r = client.post("/slots/2/resume")
    assert r.status_code == 409


def test_resume_rejects_out_of_range_slot(client):
    r = client.post("/slots/9/resume")
    assert r.status_code == 400
