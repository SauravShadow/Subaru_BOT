import json
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, AsyncMock


@pytest.fixture
def routines_file(tmp_path):
    f = tmp_path / "nexus_routines.json"
    f.write_text(json.dumps([
        {
            "id": "test_routine",
            "name": "Test",
            "agent": "ceo",
            "schedule": "* * * * *",   # every minute
            "timezone": "UTC",
            "prompt": "hello",
            "enabled": True,
            "last_run": None,
            "last_status": None,
            "run_count": 0,
        }
    ]))
    return f


def test_load_routines_returns_list(tmp_path, routines_file):
    from app.services.scheduler import load_routines
    with patch("app.services.scheduler.ROUTINES_FILE", routines_file):
        routines = load_routines()
        assert len(routines) == 1
        assert routines[0]["id"] == "test_routine"


def test_load_routines_missing_file(tmp_path):
    from app.services.scheduler import load_routines
    missing = tmp_path / "no_such_file.json"
    with patch("app.services.scheduler.ROUTINES_FILE", missing):
        assert load_routines() == []


def test_maybe_fire_triggers_within_window():
    """A routine due within +-30 s should be added to fired dict and task created."""
    from app.services.scheduler import _maybe_fire

    routine = {
        "id": "r1", "schedule": "* * * * *",
        "timezone": "UTC", "enabled": True,
        "prompt": "x", "agent": "ceo",
    }
    fired = {}
    tasks_created = []

    def fake_create_task(coro):
        coro.close()
        tasks_created.append(True)

    with patch("asyncio.create_task", side_effect=fake_create_task):
        _maybe_fire(routine, fired)

    assert len(tasks_created) == 1
    assert len(fired) == 1


def test_maybe_fire_no_double_fire():
    """Same routine must not fire twice for the same minute."""
    from app.services.scheduler import _maybe_fire

    routine = {
        "id": "r1", "schedule": "* * * * *",
        "timezone": "UTC", "enabled": True,
        "prompt": "x", "agent": "ceo",
    }
    fired = {}
    tasks_created = []

    def fake_create_task(coro):
        coro.close()
        tasks_created.append(True)

    with patch("asyncio.create_task", side_effect=fake_create_task):
        _maybe_fire(routine, fired)
        _maybe_fire(routine, fired)   # second call same minute

    assert len(tasks_created) == 1   # only fired once


def test_maybe_fire_disabled_routine_skipped():
    from app.services.scheduler import _maybe_fire

    routine = {
        "id": "r1", "schedule": "* * * * *",
        "timezone": "UTC", "enabled": False,
        "prompt": "x", "agent": "ceo",
    }
    fired = {}
    tasks_created = []

    def fake_create_task(coro):
        coro.close()
        tasks_created.append(True)

    with patch("asyncio.create_task", side_effect=fake_create_task):
        _maybe_fire(routine, fired)

    assert len(tasks_created) == 0


def test_update_routine_run(tmp_path, routines_file):
    from app.services.scheduler import update_routine_run, load_routines
    logs_file = tmp_path / "nexus_routine_logs.json"

    with patch("app.services.scheduler.ROUTINES_FILE", routines_file), \
         patch("app.services.scheduler.ROUTINE_LOGS_FILE", logs_file):
        update_routine_run("test_routine", "success", "output text")
        routines = load_routines()
        assert routines[0]["last_status"] == "success"
        assert routines[0]["run_count"] == 1
        assert logs_file.exists()


def test_get_routine_logs(tmp_path):
    from app.services.scheduler import get_routine_logs, _append_run_log
    logs_file = tmp_path / "nexus_routine_logs.json"

    with patch("app.services.scheduler.ROUTINE_LOGS_FILE", logs_file):
        _append_run_log("r1", "success", "output1")
        _append_run_log("r2", "error",   "output2")
        _append_run_log("r1", "success", "output3")

        logs = get_routine_logs("r1")
        assert len(logs) == 2
        assert all(l["routine_id"] == "r1" for l in logs)
