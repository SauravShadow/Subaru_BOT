import pytest


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "test_goals.db"
    import app.services.goals as g
    original = g.DB_PATH
    g.DB_PATH = db
    g.init_db()
    yield g
    g.DB_PATH = original


def test_create_goal_returns_id(store):
    gid = store.create_goal("Ship the payments API", deadline="2026-07-01")
    assert isinstance(gid, str) and gid


def test_get_goals_active_only(store):
    a = store.create_goal("Active goal")
    b = store.create_goal("Done goal")
    store.update_goal_status(b, "done")
    active = store.get_goals(status="active")
    titles = {row["title"] for row in active}
    assert "Active goal" in titles
    assert "Done goal" not in titles


def test_get_goals_all(store):
    store.create_goal("One")
    store.create_goal("Two")
    assert len(store.get_goals()) == 2


def test_update_goal_status_persists(store):
    gid = store.create_goal("Movable")
    store.update_goal_status(gid, "done", outcome_score=0.8)
    row = store.get_goal(gid)
    assert row["status"] == "done"
    assert row["outcome_score"] == 0.8


def test_subtasks_roundtrip(store):
    gid = store.create_goal("With subtasks", subtasks=["a", "b", "c"])
    row = store.get_goal(gid)
    assert row["subtasks"] == ["a", "b", "c"]


def test_save_and_get_outcome(store):
    gid = store.create_goal("Deploy service")
    store.save_outcome(
        goal_id=gid,
        task="Deploy on port 8080",
        approach_taken="docker compose up",
        duration_ms=4200,
        success_score=0.3,
        blockers=["port 8080 conflict"],
    )
    outs = store.get_outcomes(goal_id=gid)
    assert len(outs) == 1
    assert outs[0]["task"] == "Deploy on port 8080"
    assert outs[0]["success_score"] == 0.3
    assert outs[0]["blockers"] == ["port 8080 conflict"]


def test_get_outcomes_filters_by_goal(store):
    g1 = store.create_goal("G1")
    g2 = store.create_goal("G2")
    store.save_outcome(goal_id=g1, task="t1", success_score=0.9)
    store.save_outcome(goal_id=g2, task="t2", success_score=0.5)
    outs = store.get_outcomes(goal_id=g1)
    assert len(outs) == 1
    assert outs[0]["task"] == "t1"


def test_save_outcome_without_goal(store):
    store.save_outcome(task="orphan task", success_score=0.7)
    outs = store.get_outcomes()
    assert any(o["task"] == "orphan task" for o in outs)


def test_get_goals_fail_soft_on_missing_table(store):
    import sqlite3
    with sqlite3.connect(str(store.DB_PATH)) as c:
        c.execute("DROP TABLE goals")
    assert store.get_goals() == []
