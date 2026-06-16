"""In-memory call session store + SQLite persistence for completed calls."""
import json
import sqlite3
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app import config

logger = logging.getLogger(__name__)

_active: dict[str, "CallSession"] = {}
_ccid_to_call_id: dict[str, str] = {}


@dataclass
class ScriptEntry:
    idx: int
    question: str       # expected question from other party
    answer: str         # text answer
    audio_path: str     # path to pre-rendered WAV file
    used: bool = False


@dataclass
class Turn:
    speaker: str        # "them" | "nexus"
    text: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class CallSession:
    call_id: str
    direction: str      # "outbound" | "inbound"
    number: str
    goal: str
    language: str
    speaker: str        # TTS voice name
    script: list[ScriptEntry] = field(default_factory=list)
    transcript: list[Turn] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.utcnow)
    status: str = "prep"   # prep | dialing | connected | ended
    telnyx_call_control_id: Optional[str] = None
    # Live-turn state (human-like loop)
    is_speaking: bool = False
    last_interim_text: str = ""
    last_interim_at: float = 0.0
    pending_caller_text: Optional[str] = None
    responded_text: str = ""
    silence_task: object = None
    turn: object = None
    speculative_key: str = ""
    speculative_text: str = ""


def _conn(db_path=None) -> sqlite3.Connection:
    path = db_path or config.MEMORY_DB
    c = sqlite3.connect(str(path), timeout=5.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=5000")
    return c


def _init_db_path(db_path=None):
    with _conn(db_path) as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript("""
            CREATE TABLE IF NOT EXISTS calls (
                id              TEXT PRIMARY KEY,
                direction       TEXT,
                number          TEXT,
                goal            TEXT,
                language        TEXT,
                outcome         TEXT,
                summary         TEXT,
                transcript_json TEXT,
                started_at      TEXT,
                ended_at        TEXT
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS calls_fts USING fts5(
                goal,
                summary,
                transcript_json,
                id UNINDEXED,
                tokenize='porter unicode61'
            );
        """)


def _init_db():
    _init_db_path(config.MEMORY_DB)


_init_db()


def create_session(call_id: str, direction: str, number: str,
                   goal: str, language: str, speaker: str) -> CallSession:
    sess = CallSession(
        call_id=call_id, direction=direction, number=number,
        goal=goal, language=language, speaker=speaker,
    )
    _active[call_id] = sess
    return sess


def get_session(call_id: str) -> Optional[CallSession]:
    return _active.get(call_id)


def bind_call_control_id(call_control_id: str, call_id: str) -> None:
    """Map a Telnyx call_control_id to our internal call_id."""
    _ccid_to_call_id[call_control_id] = call_id


def resolve_call_id(call_control_id: str) -> Optional[str]:
    return _ccid_to_call_id.get(call_control_id)


def list_active() -> list[dict]:
    """Summaries of all in-progress calls (for the live dashboard)."""
    return [
        {"call_id": s.call_id, "status": s.status, "number": s.number,
         "goal": s.goal, "direction": s.direction}
        for s in _active.values()
    ]


def add_turn(call_id: str, speaker: str, text: str) -> None:
    sess = _active.get(call_id)
    if sess:
        sess.transcript.append(Turn(speaker=speaker, text=text))


def end_session(call_id: str, outcome: str, summary: str) -> None:
    sess = _active.pop(call_id, None)
    if not sess:
        return
    for ccid, cid in list(_ccid_to_call_id.items()):
        if cid == call_id:
            _ccid_to_call_id.pop(ccid, None)
    sess.status = "ended"
    transcript_json = json.dumps([
        {"speaker": t.speaker, "text": t.text, "timestamp": t.timestamp}
        for t in sess.transcript
    ])
    with _conn() as c:
        c.execute(
            """INSERT OR REPLACE INTO calls
               (id, direction, number, goal, language, outcome, summary, transcript_json, started_at, ended_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (call_id, sess.direction, sess.number, sess.goal, sess.language,
             outcome, summary, transcript_json,
             sess.started_at.isoformat(), datetime.utcnow().isoformat()),
        )
        c.execute(
            "INSERT OR REPLACE INTO calls_fts(id, goal, summary, transcript_json) VALUES (?,?,?,?)",
            (call_id, sess.goal, summary, transcript_json),
        )


def get_call_history(direction: str = "", outcome: str = "",
                     number_prefix: str = "", limit: int = 50) -> list[dict]:
    query = "SELECT id, direction, number, goal, outcome, summary, started_at, ended_at FROM calls WHERE 1=1"
    params: list = []
    if direction:
        query += " AND direction=?"; params.append(direction)
    if outcome:
        query += " AND outcome=?"; params.append(outcome)
    if number_prefix:
        query += " AND number LIKE ?"; params.append(number_prefix + "%")
    query += " ORDER BY started_at DESC LIMIT ?"
    params.append(limit)
    with _conn() as c:
        rows = c.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_transcript(call_id: str) -> Optional[dict]:
    with _conn() as c:
        row = c.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["transcript"] = json.loads(d.pop("transcript_json", "[]"))
    return d


def search_calls(q: str, limit: int = 20) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            """SELECT c.id, c.direction, c.number, c.goal, c.outcome, c.summary, c.started_at
               FROM calls_fts f JOIN calls c ON c.id = f.id
               WHERE calls_fts MATCH ? ORDER BY rank LIMIT ?""",
            (q, limit),
        ).fetchall()
    return [dict(r) for r in rows]
