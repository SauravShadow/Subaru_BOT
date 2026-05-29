"""
Persistent state manager for Shadow Garden.
All mutable globals live here so every module imports from one place.
"""
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional

from app import config

logger = logging.getLogger(__name__)

# ── Runtime globals ────────────────────────────────────────────────────────────
conversation_histories: Dict[str, List[dict]] = {}
work_queue: List[dict] = []
active_agent_tasks: Dict[str, int] = {}   # agent_id -> task item id currently running
custom_agents: Dict[str, dict] = {}
email_tasks: Dict[str, dict] = {}         # message_id -> email task state machine record
task_history: List[dict] = []             # last 5 completed CEO-level tasks for resume

# ── Record batching ────────────────────────────────────────────────────────────
_record_call_count: int = 0
_SAVE_EVERY: int = 5


# ── Persistence ────────────────────────────────────────────────────────────────

def save_state() -> None:
    try:
        config.STATE_FILE.write_text(
            json.dumps(
                {
                    "conversation_histories": conversation_histories,
                    "custom_agents":          custom_agents,
                    "work_queue":             work_queue,
                    "active_agent_tasks":     active_agent_tasks,
                    "email_tasks":            email_tasks,
                    "task_history":           task_history,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.error("save_state failed: %s", exc)


def load_state() -> None:
    """Load persisted state; resets any stuck 'running' tasks to 'pending'."""
    if not config.STATE_FILE.exists():
        return
    try:
        state = json.loads(config.STATE_FILE.read_text(encoding="utf-8"))
        conversation_histories.update(state.get("conversation_histories", {}))
        custom_agents.update(state.get("custom_agents", {}))
        loaded_wq = state.get("work_queue", [])
        work_queue.clear()
        work_queue.extend(loaded_wq)
        email_tasks.update(state.get("email_tasks", {}))
        loaded_th = state.get("task_history", [])
        task_history.clear()
        task_history.extend(loaded_th)

        # Reset tasks stuck in 'running' state from a previous crashed session
        reset_count = 0
        for item in work_queue:
            if item.get("status") == "running":
                item["status"] = "pending"
                item["summary"] = None
                reset_count += 1
        if reset_count:
            logger.info("Reset %d stuck task(s) to 'pending' on startup", reset_count)

        # active_agent_tasks are irrelevant after restart — clear them
        active_agent_tasks.clear()
        save_state()
    except Exception as exc:
        logger.error("load_state failed: %s", exc)


# ── History helpers ────────────────────────────────────────────────────────────

def record(agent_id: str, role: str, content: str) -> None:
    global _record_call_count
    conversation_histories.setdefault(agent_id, []).append(
        {"role": role, "content": content, "ts": datetime.now().isoformat()}
    )
    # Trim to rolling window
    conversation_histories[agent_id] = conversation_histories[agent_id][
        -(config.MAX_HISTORY * 2) :
    ]
    _record_call_count += 1
    if _record_call_count >= _SAVE_EVERY:
        save_state()
        _record_call_count = 0


def get_history(agent_id: str) -> List[dict]:
    return conversation_histories.get(agent_id, [])


# ── Work queue helpers ─────────────────────────────────────────────────────────

def create_work_item(agent: str, task: str, from_agent: str = "ceo") -> dict:
    item_id = (max((i["id"] for i in work_queue), default=0)) + 1
    item = {
        "id":      item_id,
        "agent":   agent,
        "task":    task,
        "status":  "pending",
        "created": datetime.now().isoformat(),
        "from":    from_agent,
        "summary": None,
    }
    work_queue.append(item)
    save_state()
    return item


def _push_task_history(task: str, agent: str, summary: str, status: str = "completed") -> None:
    """Record a CEO-level task to the rolling history (max 5)."""
    task_history.append({
        "task":    task[:200],
        "agent":   agent,
        "summary": summary[:300] if summary else "",
        "status":  status,
        "ts":      datetime.now().isoformat(),
    })
    # Keep only last 5
    del task_history[:-5]


def complete_work_item(item_id: int, summary: str) -> Optional[dict]:
    for item in work_queue:
        if item["id"] == item_id:
            item["status"]  = "completed"
            item["summary"] = summary
            active_agent_tasks.pop(item["agent"], None)
            _push_task_history(item["task"], item["agent"], summary, "completed")
            save_state()
            return item
    return None


def force_complete_item(item_id: int) -> Optional[dict]:
    for item in work_queue:
        if item["id"] == item_id:
            item["status"]  = "completed"
            item["summary"] = "Force-completed by user."
            active_agent_tasks.pop(item.get("agent", ""), None)
            save_state()
            return item
    return None


def reset_work_item(item_id: int) -> Optional[dict]:
    for item in work_queue:
        if item["id"] == item_id:
            item["status"]  = "pending"
            item["summary"] = None
            active_agent_tasks.pop(item.get("agent", ""), None)
            save_state()
            return item
    return None


# ── Projects ───────────────────────────────────────────────────────────────────

def load_projects() -> list:
    if config.PROJECTS_FILE.exists():
        try:
            return json.loads(config.PROJECTS_FILE.read_text())
        except Exception:
            pass
    return []


def save_project(project: dict) -> dict:
    projects = load_projects()
    project.update(
        {"id": len(projects) + 1, "created": datetime.now().isoformat(), "status": "active"}
    )
    projects.append(project)
    config.PROJECTS_FILE.write_text(json.dumps(projects, indent=2))
    return project


def _get_workdir():
    return config.WORK_DIR


# ── Feature Changelog ─────────────────────────────────────────────────────────

CHANGELOG_FILE = config.CHANGELOG_FILE

_changelog_cache: Optional[List[dict]] = None


def load_changelog() -> list:
    global _changelog_cache
    if _changelog_cache is not None:
        return _changelog_cache
    try:
        if CHANGELOG_FILE.exists():
            _changelog_cache = json.loads(CHANGELOG_FILE.read_text(encoding="utf-8"))
            return _changelog_cache
    except Exception as exc:
        logger.warning("load_changelog failed: %s", exc)
    _changelog_cache = []
    return _changelog_cache


def log_feature(feature: str, files: list, agent: str = "worker") -> dict:
    global _changelog_cache
    changelog = load_changelog()
    entry = {
        "feature":   feature,
        "files":     files,
        "agent":     agent,
        "timestamp": datetime.now().isoformat(),
    }
    changelog.append(entry)
    try:
        CHANGELOG_FILE.write_text(json.dumps(changelog, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.error("log_feature failed: %s", exc)
    return entry
