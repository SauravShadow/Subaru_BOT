def test_nexus_state_has_goal_fields():
    from app.graph.state import NexusState
    ann = NexusState.__annotations__
    assert "goal_id" in ann
    assert "parent_goal_id" in ann
    assert "deadline" in ann
    assert "success_criteria" in ann


def test_initial_state_seeds_goal_fields():
    import inspect
    import app.api.websocket as ws
    src = inspect.getsource(ws._run_and_stream)
    # The initial state dict must seed all four goal keys.
    for key in ("goal_id", "parent_goal_id", "deadline", "success_criteria"):
        assert f'"{key}"' in src


def test_build_goal_context_lists_active_goals(monkeypatch):
    import app.graph.nodes.ceo as ceo

    def fake_get_goals(status=None, limit=50):
        assert status == "active"
        return [
            {"title": "Ship payments API", "deadline": "2026-07-01"},
            {"title": "Refactor auth", "deadline": None},
        ]

    monkeypatch.setattr(ceo.goal_store, "get_goals", fake_get_goals)
    block = ceo._build_goal_context()
    assert "Ship payments API" in block
    assert "2026-07-01" in block
    assert "Refactor auth" in block


def test_build_goal_context_empty_when_no_goals(monkeypatch):
    import app.graph.nodes.ceo as ceo
    monkeypatch.setattr(ceo.goal_store, "get_goals", lambda status=None, limit=50: [])
    assert ceo._build_goal_context() == ""
