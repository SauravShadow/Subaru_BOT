"""Long-term memory via SQLite FTS5 with importance-weighted retrieval."""
import sqlite3
import logging
import re
from datetime import datetime
from pathlib import Path

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
            CREATE TABLE IF NOT EXISTS memories (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id    TEXT    NOT NULL,
                mem_type    TEXT    NOT NULL DEFAULT 'conversation',
                content     TEXT    NOT NULL,
                importance  REAL    NOT NULL DEFAULT 0.5,
                created_at  TEXT    NOT NULL,
                last_hit_at TEXT
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                content,
                agent_id UNINDEXED,
                tokenize='porter unicode61'
            );
            CREATE TABLE IF NOT EXISTS user_preferences (
                key        TEXT PRIMARY KEY,
                value      TEXT,
                updated_at TEXT
            );
        """)
        # Idempotent migration: add goal_id to pre-existing memories tables.
        cols = {r["name"] for r in c.execute("PRAGMA table_info(memories)")}
        if "goal_id" not in cols:
            c.execute("ALTER TABLE memories ADD COLUMN goal_id TEXT")


def save_memory(
    agent_id: str,
    content: str,
    mem_type: str = "conversation",
    importance: float = 0.5,
    goal_id: str | None = None,
) -> None:
    now = datetime.now().isoformat()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO memories (agent_id, mem_type, content, importance, created_at, goal_id)"
            " VALUES (?,?,?,?,?,?)",
            (agent_id, mem_type, content, importance, now, goal_id),
        )
        c.execute(
            "INSERT INTO memories_fts (rowid, content, agent_id) VALUES (?,?,?)",
            (cur.lastrowid, content, agent_id),
        )


def _fts_escape(query: str) -> str:
    """Tokenize to alphanumerics and quote each token — immune to FTS5 syntax."""
    tokens = re.findall(r"[A-Za-z0-9_]+", query)
    return " ".join(f'"{t}"' for t in tokens)


def get_relevant_memories(agent_id: str, query: str, limit: int = 5) -> list[str]:
    if not query.strip():
        return []
    escaped_query = _fts_escape(query)
    if not escaped_query:
        return []
    try:
        with _conn() as c:
            rows = c.execute("""
                SELECT m.id, m.content
                FROM   memories_fts f
                JOIN   memories m ON m.id = f.rowid
                WHERE  memories_fts MATCH ?
                  AND  m.agent_id IN (?, 'shared')
                ORDER  BY rank * m.importance
                LIMIT  ?
            """, (escaped_query, agent_id, limit)).fetchall()
            if rows:
                now = datetime.now().isoformat()
                ids = [r["id"] for r in rows]
                c.execute(
                    f"UPDATE memories SET last_hit_at=? WHERE id IN ({','.join('?'*len(ids))})",
                    [now] + ids,
                )
            return [r["content"] for r in rows]
    except sqlite3.OperationalError as exc:
        logger.warning("memory query failed: %s", exc)
        return []


def get_shared_memories(limit: int = 3) -> list[str]:
    """Top shared memories by importance — ALWAYS injectable (no keyword match needed)."""
    try:
        with _conn() as c:
            rows = c.execute("""
                SELECT content
                FROM   memories
                WHERE  agent_id = 'shared'
                ORDER  BY importance DESC, last_hit_at DESC
                LIMIT  ?
            """, (limit,)).fetchall()
            return [r["content"] for r in rows]
    except sqlite3.OperationalError as exc:
        logger.warning("shared memory query failed: %s", exc)
        return []


def get_memories_by_goal(goal_id: str, limit: int = 20) -> list[str]:
    """All memories tagged with a goal_id, newest first — no keyword match needed."""
    try:
        with _conn() as c:
            rows = c.execute("""
                SELECT content
                FROM   memories
                WHERE  goal_id = ?
                ORDER  BY created_at DESC
                LIMIT  ?
            """, (goal_id, limit)).fetchall()
            return [r["content"] for r in rows]
    except sqlite3.OperationalError as exc:
        logger.warning("goal memory query failed: %s", exc)
        return []


def save_preference(key: str, value: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO user_preferences (key, value, updated_at) VALUES (?,?,?)",
            (key, value, datetime.now().isoformat()),
        )


def get_preference(key: str, default: str = "") -> str:
    with _conn() as c:
        row = c.execute("SELECT value FROM user_preferences WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def decay_old_memories(days_threshold: int = 7, decay_amount: float = 0.05) -> int:
    with _conn() as c:
        result = c.execute("""
            UPDATE memories
               SET importance = MAX(0.05, importance - ?)
             WHERE (last_hit_at IS NULL OR last_hit_at < datetime('now', ?))
               AND importance > 0.05
        """, (decay_amount, f"-{days_threshold} days"))
        return result.rowcount
