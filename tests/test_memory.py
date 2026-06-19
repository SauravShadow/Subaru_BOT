import pytest
import sqlite3
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timedelta


@pytest.fixture
def mem(tmp_path):
    db = tmp_path / "test_memory.db"
    import app.services.memory as m
    original_db = m.DB_PATH
    m.DB_PATH = db
    m.init_db()
    yield m
    m.DB_PATH = original_db


def test_save_and_retrieve_memory(mem):
    mem.save_memory("ceo", "The user prefers Python over JavaScript")
    results = mem.get_relevant_memories("ceo", "Python preference")
    assert any("Python" in r for r in results)


def test_fts_relevance_ranking(mem):
    mem.save_memory("ceo", "Project Alpha uses FastAPI", importance=0.3)
    mem.save_memory("ceo", "FastAPI is the primary web framework", importance=0.9)
    results = mem.get_relevant_memories("ceo", "FastAPI framework")
    assert len(results) >= 1


def test_agent_isolation(mem):
    mem.save_memory("ceo",     "CEO memory: executive strategy")
    mem.save_memory("backend", "Backend memory: database schema")
    ceo_results     = mem.get_relevant_memories("ceo",     "memory")
    backend_results = mem.get_relevant_memories("backend", "memory")
    assert any("executive" in r for r in ceo_results)
    assert not any("executive" in r for r in backend_results)


def test_shared_memories_visible_to_all(mem):
    mem.save_memory("shared", "Global config: port 3030")
    results = mem.get_relevant_memories("ceo", "port config")
    assert any("3030" in r for r in results)


def test_empty_query_returns_empty(mem):
    mem.save_memory("ceo", "some content")
    assert mem.get_relevant_memories("ceo", "") == []


def test_save_and_get_preference(mem):
    mem.save_preference("theme", "dark")
    assert mem.get_preference("theme") == "dark"
    assert mem.get_preference("missing", "default") == "default"


def test_decay_old_memories(mem):
    mem.save_memory("ceo", "Old news")
    conn = sqlite3.connect(str(mem.DB_PATH))
    old_date = (datetime.now() - timedelta(days=10)).isoformat()
    conn.execute("UPDATE memories SET last_hit_at=?", (old_date,))
    conn.commit()
    conn.close()
    count = mem.decay_old_memories(days_threshold=7, decay_amount=0.1)
    assert count >= 1


def test_get_relevant_memories_handles_punctuated_query(mem):
    mem.save_memory("maya", "Applied to Stripe's backend role")
    results = mem.get_relevant_memories("maya", "Stripe's backend role?")
    assert any("Stripe" in r for r in results)


def test_get_relevant_memories_handles_fts5_operator_characters(mem):
    mem.save_memory("maya", "Looking for C++ backend engineers in Bangalore")
    results = mem.get_relevant_memories("maya", "C++ backend")
    assert any("C++" in r for r in results)


def test_fts_escape_handles_commas_and_colons():
    from app.services.memory import _fts_escape
    assert _fts_escape('deploy app, port 3030: done') == '"deploy" "app" "port" "3030" "done"'


def test_fts_escape_empty_punctuation_only():
    from app.services.memory import _fts_escape
    assert _fts_escape('?!,;') == ''


def test_query_with_commas_does_not_error(tmp_path, monkeypatch):
    from app.services import memory
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "mem.db")
    memory.init_db()
    memory.save_memory("ceo", "deployed trading dashboard on port 8002")
    rows = memory.get_relevant_memories("ceo", "trading, dashboard: port")
    assert rows and "trading" in rows[0]


def test_get_shared_memories_ranks_by_importance(mem):
    mem.save_memory("shared", "Company mission: ship reliable agents", importance=0.9)
    mem.save_memory("shared", "Minor shared note", importance=0.2)
    results = mem.get_shared_memories(limit=5)
    assert any("mission" in r for r in results)
    assert results[0] == "Company mission: ship reliable agents"  # highest importance first


def test_get_shared_memories_ignores_non_shared(mem):
    mem.save_memory("ceo", "CEO-only private note", importance=0.9)
    mem.save_memory("shared", "Shared broadcast note", importance=0.5)
    results = mem.get_shared_memories(limit=5)
    assert any("broadcast" in r for r in results)
    assert not any("private" in r for r in results)


def test_get_shared_memories_no_keyword_needed(mem):
    # Unlike get_relevant_memories, this needs no query/keyword match.
    mem.save_memory("shared", "Zzxq unrelated token", importance=0.7)
    results = mem.get_shared_memories(limit=5)
    assert any("Zzxq" in r for r in results)


def test_context_block_includes_shared_without_keyword(mem, monkeypatch):
    import app.agents.runner as runner
    monkeypatch.setattr(runner, "mem_svc", mem)
    mem.save_memory("shared", "Always-on fact: prefer Engine B for calls", importance=0.9)
    block = runner._build_context_block("backend", "totally unrelated query about widgets")
    assert "Always-on fact" in block


def test_save_memory_with_goal_id(mem):
    mem.save_memory("ceo", "Picked Postgres for payments", goal_id="goal-123")
    results = mem.get_memories_by_goal("goal-123")
    assert any("Postgres" in r for r in results)


def test_get_memories_by_goal_filters(mem):
    mem.save_memory("ceo", "Belongs to goal A", goal_id="A")
    mem.save_memory("ceo", "Belongs to goal B", goal_id="B")
    mem.save_memory("ceo", "No goal at all")
    a = mem.get_memories_by_goal("A")
    assert any("goal A" in r for r in a)
    assert not any("goal B" in r for r in a)
    assert not any("No goal" in r for r in a)


def test_save_memory_without_goal_still_works(mem):
    # Backward compatibility — goal_id is optional.
    mem.save_memory("ceo", "Plain memory, no goal")
    results = mem.get_relevant_memories("ceo", "Plain memory")
    assert any("Plain memory" in r for r in results)
