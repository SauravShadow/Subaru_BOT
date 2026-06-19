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
