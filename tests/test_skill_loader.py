import pytest
import json
from pathlib import Path


@pytest.fixture
def tmp_skills(tmp_path):
    """Create a minimal skills directory for testing."""
    core = tmp_path / "core"
    core.mkdir()
    (core / "__init__.py").touch()
    (core / "bash_tools.py").write_text('TOOLS = [{"name": "bash", "description": "run bash"}]')
    (tmp_path / "learned").mkdir()
    (tmp_path / "registry.json").write_text('{"learned": []}')
    return tmp_path


def test_loader_lists_core_tools(tmp_skills):
    from app.skills.loader import SkillLoader
    loader = SkillLoader(tmp_skills)
    loader.load_all()
    tools = loader.list_tools()
    names = [t["name"] for t in tools]
    assert "bash" in names


def test_loader_get_tool_returns_none_for_core(tmp_skills):
    """Core tools have no handler — they're dispatched by tools.py."""
    from app.skills.loader import SkillLoader
    loader = SkillLoader(tmp_skills)
    loader.load_all()
    assert loader.get_tool("bash") is None


def test_register_learned_skill(tmp_skills):
    from app.skills.loader import SkillLoader
    loader = SkillLoader(tmp_skills)
    loader.load_all()

    skill_code = """
TOOLS = [{"name": "greet", "description": "Say hello"}]

async def handle_greet(args):
    return f"Hello, {args.get('name', 'world')}!"
"""
    test_code = """
import pytest

@pytest.mark.asyncio
async def test_greet():
    import sys, importlib.util
    from pathlib import Path
    assert True  # placeholder — just verify import works
"""
    manifest = {
        "id": "test_greet",
        "name": "Greeting",
        "active_version": "1",
        "description": "Says hello",
        "tools": ["greet"],
        "available_to": ["ceo"],
        "safety_zone": "medium",
        "author": "test",
    }
    result = loader.register_skill(manifest, skill_code, test_code)
    assert result["id"] == "test_greet"
    assert loader.get_tool("greet") is not None


@pytest.mark.asyncio
async def test_registered_skill_handler_runs(tmp_skills):
    from app.skills.loader import SkillLoader
    loader = SkillLoader(tmp_skills)
    loader.load_all()
    skill_code = 'TOOLS = [{"name": "ping", "description": "ping"}]\nasync def handle_ping(args): return "pong"'
    test_code  = 'import pytest\ndef test_ping(): pass'
    manifest = {
        "id": "ping", "name": "Ping", "active_version": "1",
        "description": "ping", "tools": ["ping"],
        "available_to": ["all"], "safety_zone": "low", "author": "test"
    }
    loader.register_skill(manifest, skill_code, test_code)
    handler = loader.get_tool("ping")
    result = await handler({})
    assert result == "pong"


def test_rollback_reverts_active_version(tmp_skills):
    from app.skills.loader import SkillLoader
    loader = SkillLoader(tmp_skills)
    loader.load_all()

    v1_code   = 'TOOLS=[{"name":"ver","description":"v"}]\nasync def handle_ver(a): return "v1"'
    v2_code   = 'TOOLS=[{"name":"ver","description":"v"}]\nasync def handle_ver(a): return "v2"'
    test_code = 'def test_ver(): pass'

    m1 = {"id": "ver", "name": "Ver", "active_version": "1", "description": "v",
          "tools": ["ver"], "available_to": ["all"], "safety_zone": "low", "author": "t"}
    loader.register_skill(m1, v1_code, test_code)

    m2 = {**m1, "active_version": "2", "rollback_to": "1"}
    loader.register_skill(m2, v2_code, test_code)

    ok = loader.rollback("ver")
    assert ok is True
    # After rollback manifest should show version 1
    manifest_path = tmp_skills / "learned" / "ver" / "manifest.json"
    manifest_data = json.loads(manifest_path.read_text())
    assert manifest_data["active_version"] == "1"
