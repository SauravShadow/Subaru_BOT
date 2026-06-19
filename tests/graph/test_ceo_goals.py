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
