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
