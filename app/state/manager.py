"""
State helpers — conversation history (runtime cache), changelog, projects.
Work queue and save_state/load_state removed: LangGraph checkpointer owns persistence.
"""
import json
import logging
from datetime import datetime
from typing import List, Optional

from app import config

logger = logging.getLogger(__name__)

conversation_histories: dict[str, list[dict]] = {}


def record(agent_id: str, role: str, content: str) -> None:
    if agent_id not in conversation_histories:
        conversation_histories[agent_id] = []
    conversation_histories[agent_id].append({"role": role, "content": content})
    cap = config.MAX_HISTORY
    if len(conversation_histories[agent_id]) > cap:
        conversation_histories[agent_id] = conversation_histories[agent_id][-cap:]


def get_history(agent_id: str) -> List[dict]:
    return conversation_histories.get(agent_id, [])


def load_changelog() -> list:
    try:
        if config.CHANGELOG_FILE.exists():
            return json.loads(config.CHANGELOG_FILE.read_text())
    except Exception as exc:
        logger.warning("load_changelog error: %s", exc)
    return []


def log_feature(feature: str, files: list, agent: str = "worker") -> dict:
    changelog = load_changelog()
    entry = {
        "timestamp": datetime.now().isoformat(),
        "feature": feature,
        "files": files,
        "agent": agent,
    }
    changelog.append(entry)
    try:
        config.CHANGELOG_FILE.write_text(json.dumps(changelog, indent=2))
    except Exception as exc:
        logger.warning("log_feature write error: %s", exc)
    return entry


def load_projects() -> list:
    try:
        if config.PROJECTS_FILE.exists():
            return json.loads(config.PROJECTS_FILE.read_text())
    except Exception as exc:
        logger.warning("load_projects error: %s", exc)
    return []


def save_project(project: dict) -> dict:
    projects = load_projects()
    existing = next((p for p in projects if p.get("id") == project.get("id")), None)
    if existing:
        existing.update(project)
    else:
        project.setdefault("id", len(projects) + 1)
        projects.append(project)
    try:
        config.PROJECTS_FILE.write_text(json.dumps(projects, indent=2))
    except Exception as exc:
        logger.warning("save_project write error: %s", exc)
    return project


def load_state() -> None:
    """No-op — LangGraph checkpointer owns persistence. Kept for import compat."""
    pass
