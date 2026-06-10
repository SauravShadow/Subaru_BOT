import pytest
from app.api.websocket import _translate_event, _step_counters, _checkpoint_counters


def _evt(kind, name, metadata=None, data=None):
    return {
        "event": kind,
        "name": name,
        "metadata": metadata or {},
        "data": data or {},
        "tags": [],
        "run_id": "run-001",
    }


def test_ceo_chain_start_emits_thinking():
    event = _evt("on_chain_start", "ceo_node",
                 metadata={"langgraph_checkpoint_ns": "ceo_node"})
    msg = _translate_event(event, "ws_abc")
    assert msg is not None
    assert msg["type"] == "thinking"
    assert msg["agent"] == "ceo"


def test_tool_start_emits_worker_step():
    _step_counters.clear()
    event = _evt(
        "on_tool_start", "bash",
        metadata={"langgraph_checkpoint_ns": "backend:subgraph123"},
        data={"input": {"command": "pytest tests/"}, "name": "bash"},
    )
    msg = _translate_event(event, "ws_abc")
    assert msg is not None
    assert msg["type"] == "worker_step"
    assert msg["agent"] == "backend"
    assert msg["step"] == 1
    assert msg["tool"] == "bash"
    assert "pytest" in msg["label"]


def test_tool_start_increments_step_per_thread_and_agent():
    _step_counters.clear()
    event = _evt(
        "on_tool_start", "bash",
        metadata={"langgraph_checkpoint_ns": "backend:id"},
        data={"input": {"command": "run"}, "name": "bash"},
    )
    _translate_event(event, "ws_t1")
    _translate_event(event, "ws_t1")
    msg = _translate_event(event, "ws_t1")
    assert msg["step"] == 3


def test_tool_start_separate_agents_have_independent_counters():
    _step_counters.clear()
    ba_event = _evt("on_tool_start", "bash",
                    metadata={"langgraph_checkpoint_ns": "backend:id"},
                    data={"input": {"command": "x"}, "name": "bash"})
    fe_event = _evt("on_tool_start", "bash",
                    metadata={"langgraph_checkpoint_ns": "frontend:id"},
                    data={"input": {"command": "x"}, "name": "bash"})
    _translate_event(ba_event, "ws_t2")
    _translate_event(ba_event, "ws_t2")
    msg = _translate_event(fe_event, "ws_t2")
    assert msg["step"] == 1


def test_worker_node_end_emits_checkpoint():
    _step_counters.clear()
    _checkpoint_counters.clear()
    _step_counters["ws_t3:backend"] = 5
    event = _evt(
        "on_chain_end", "worker_node",
        metadata={"langgraph_checkpoint_ns": "backend:id"},
        data={"output": {"result": "[DONE: Scaffolded API routes]", "new_artifacts": {}}},
    )
    msg = _translate_event(event, "ws_t3")
    assert msg is not None
    assert msg["type"] == "worker_checkpoint"
    assert msg["agent"] == "backend"
    assert msg["index"] == 1
    assert msg["step"] == 5
    assert "Scaffolded API routes" in msg["summary"]


def test_output_node_end_emits_worker_done():
    event = _evt(
        "on_chain_end", "output_node",
        metadata={"langgraph_checkpoint_ns": "backend:id"},
        data={"output": {}},
    )
    msg = _translate_event(event, "ws_t4")
    assert msg is not None
    assert msg["type"] == "worker_done"
    assert msg["agent"] == "backend"


def test_ceo_chain_end_emits_done():
    event = _evt(
        "on_chain_end", "ceo_node",
        metadata={"langgraph_checkpoint_ns": "ceo_node"},
        data={"output": {}},
    )
    msg = _translate_event(event, "ws_t5")
    assert msg is not None
    assert msg["type"] == "done"
    assert msg["agent"] == "ceo"


def test_unknown_event_returns_none():
    event = _evt("on_tool_end", "bash",
                 metadata={"langgraph_checkpoint_ns": "backend:id"})
    msg = _translate_event(event, "ws_t6")
    assert msg is None


def test_step_counters_reset_on_new_ceo_task():
    _step_counters.clear()
    _step_counters["ws_t7:backend"] = 10
    _step_counters["ws_t7:frontend"] = 5
    _step_counters["ws_other:backend"] = 3
    event = _evt("on_chain_start", "ceo_node",
                 metadata={"langgraph_checkpoint_ns": "ceo_node"})
    _translate_event(event, "ws_t7")
    assert "ws_t7:backend" not in _step_counters
    assert "ws_t7:frontend" not in _step_counters
    assert _step_counters.get("ws_other:backend") == 3
