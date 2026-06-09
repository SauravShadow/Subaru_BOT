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
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _conn() as c:
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


def save_memory(
    agent_id: str,
    content: str,
    mem_type: str = "conversation",
    importance: float = 0.5,
) -> None:
    now = datetime.now().isoformat()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO memories (agent_id, mem_type, content, importance, created_at)"
            " VALUES (?,?,?,?,?)",
            (agent_id, mem_type, content, importance, now),
        )
        c.execute(
            "INSERT INTO memories_fts (rowid, content, agent_id) VALUES (?,?,?)",
            (cur.lastrowid, content, agent_id),
        )


def get_relevant_memories(agent_id: str, query: str, limit: int = 5) -> list[str]:
    if not query.strip():
        return []
    # Escape FTS5 special characters by wrapping in phrase quotes only when needed.
    # This prevents syntax errors from punctuation like apostrophes and question marks
    # while maintaining original OR semantics for safe queries.
    if re.search(r"['\"]|\?", query):
        escaped_query = '"' + query.replace('"', '""') + '"'
    else:
        escaped_query = query
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
