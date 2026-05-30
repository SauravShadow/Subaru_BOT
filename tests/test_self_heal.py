import pytest
import json
from pathlib import Path
from unittest.mock import patch


def test_classify_immutable_paths():
    from app.services.self_heal import classify_path
    assert classify_path("/app/app/main.py")               == "immutable"
    assert classify_path("/app/skills/loader.py")          == "immutable"
    assert classify_path("/app/skills/core/bash_tools.py") == "immutable"
    assert classify_path("app/main.py")                    == "immutable"


def test_classify_protected_paths():
    from app.services.self_heal import classify_path
    assert classify_path("/app/app/agents/executor.py")    == "protected"
    assert classify_path("/app/app/api/router.py")         == "protected"
    assert classify_path("app/agents/definitions.py")      == "protected"
    assert classify_path("/app/requirements.txt")          == "protected"
    assert classify_path("/app/Dockerfile")                == "protected"


def test_classify_surface_paths():
    from app.services.self_heal import classify_path
    assert classify_path("/app/app/static/style-v5.css")   == "surface"
    assert classify_path("/app/app/static/app-v5.js")      == "surface"
    assert classify_path("app/static/index.html")          == "surface"


def test_classify_learning_paths():
    from app.services.self_heal import classify_path
    assert classify_path("/app/app/services/scheduler.py")          == "learning"
    assert classify_path("/app/app/services/browser.py")            == "learning"
    assert classify_path("/app/skills/learned/ping/v1/skill.py")    == "learning"


def test_load_save_approvals(tmp_path):
    from app.services.self_heal import load_approvals, save_approvals
    approvals_file = tmp_path / "nexus_pending_approvals.json"
    with patch("app.services.self_heal.APPROVALS_FILE", approvals_file):
        assert load_approvals() == {}
        save_approvals({"abc": {"id": "abc", "status": "pending"}})
        data = load_approvals()
        assert "abc" in data
        assert data["abc"]["status"] == "pending"


def test_classify_path_strips_workspace_prefix():
    from app.services.self_heal import classify_path
    assert classify_path("/workspace/virtual-company/app/agents/executor.py") == "protected"
    assert classify_path("virtual-company/app/static/style.css")               == "surface"
