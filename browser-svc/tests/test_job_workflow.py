import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from job_workflow import _resolve_field, _guess_company, ApplyResult


_PROFILE = {
    "name": "Saurav Subaru",
    "email": "saurav@test.com",
    "phone": "9999999999",
    "linkedin": "https://linkedin.com/in/saurav",
    "experience_years": 5,
    "notice_period": "immediate",
    "location_preference": "Bangalore / Remote",
    "target_roles": ["Backend Engineer"],
    "target_companies": ["Stripe"],
    "skills": ["Python"],
}


def test_resolve_field_email():
    assert _resolve_field("email address", _PROFILE) == "saurav@test.com"


def test_resolve_field_full_name():
    assert _resolve_field("Full Name", _PROFILE) == "Saurav Subaru"


def test_resolve_field_first_name():
    assert _resolve_field("First Name", _PROFILE) == "Saurav"


def test_resolve_field_last_name():
    assert _resolve_field("Last Name", _PROFILE) == "Subaru"


def test_resolve_field_phone():
    assert _resolve_field("Mobile Number", _PROFILE) == "9999999999"


def test_resolve_field_linkedin():
    assert _resolve_field("LinkedIn Profile", _PROFILE) == "https://linkedin.com/in/saurav"


def test_resolve_field_unknown_returns_none():
    assert _resolve_field("salary_expectations_xyz", _PROFILE) is None


def test_guess_company_linkedin():
    assert _guess_company("https://www.linkedin.com/jobs/123") == "Linkedin"


def test_guess_company_careers_subdomain():
    assert _guess_company("https://careers.stripe.com/apply/123") == "Stripe"


def test_guess_company_custom_domain():
    assert _guess_company("https://razorpay.com/jobs/123") == "Razorpay"


def test_apply_result_fields():
    r = ApplyResult(url="https://test.com", company="Test", role="Eng", status="applied")
    assert r.status == "applied"
    assert r.keywords == []
    assert r.error == ""


def test_load_profile_reads_json(tmp_path):
    profile_data = {"name": "Test User", "email": "t@t.com"}
    profile_file = tmp_path / "browser_profile.json"
    profile_file.write_text(json.dumps(profile_data))

    import job_workflow as jw
    original = jw.PROFILE_PATH
    jw.PROFILE_PATH = profile_file
    result = jw.load_profile()
    jw.PROFILE_PATH = original
    assert result["name"] == "Test User"


from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_detect_blocker_recognizes_captcha_selector():
    from job_workflow import detect_blocker

    page = AsyncMock()
    page.url = "https://example.com/apply"
    page.inner_text = AsyncMock(return_value="")
    locator_mock = MagicMock()
    locator_mock.first.is_visible = AsyncMock(return_value=True)
    page.locator = MagicMock(return_value=locator_mock)

    blocker = await detect_blocker(page)
    assert blocker == {"blocker_type": "captcha", "description": "Captcha challenge on https://example.com/apply"}


@pytest.mark.asyncio
async def test_detect_blocker_recognizes_login_wall_text():
    from job_workflow import detect_blocker

    page = AsyncMock()
    page.url = "https://naukri.com/jobs/123"
    page.inner_text = AsyncMock(return_value="Please log in to view this job posting")
    locator_mock = MagicMock()
    locator_mock.first.is_visible = AsyncMock(return_value=False)
    page.locator = MagicMock(return_value=locator_mock)

    blocker = await detect_blocker(page)
    assert blocker == {"blocker_type": "login_wall", "description": "Login wall on https://naukri.com/jobs/123"}


@pytest.mark.asyncio
async def test_detect_blocker_returns_none_when_page_is_clean():
    from job_workflow import detect_blocker

    page = AsyncMock()
    page.url = "https://example.com/jobs/456"
    page.inner_text = AsyncMock(return_value="Senior Backend Engineer — apply below")
    locator_mock = MagicMock()
    locator_mock.first.is_visible = AsyncMock(return_value=False)
    page.locator = MagicMock(return_value=locator_mock)

    assert await detect_blocker(page) is None
