import asyncio
import pytest

from stealth import random_ua, random_viewport, _bezier, human_delay, _USER_AGENTS


def test_random_ua_is_known():
    assert random_ua() in _USER_AGENTS


def test_random_viewport_in_range():
    vp = random_viewport()
    assert 1280 <= vp["width"] <= 1440
    assert 768 <= vp["height"] <= 900


def test_bezier_at_zero_is_p0():
    assert _bezier(0, 10, 20, 30, 40) == pytest.approx(10.0)


def test_bezier_at_one_is_p3():
    assert _bezier(1, 10, 20, 30, 40) == pytest.approx(40.0)


def test_bezier_midpoint_is_between():
    mid = _bezier(0.5, 0, 0, 100, 100)
    assert 0 < mid < 100


@pytest.mark.asyncio
async def test_human_delay_within_bounds():
    import time
    start = time.monotonic()
    await human_delay(100, 200)
    elapsed = time.monotonic() - start
    # Allow generous upper bound for slow CI
    assert 0.09 < elapsed < 1.0
