"""Persistent goals + outcomes over the shared nexus_memory.db."""
import json
import logging
import sqlite3
import uuid
from datetime import datetime

from app import config

logger  = logging.getLogger(__name__)
DB_PATH = config.MEMORY_DB


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH), timeout=5.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=5000")
    return c


def init_db() -> None:
    with _conn() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript("""
            CREATE TABLE IF NOT EXISTS goals (
                goal_id        TEXT PRIMARY KEY,
                parent_goal_id TEXT,
                title          TEXT NOT NULL,
                status         TEXT NOT NULL DEFAULT 'active',
                created_at     TEXT NOT NULL,
                deadline       TEXT,
                success_criteria TEXT,
                subtasks_json  TEXT NOT NULL DEFAULT '[]',
                outcome_score  REAL
            );
            CREATE TABLE IF NOT EXISTS goal_outcomes (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                goal_id        TEXT,
                task           TEXT NOT NULL,
                approach_taken TEXT,
                duration_ms    INTEGER,
                success_score  REAL,
                blockers_json  TEXT NOT NULL DEFAULT '[]',
                created_at     TEXT NOT NULL
            );
        """)


def create_goal(
    title: str,
    *,
    parent_goal_id: str | None = None,
    deadline: str | None = None,
    success_criteria: str | None = None,
    subtasks: list[str] | None = None,
) -> str:
    goal_id = uuid.uuid4().hex
    with _conn() as c:
        c.execute(
            "INSERT INTO goals (goal_id, parent_goal_id, title, status, created_at,"
            " deadline, success_criteria, subtasks_json)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (goal_id, parent_goal_id, title, "active", datetime.now().isoformat(),
             deadline, success_criteria, json.dumps(subtasks or [])),
        )
    return goal_id


def _row_to_goal(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["subtasks"] = json.loads(d.pop("subtasks_json") or "[]")
    return d


def get_goal(goal_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM goals WHERE goal_id=?", (goal_id,)).fetchone()
        return _row_to_goal(row) if row else None


def get_goals(status: str | None = None, limit: int = 50) -> list[dict]:
    with _conn() as c:
        if status:
            rows = c.execute(
                "SELECT * FROM goals WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM goals ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_row_to_goal(r) for r in rows]


def update_goal_status(goal_id: str, status: str, outcome_score: float | None = None) -> None:
    with _conn() as c:
        if outcome_score is None:
            c.execute("UPDATE goals SET status=? WHERE goal_id=?", (status, goal_id))
        else:
            c.execute(
                "UPDATE goals SET status=?, outcome_score=? WHERE goal_id=?",
                (status, outcome_score, goal_id),
            )
