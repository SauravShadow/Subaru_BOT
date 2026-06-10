# app/graph/workers/tools/core.py
"""Dynamic skill meta-tools compiled into every worker subgraph."""
import logging
from langchain_core.tools import tool

from app.skills import skill_loader

logger = logging.getLogger(__name__)


@tool
def list_available_skills() -> list[str]:
    """List all dynamically loaded skill tools available to this worker."""
    tools = skill_loader.list_tools()
    return [t.get("name", "") for t in tools if t.get("name")]


@tool
async def call_skill(skill_name: str, args: dict) -> str:
    """Call a dynamically loaded skill by name with the given arguments."""
    handler = skill_loader.get_tool(skill_name)
    if not handler:
        available = list_available_skills()
        return f"Skill '{skill_name}' not found. Available: {available}"
    try:
        result = await handler(args)
        return str(result)
    except Exception as exc:
        logger.warning("skill %s error: %s", skill_name, exc)
        return f"Skill error: {exc}"


WORKER_META_TOOLS = [list_available_skills, call_skill]
