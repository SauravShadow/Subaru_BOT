# Calling Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add bidirectional Twilio telephony to NEXUS — a dedicated `call_agent` handles inbound calls and outbound calls (user-initiated or agent-autonomous), using pre-rendered TTS audio for outbound and Twilio TTS for inbound, with full transcript history and search.

**Architecture:** A new `call_agent` is registered in `AGENT_DEFS` **and added as a 6th LangGraph worker** (`_KNOWN_AGENTS` + `WORKER_IDS`); it owns all telephony. Outbound calls run a pre-call prep phase (LLM script generation → edge-tts pre-render → Twilio dial); live call state is managed via Twilio webhooks with fuzzy Q&A matching. **Unmatched outbound questions and all inbound turns are answered by a sub-2s Gemini-flash fast path** (`call_prep.quick_reply`) spoken via Twilio `<Say>` — never the full agentic loop. Agents trigger calls autonomously via a `[MAKE_CALL: number | goal | language]` tag.

**Tech Stack:** Twilio Python SDK (`twilio>=9.0.0`), `edge-tts` (mature neural voice), `google-genai` (Gemini-flash live replies), `difflib` (fuzzy match stdlib), FastAPI background tasks, SQLite FTS5, React/TypeScript (CallPanel)

---

## Reconciliation Update (2026-06-14)

This plan was reconciled against the live codebase + three confirmed decisions. Changes from the original draft, all folded into the tasks below:

1. **Live turns use Gemini-flash, not the agentic loop** (decision: "Gemini-flash fast path"). New `call_prep.quick_reply()` (Task 5b) replaces the outbound no-match static line (Task 7) and the inbound `_inbound_agent_reply` (Task 8). The original inbound `run_agent("ceo", …, thread_id=…)` was also a bug — `run_agent(agent_id, prompt, send, model)` has no `thread_id` param.
2. **`call_agent` is a real LangGraph worker** (decision: "full delegated graph worker"). Registering it in `AGENT_DEFS` is not enough — Task 6 now also adds `"call_agent"` to `_KNOWN_AGENTS` (`app/graph/nexus_graph.py`) and `WORKER_IDS` (`nexus-ui/src/store.ts`).
3. **Twilio SDK + rebuild** (decision: confirmed) — already reflected in Task 1.
4. **`[MAKE_CALL]` tag wiring** (review fix). `make_call()` existed but nothing parsed agent output to invoke it, so the agent-autonomous path was dead. New Task 6b wires `[MAKE_CALL: number | goal | language]` into `parse_tool_call` + `_execute_tool`.
5. **Route ordering** (review fix). All `@router.*` call routes MUST be inserted **above** the `# ── SPA fallback (must be last)` catch-all in `app/api/router.py` — see the note in Task 7.
6. **edge-tts sidesteps the gTTS 200-char cap.** Call audio always passes `voice=speaker`, so it goes through `_edge_tts_wav` (full text), not the `MAX_TTS_CHARS`-truncated `_gtts_wav` path. No extra change needed; just don't route call lines through the gTTS branch.

`BASE_URL` (Task 1) is the public Cloudflare-tunnel URL Twilio reaches — it already covers the "public base URL" requirement.

---

## File Structure

```
NEW:
  app/services/telephony.py          Twilio SDK wrapper + TwiML builders
  app/agents/call_prep.py            Script generation (LLM) + TTS pre-render + fuzzy match
  app/services/call_store.py         CallSession dataclass, in-memory dict, SQLite CRUD
  nexus-ui/src/components/CallPanel.tsx  Full calling UI
  tests/test_call_store.py
  tests/test_call_prep.py
  tests/test_telephony.py

MODIFIED:
  requirements.txt                   Add twilio>=9.0.0
  bark-lite/requirements.txt         Add edge-tts
  bark-lite/main.py                  Add voice param + edge-tts support
  app/services/bark_client.py        Add voice param to speak()
  app/config.py                      Add TWILIO_*, BARK_SPEAKER, BASE_URL
  app/agents/definitions.py          Register call_agent
  app/agents/tools.py                Add make_call, get_call_transcript, list_calls tools
  app/api/router.py                  Add all call endpoints
```

---

## Task 1: Dependencies + Config

**Files:**
- Modify: `requirements.txt`
- Modify: `bark-lite/requirements.txt`
- Modify: `app/config.py`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add twilio to requirements.txt**

Open `requirements.txt` and add after the last line:
```
twilio>=9.0.0
edge-tts>=7.0.0
```

- [ ] **Step 2: Add edge-tts to bark-lite/requirements.txt**

Open `bark-lite/requirements.txt` and add:
```
edge-tts>=7.0.0
```

- [ ] **Step 3: Add config vars to app/config.py**

Open `app/config.py` and add after the `# Bark TTS sidecar` block:

```python
# Twilio telephony
TWILIO_ACCOUNT_SID  = os.environ.get("TWILIO_ACCOUNT_SID",  "")
TWILIO_AUTH_TOKEN   = os.environ.get("TWILIO_AUTH_TOKEN",   "")
TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER", "")
BASE_URL            = os.environ.get("BASE_URL", "")  # public Cloudflare tunnel URL e.g. https://nexus.example.com

# Voice
BARK_SPEAKER = os.environ.get("BARK_SPEAKER", "en-US-GuyNeural")  # edge-tts voice name
```

- [ ] **Step 4: Add env vars to docker-compose.yml**

In the `virtual-company` service `environment:` block, add:
```yaml
      - TWILIO_ACCOUNT_SID=${TWILIO_ACCOUNT_SID:-}
      - TWILIO_AUTH_TOKEN=${TWILIO_AUTH_TOKEN:-}
      - TWILIO_PHONE_NUMBER=${TWILIO_PHONE_NUMBER:-}
      - BASE_URL=${BASE_URL:-}
      - BARK_SPEAKER=${BARK_SPEAKER:-en-US-GuyNeural}
```

- [ ] **Step 5: Rebuild container to install new deps**

```bash
docker compose build virtual-company bark-svc && docker compose up -d
```

Expected: Both services rebuild and start without errors.

- [ ] **Step 6: Verify twilio installed**

```bash
docker exec virtual-company python -c "import twilio; print(twilio.__version__)"
```

Expected: prints a version like `9.x.x`

- [ ] **Step 7: Commit**

```bash
git add requirements.txt bark-lite/requirements.txt app/config.py docker-compose.yml
git commit -m "feat(calls): add Twilio + edge-tts deps and config vars"
```

---

## Task 2: call_store.py — Data Layer

**Files:**
- Create: `app/services/call_store.py`
- Create: `tests/test_call_store.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_call_store.py`:

```python
import pytest
from datetime import datetime
from app.services.call_store import (
    CallSession, ScriptEntry, Turn,
    create_session, get_session, add_turn,
    end_session, search_calls, get_call_history,
)
# NOTE: ScriptEntry is the canonical definition — call_prep.py imports from here


def _make_session(call_id="test-123"):
    return create_session(
        call_id=call_id,
        direction="outbound",
        number="+919876543210",
        goal="Book a table for 2 at 7pm",
        language="en",
        speaker="en-US-GuyNeural",
    )


def test_create_and_get_session():
    sess = _make_session("sess-1")
    assert sess.call_id == "sess-1"
    assert sess.status == "prep"
    retrieved = get_session("sess-1")
    assert retrieved is not None
    assert retrieved.number == "+919876543210"


def test_add_turn():
    _make_session("sess-2")
    add_turn("sess-2", speaker="them", text="Hello how can I help?")
    add_turn("sess-2", speaker="nexus", text="Hi, booking table for 2.")
    sess = get_session("sess-2")
    assert len(sess.transcript) == 2
    assert sess.transcript[0].speaker == "them"
    assert sess.transcript[1].text == "Hi, booking table for 2."


def test_end_session_writes_to_sqlite(tmp_path, monkeypatch):
    import app.config as cfg
    monkeypatch.setattr(cfg, "MEMORY_DB", tmp_path / "test.db")
    from app.services import call_store
    monkeypatch.setattr(call_store, "_init_db", lambda: call_store._init_db_path(tmp_path / "test.db"))
    call_store._init_db()

    _make_session("sess-3")
    add_turn("sess-3", "them", "How many people?")
    add_turn("sess-3", "nexus", "2 people please.")
    end_session("sess-3", outcome="success", summary="Table booked for 2 at 7pm.")

    assert get_session("sess-3") is None  # removed from in-memory

    history = get_call_history()
    assert any(c["id"] == "sess-3" for c in history)
    row = next(c for c in history if c["id"] == "sess-3")
    assert row["summary"] == "Table booked for 2 at 7pm."


def test_search_calls(tmp_path, monkeypatch):
    import app.config as cfg
    monkeypatch.setattr(cfg, "MEMORY_DB", tmp_path / "test2.db")
    from app.services import call_store
    call_store._init_db()

    create_session("s4", "outbound", "+1234567890", "Book flight to Mumbai", "en", "en-US-GuyNeural")
    add_turn("s4", "them", "What date?")
    add_turn("s4", "nexus", "20th June please.")
    end_session("s4", "success", "Flight enquiry done.")

    results = search_calls("Mumbai")
    assert any(r["id"] == "s4" for r in results)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
docker exec virtual-company pytest tests/test_call_store.py -v 2>&1 | head -20
```

Expected: `ImportError` or `ModuleNotFoundError` — `call_store` doesn't exist yet.

- [ ] **Step 3: Create app/services/call_store.py**

```python
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
    twilio_sid: Optional[str] = None


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


def add_turn(call_id: str, speaker: str, text: str) -> None:
    sess = _active.get(call_id)
    if sess:
        sess.transcript.append(Turn(speaker=speaker, text=text))


def end_session(call_id: str, outcome: str, summary: str) -> None:
    sess = _active.pop(call_id, None)
    if not sess:
        return
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
```

- [ ] **Step 4: Run tests**

```bash
docker exec virtual-company pytest tests/test_call_store.py -v
```

Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/call_store.py tests/test_call_store.py
git commit -m "feat(calls): add call_store data layer with SQLite FTS5 persistence"
```

---

## Task 3: bark-lite Voice Improvement (edge-tts)

**Files:**
- Modify: `bark-lite/main.py`
- Modify: `app/services/bark_client.py`
- Create: `tests/test_bark_voice.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_bark_voice.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx


@pytest.mark.asyncio
async def test_speak_passes_voice_param():
    """speak() must forward the voice kwarg to bark-svc."""
    from app.services import bark_client
    captured = {}

    async def fake_post(url, json=None, timeout=None):
        captured.update(json or {})
        resp = AsyncMock()
        resp.json = MagicMock(return_value={"audio": "dGVzdA=="})
        resp.raise_for_status = MagicMock()
        return resp

    with patch("httpx.AsyncClient.post", side_effect=fake_post):
        await bark_client.speak("Hello world", "calm", voice="en-US-GuyNeural")

    assert captured.get("voice") == "en-US-GuyNeural"


@pytest.mark.asyncio
async def test_speak_omits_voice_when_none():
    """speak() without voice kwarg still works (backward compat)."""
    from app.services import bark_client
    captured = {}

    async def fake_post(url, json=None, timeout=None):
        captured.update(json or {})
        resp = AsyncMock()
        resp.json = MagicMock(return_value={"audio": "dGVzdA=="})
        resp.raise_for_status = MagicMock()
        return resp

    with patch("httpx.AsyncClient.post", side_effect=fake_post):
        await bark_client.speak("Hello world", "calm")

    assert "voice" not in captured
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
docker exec virtual-company pytest tests/test_bark_voice.py -v 2>&1 | head -20
```

Expected: FAIL — `speak()` doesn't accept `voice` kwarg.

- [ ] **Step 3: Update app/services/bark_client.py — add voice param**

Open `app/services/bark_client.py`. Replace the `speak` function:

```python
async def speak(text: str, emotion: str = "calm", voice: str | None = None) -> str | None:
    """POST /speak → base64 WAV string, or None if bark-svc is unavailable."""
    try:
        payload: dict = {"text": text, "emotion": emotion}
        if voice:
            payload["voice"] = voice
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{config.BARK_SVC_URL}/speak",
                json=payload,
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()["audio"]
    except Exception as exc:
        logger.warning("bark_client.speak failed: %s", exc)
        return None
```

- [ ] **Step 4: Run test — should still fail (bark-svc doesn't accept voice yet)**

```bash
docker exec virtual-company pytest tests/test_bark_voice.py::test_speak_passes_voice_param -v
```

Expected: PASS (the mock captures the payload). The second test should also pass.

- [ ] **Step 5: Update bark-lite/main.py — add edge-tts voice support**

Open `bark-lite/main.py`. Update `SpeakRequest` and add edge-tts function:

```python
import asyncio

class SpeakRequest(BaseModel):
    text: str
    emotion: str = "calm"
    agent_id: str = ""
    voice: str = ""   # edge-tts voice name e.g. "en-US-GuyNeural"; empty = use gTTS


async def _edge_tts_wav(text: str, voice: str) -> bytes:
    """Generate WAV bytes via edge-tts (Microsoft neural voices)."""
    import edge_tts
    import io
    from pydub import AudioSegment

    communicate = edge_tts.Communicate(text, voice)
    mp3_chunks = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3_chunks.append(chunk["data"])
    mp3_bytes = b"".join(mp3_chunks)
    audio = AudioSegment.from_mp3(io.BytesIO(mp3_bytes))
    buf = io.BytesIO()
    audio.export(buf, format="wav")
    return buf.getvalue()


@app.post("/speak")
async def speak(req: SpeakRequest):
    try:
        if req.voice:
            wav = await _edge_tts_wav(req.text, req.voice)
        else:
            wav = _speak_wav(req.text, req.emotion)
    except Exception as exc:
        logger.error("speak failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    return {"audio": _wav_to_b64(wav)}
```

- [ ] **Step 6: Rebuild bark-svc to install edge-tts**

```bash
docker compose build bark-svc && docker compose up -d bark-svc
```

Expected: Builds successfully. `edge-tts` installed in image.

- [ ] **Step 7: Smoke-test edge-tts voice in bark-svc**

```bash
curl -s -X POST http://127.0.0.1:3031/api/bark/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello, this is NEXUS calling.", "voice": "en-US-GuyNeural"}' \
  | python3 -c "import sys,json,base64; d=json.load(sys.stdin); open('/tmp/test_voice.wav','wb').write(base64.b64decode(d['audio'])); print('WAV written, size:', len(d['audio']))"
```

Expected: prints `WAV written, size: <number>` — no error.

- [ ] **Step 8: Run all bark tests to confirm no regression**

```bash
docker exec virtual-company pytest tests/test_bark_client.py tests/test_bark_voice.py -v
```

Expected: All tests PASS.

- [ ] **Step 9: Commit**

```bash
git add bark-lite/main.py bark-lite/requirements.txt app/services/bark_client.py tests/test_bark_voice.py
git commit -m "feat(calls): add edge-tts support to bark-svc for mature adult voice"
```

---

## Task 4: telephony.py — Twilio Wrapper

**Files:**
- Create: `app/services/telephony.py`
- Create: `tests/test_telephony.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_telephony.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from app.services.telephony import (
    build_play_and_gather, build_say_and_gather,
    build_hangup, dial_outbound, validate_twilio_request,
)


def test_build_play_and_gather_contains_play_url():
    twiml = build_play_and_gather(
        audio_url="https://example.com/api/calls/audio/abc/0",
        gather_action="https://example.com/api/calls/gather?call_id=abc&turn=1",
    )
    assert "<Play>" in twiml
    assert "audio/abc/0" in twiml
    assert "<Gather" in twiml
    assert "gather?call_id=abc&turn=1" in twiml


def test_build_say_and_gather_contains_text():
    twiml = build_say_and_gather(
        text="Sorry, I didn't catch that.",
        gather_action="https://example.com/api/calls/gather?call_id=abc&turn=2",
        language="en-US",
    )
    assert "Sorry, I didn't catch that." in twiml
    assert "<Say" in twiml
    assert "<Gather" in twiml


def test_build_hangup():
    twiml = build_hangup(final_text="Thank you, goodbye!")
    assert "<Hangup" in twiml
    assert "Thank you, goodbye!" in twiml


def test_dial_outbound_calls_twilio():
    mock_call = MagicMock()
    mock_call.sid = "CA1234567890"
    mock_client = MagicMock()
    mock_client.calls.create.return_value = mock_call

    with patch("app.services.telephony._get_client", return_value=mock_client):
        sid = dial_outbound(
            to="+919876543210",
            call_id="call-abc",
            webhook_url="https://example.com/api/calls/gather?call_id=call-abc&turn=0",
        )

    assert sid == "CA1234567890"
    mock_client.calls.create.assert_called_once()
    call_kwargs = mock_client.calls.create.call_args[1]
    assert call_kwargs["to"] == "+919876543210"
    assert "gather?call_id=call-abc&turn=0" in call_kwargs["url"]


def test_validate_twilio_request_calls_validator():
    with patch("app.services.telephony.RequestValidator") as mock_rv:
        instance = mock_rv.return_value
        instance.validate.return_value = True
        result = validate_twilio_request(
            url="https://example.com/api/calls/gather",
            params={"CallSid": "CA123"},
            signature="abc123",
        )
    assert result is True
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
docker exec virtual-company pytest tests/test_telephony.py -v 2>&1 | head -20
```

Expected: `ImportError` — `telephony` module doesn't exist.

- [ ] **Step 3: Create app/services/telephony.py**

```python
"""Twilio SDK wrapper — TwiML builders, outbound dialer, webhook validator."""
import logging
from typing import Optional

from twilio.rest import Client
from twilio.request_validator import RequestValidator
from twilio.twiml.voice_response import VoiceResponse, Gather, Play, Say

from app import config

logger = logging.getLogger(__name__)

_GATHER_TIMEOUT  = 8    # seconds of silence before timeout
_GATHER_LANGUAGE = "en-US"


def _get_client() -> Client:
    if not config.TWILIO_ACCOUNT_SID or not config.TWILIO_AUTH_TOKEN:
        raise RuntimeError("TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN not configured")
    return Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)


def build_play_and_gather(audio_url: str, gather_action: str,
                          language: str = _GATHER_LANGUAGE) -> str:
    """TwiML: play pre-rendered audio then listen for speech."""
    resp = VoiceResponse()
    gather = Gather(
        input="speech",
        timeout=_GATHER_TIMEOUT,
        action=gather_action,
        method="POST",
        language=language,
    )
    gather.play(audio_url)
    resp.append(gather)
    return str(resp)


def build_say_and_gather(text: str, gather_action: str,
                         language: str = _GATHER_LANGUAGE) -> str:
    """TwiML: speak text via Twilio TTS then listen for speech."""
    resp = VoiceResponse()
    gather = Gather(
        input="speech",
        timeout=_GATHER_TIMEOUT,
        action=gather_action,
        method="POST",
        language=language,
    )
    gather.say(text, language=language)
    resp.append(gather)
    return str(resp)


def build_hangup(final_text: str = "", language: str = _GATHER_LANGUAGE) -> str:
    """TwiML: optionally say a closing line then hang up."""
    resp = VoiceResponse()
    if final_text:
        resp.say(final_text, language=language)
    resp.hangup()
    return str(resp)


def dial_outbound(to: str, call_id: str, webhook_url: str) -> str:
    """Dial a number via Twilio. Returns the call SID."""
    client = _get_client()
    if not config.TWILIO_PHONE_NUMBER:
        raise RuntimeError("TWILIO_PHONE_NUMBER not configured")
    call = client.calls.create(
        to=to,
        from_=config.TWILIO_PHONE_NUMBER,
        url=webhook_url,
        method="POST",
    )
    logger.info("Dialed %s → SID %s", to, call.sid)
    return call.sid


def validate_twilio_request(url: str, params: dict, signature: str) -> bool:
    """Verify the X-Twilio-Signature header to confirm the webhook is genuine."""
    validator = RequestValidator(config.TWILIO_AUTH_TOKEN)
    return validator.validate(url, params, signature)
```

- [ ] **Step 4: Run tests**

```bash
docker exec virtual-company pytest tests/test_telephony.py -v
```

Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/telephony.py tests/test_telephony.py
git commit -m "feat(calls): add telephony service — Twilio wrapper and TwiML builders"
```

---

## Task 5: call_prep.py — Script Generation + Fuzzy Match

**Files:**
- Create: `app/agents/call_prep.py`
- Create: `tests/test_call_prep.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_call_prep.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.call_store import ScriptEntry
from app.agents.call_prep import match_utterance, generate_script_prompt


def _entry(idx, question, answer):
    return ScriptEntry(idx=idx, question=question, answer=answer, audio_path="", used=False)


def test_match_utterance_exact():
    script = [
        _entry(0, "How many people?", "2 people please."),
        _entry(1, "What time would you like?", "7pm please."),
    ]
    match = match_utterance("how many people", script)
    assert match is not None
    assert match.idx == 0


def test_match_utterance_fuzzy():
    script = [
        _entry(0, "Can I get your name?", "Sure, it's Saurav."),
        _entry(1, "Any dietary restrictions?", "No restrictions, thank you."),
    ]
    match = match_utterance("what is your name please", script)
    assert match is not None
    assert match.idx == 0


def test_match_utterance_no_match():
    script = [
        _entry(0, "How many people?", "2 people please."),
    ]
    match = match_utterance("please hold the line", script, threshold=0.6)
    assert match is None


def test_match_utterance_skips_used():
    script = [
        _entry(0, "How many people?", "2 people."),
        _entry(1, "What time?", "7pm."),
    ]
    script[0].used = True
    match = match_utterance("how many people", script)
    # Should not match idx=0 (used), fallback to no match or idx=1
    assert match is None or match.idx != 0


def test_generate_script_prompt_contains_goal():
    prompt = generate_script_prompt(
        goal="Book a table for 2 at 7pm at Spice Garden restaurant",
        language="en",
    )
    assert "Book a table" in prompt
    assert "JSON" in prompt
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
docker exec virtual-company pytest tests/test_call_prep.py -v 2>&1 | head -20
```

Expected: `ImportError` — `call_prep` doesn't exist.

- [ ] **Step 3: Create app/agents/call_prep.py**

```python
"""
Pre-call prep: LLM script generation, TTS pre-render, fuzzy Q&A matching.
"""
import asyncio
import base64
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from app import config
from app.services import bark_client
from app.services.call_store import ScriptEntry   # canonical definition lives in call_store

logger = logging.getLogger(__name__)

_AUDIO_DIR = Path(tempfile.gettempdir()) / "nexus_calls"
_AUDIO_DIR.mkdir(parents=True, exist_ok=True)


def generate_script_prompt(goal: str, language: str = "en") -> str:
    return f"""You are preparing a phone call script for an AI assistant named NEXUS.

CALL GOAL: {goal}
LANGUAGE: {language}

Generate a JSON object with this exact structure:
{{
  "opening": "<first thing NEXUS says when call connects>",
  "script": [
    {{"question": "<likely thing the other party says>", "answer": "<NEXUS response>"}},
    ... (8-12 entries covering the most likely conversation turns)
  ],
  "closing": "<final line before hanging up>"
}}

Rules:
- Write naturally, conversationally — not robotic
- Cover the most likely questions/responses for this specific goal
- Keep each answer under 30 words
- Output ONLY the JSON, no explanation
"""


async def generate_script(goal: str, language: str = "en") -> dict:
    """Call LLM to generate a call script. Returns dict with opening/script/closing."""
    prompt = generate_script_prompt(goal, language)
    try:
        import anthropic
        client = anthropic.AsyncAnthropic()
        msg = await client.messages.create(
            model=config.DEFAULT_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)
    except Exception as exc:
        logger.error("Script generation failed: %s", exc)
        return {
            "opening": f"Hello, I'm calling regarding: {goal}",
            "script": [],
            "closing": "Thank you for your time. Goodbye.",
        }


async def prerender_audio(
    script_data: dict,
    call_id: str,
    speaker: str,
) -> list[ScriptEntry]:
    """Pre-render all script lines to WAV files. Returns list of ScriptEntry."""
    call_dir = _AUDIO_DIR / call_id
    call_dir.mkdir(parents=True, exist_ok=True)
    entries: list[ScriptEntry] = []

    lines: list[tuple[str, str]] = []  # (question, answer)
    lines.append(("", script_data.get("opening", "")))
    for item in script_data.get("script", []):
        lines.append((item.get("question", ""), item.get("answer", "")))
    lines.append(("", script_data.get("closing", "")))

    async def render_one(idx: int, question: str, answer: str) -> ScriptEntry:
        wav_path = str(call_dir / f"{idx}.wav")
        audio_b64 = await bark_client.speak(answer, "calm", voice=speaker)
        if audio_b64:
            wav_bytes = base64.b64decode(audio_b64)
            Path(wav_path).write_bytes(wav_bytes)
        else:
            wav_path = ""
            logger.warning("Pre-render failed for entry %d: %s", idx, answer)
        return ScriptEntry(idx=idx, question=question, answer=answer, audio_path=wav_path)

    tasks = [render_one(i, q, a) for i, (q, a) in enumerate(lines)]
    return list(await asyncio.gather(*tasks))


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def match_utterance(
    stt_text: str,
    script: list[ScriptEntry],
    threshold: float = 0.45,
) -> Optional[ScriptEntry]:
    """Fuzzy-match STT text against unused script entries. Returns best match or None."""
    best_score, best_entry = 0.0, None
    for entry in script:
        if entry.used or not entry.question:
            continue
        score = _similarity(stt_text, entry.question)
        if score > best_score:
            best_score, best_entry = score, entry
    return best_entry if best_score >= threshold else None


def cleanup_call_audio(call_id: str) -> None:
    """Remove temp WAV files after a call ends."""
    import shutil
    call_dir = _AUDIO_DIR / call_id
    if call_dir.exists():
        shutil.rmtree(call_dir, ignore_errors=True)
```

- [ ] **Step 4: Run tests**

```bash
docker exec virtual-company pytest tests/test_call_prep.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/agents/call_prep.py tests/test_call_prep.py
git commit -m "feat(calls): add call_prep — script generation, Bark pre-render, fuzzy match"
```

---

## Task 5b: Gemini-flash live reply (`quick_reply`)

Sub-2s contextual reply for live call turns (outbound no-match + all inbound turns). Used by Tasks 7 and 8 instead of the agentic loop.

**Files:**
- Modify: `app/agents/call_prep.py`
- Create: `tests/test_call_quick_reply.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_call_quick_reply.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from app.services.call_store import Turn


@pytest.mark.asyncio
async def test_quick_reply_uses_gemini_flash(monkeypatch):
    from app.agents import call_prep
    monkeypatch.setattr(call_prep.config, "GEMINI_API_KEY", "key")

    fake_resp = MagicMock(text="Sure, 7pm works for two people.")
    fake_models = MagicMock()
    fake_models.generate_content.return_value = fake_resp
    fake_client = MagicMock(models=fake_models)

    with patch("google.genai.Client", return_value=fake_client):
        out = await call_prep.quick_reply(
            goal="Book a table for 2 at 7pm",
            transcript=[Turn(speaker="them", text="What time did you want?")],
            language="en")
    assert "7pm" in out
    assert fake_models.generate_content.call_args.kwargs["model"] == "gemini-3.5-flash"


@pytest.mark.asyncio
async def test_quick_reply_safe_fallback_without_key(monkeypatch):
    from app.agents import call_prep
    monkeypatch.setattr(call_prep.config, "GEMINI_API_KEY", "")
    out = await call_prep.quick_reply("goal", [Turn("them", "hi")], "en")
    assert isinstance(out, str) and out  # non-empty safe fallback
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
docker exec virtual-company pytest tests/test_call_quick_reply.py -v 2>&1 | head -20
```

Expected: FAIL — `AttributeError: module 'app.agents.call_prep' has no attribute 'quick_reply'`.

- [ ] **Step 3: Add `quick_reply` to `app/agents/call_prep.py`**

Insert this function before `def cleanup_call_audio` (the file already imports `asyncio`, `config`, and `logger`):

```python
_FALLBACK_REPLY = "Sorry, could you repeat that?"


async def quick_reply(goal: str, transcript: list, language: str = "en") -> str:
    """Sub-2s Gemini-flash reply for a live call turn. Never raises.

    `transcript` is a list of call_store.Turn (objects with .speaker/.text).
    """
    if not config.GEMINI_API_KEY:
        return _FALLBACK_REPLY
    convo = "\n".join(
        f"{'You' if t.speaker == 'nexus' else 'Caller'}: {t.text}"
        for t in transcript[-8:]
    )
    prompt = (
        f"You are NEXUS on a live phone call. Goal: {goal}\n"
        f"Reply in {language}. ONE short spoken sentence — no markdown, no emojis, "
        f"no stage directions. If the goal is met or the caller is done, close politely.\n\n"
        f"Conversation so far:\n{convo}\n\nYour next spoken line:"
    )
    try:
        import google.genai as genai
        client = genai.Client(api_key=config.GEMINI_API_KEY)
        resp = await asyncio.wait_for(
            asyncio.to_thread(
                client.models.generate_content,
                model="gemini-3.5-flash",
                contents=prompt,
            ),
            timeout=4.0,
        )
        return (resp.text or "").strip() or _FALLBACK_REPLY
    except Exception as exc:
        logger.warning("quick_reply failed: %s", exc)
        return _FALLBACK_REPLY
```

- [ ] **Step 4: Run test to verify it passes**

```bash
docker exec virtual-company pytest tests/test_call_quick_reply.py -v
```

Expected: Both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/agents/call_prep.py tests/test_call_quick_reply.py
git commit -m "feat(calls): Gemini-flash quick_reply for live call turns"
```

---

## Task 6: call_agent Definition + Agent Tools

**Files:**
- Modify: `app/agents/definitions.py`
- Modify: `app/agents/tools.py`

- [ ] **Step 1: Add call_agent to AGENT_DEFS in app/agents/definitions.py**

Open `app/agents/definitions.py`. Add a persona function before `AGENT_DEFS`:

```python
def _call_agent_persona() -> str:
    return f"""You are NEXUS Call Agent — a specialist in voice telephony.

YOUR ROLE:
- Prepare and execute outbound phone calls on behalf of the user
- Handle inbound calls to the NEXUS Twilio number
- Generate natural, context-aware call scripts
- Report call outcomes and transcripts clearly

TOOLS AVAILABLE:
  make_call(number, goal, language) — dial a number and run a scripted call
  get_call_transcript(call_id)      — retrieve full transcript of a past call
  list_calls(limit)                 — list recent call history

COMMUNICATION:
- Always confirm what number you dialled and the outcome
- Report key information extracted from the call (booking reference, name, time, etc.)
- If a call fails, explain why and suggest retry
- Working directory: {config.WORK_DIR}
"""
```

Then inside `AGENT_DEFS`, add after the last existing agent:

```python
    "call_agent": {
        "name":        "Call Agent",
        "title":       "Voice Call Specialist",
        "color":       "#22c55e",
        "avatar":      "CA",
        "description": "Handles all voice calls — outbound prep, live call execution, inbound responses, transcripts.",
        "persona":     _call_agent_persona,
    },
```

- [ ] **Step 2: Verify call_agent appears in agents API**

```bash
curl -s http://127.0.0.1:3031/api/agents | python3 -m json.tool | grep -A3 "call_agent"
```

Expected: shows `"call_agent"` key with `name`, `title`, `description`.

- [ ] **Step 3: Write failing test for make_call tool**

Add to `tests/test_call_store.py` (or create `tests/test_call_tools.py`):

Create `tests/test_call_tools.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_make_call_tool_returns_call_id():
    """make_call returns a dict with call_id and status."""
    with patch("app.agents.tools.run_outbound_call", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"call_id": "abc-123", "status": "dialing", "twilio_sid": "CA999"}
        from app.agents.tools import make_call
        result = await make_call(number="+919876543210", goal="Book a table", language="en")
    assert result["call_id"] == "abc-123"
    assert result["status"] == "dialing"


@pytest.mark.asyncio
async def test_get_call_transcript_tool():
    """get_call_transcript returns transcript for a known call_id."""
    with patch("app.agents.tools.call_store") as mock_store:
        mock_store.get_transcript.return_value = {
            "id": "abc-123",
            "goal": "Book a table",
            "transcript": [{"speaker": "nexus", "text": "Hello!"}],
        }
        from app.agents.tools import get_call_transcript
        result = await get_call_transcript(call_id="abc-123")
    assert result["id"] == "abc-123"
    assert len(result["transcript"]) == 1
```

- [ ] **Step 4: Run to confirm failure**

```bash
docker exec virtual-company pytest tests/test_call_tools.py -v 2>&1 | head -20
```

Expected: `ImportError` — `make_call`, `run_outbound_call` not yet in `tools.py`.

- [ ] **Step 5: Add tools to app/agents/tools.py**

Open `app/agents/tools.py` and add at the bottom (before any `__all__` if present):

```python
# ── Telephony tools ────────────────────────────────────────────────────────────

from app.services import call_store as _call_store
from app.services import call_store


async def run_outbound_call(number: str, goal: str, language: str = "en") -> dict:
    """Full async orchestration: script gen → pre-render → dial. Returns session info."""
    import uuid
    from app.agents.call_prep import generate_script, prerender_audio
    from app.services.telephony import dial_outbound
    from app import config as cfg

    if not cfg.TWILIO_ACCOUNT_SID:
        return {"error": "Twilio not configured — set TWILIO_ACCOUNT_SID in .env"}
    if not cfg.BASE_URL:
        return {"error": "BASE_URL not configured — set public tunnel URL in .env"}

    call_id = str(uuid.uuid4())
    speaker = cfg.BARK_SPEAKER

    sess = call_store.create_session(
        call_id=call_id, direction="outbound",
        number=number, goal=goal, language=language, speaker=speaker,
    )
    sess.status = "prep"

    script_data = await generate_script(goal, language)
    entries = await prerender_audio(script_data, call_id, speaker)
    sess.script = entries
    sess.status = "dialing"

    webhook_url = f"{cfg.BASE_URL}/api/calls/gather?call_id={call_id}&turn=0"
    twilio_sid = dial_outbound(to=number, call_id=call_id, webhook_url=webhook_url)
    sess.twilio_sid = twilio_sid

    return {"call_id": call_id, "status": "dialing", "twilio_sid": twilio_sid}


async def make_call(number: str, goal: str, language: str = "en") -> dict:
    """Agent tool: make an outbound phone call."""
    return await run_outbound_call(number=number, goal=goal, language=language)


async def get_call_transcript(call_id: str) -> dict:
    """Agent tool: retrieve the transcript of a completed call."""
    result = call_store.get_transcript(call_id)
    if result is None:
        return {"error": f"No call found with id {call_id}"}
    return result


async def list_calls(limit: int = 20) -> list:
    """Agent tool: list recent call history."""
    return call_store.get_call_history(limit=limit)
```

- [ ] **Step 6: Run tests**

```bash
docker exec virtual-company pytest tests/test_call_tools.py -v
```

Expected: Both tests PASS.

- [ ] **Step 7: Commit**

```bash
git add app/agents/definitions.py app/agents/tools.py tests/test_call_tools.py
git commit -m "feat(calls): add call_agent definition and make_call/transcript/list tools"
```

---

## Task 7: Outbound Call API + Audio Serving

**Files:**
- Modify: `app/api/router.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_call_api_outbound.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def test_outbound_call_returns_call_id(client):
    with patch("app.agents.tools.run_outbound_call", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"call_id": "test-call-1", "status": "dialing", "twilio_sid": "CA123"}
        resp = client.post("/api/calls/outbound", json={
            "number": "+919876543210",
            "goal": "Book a table for 2 at 7pm",
            "language": "en",
        })
    assert resp.status_code == 200
    assert resp.json()["call_id"] == "test-call-1"
    assert resp.json()["status"] == "dialing"


def test_audio_endpoint_serves_wav(client, tmp_path):
    import base64
    from app.agents.call_prep import _AUDIO_DIR
    wav_dir = _AUDIO_DIR / "call-xyz"
    wav_dir.mkdir(parents=True, exist_ok=True)
    (wav_dir / "0.wav").write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")

    resp = client.get("/api/calls/audio/call-xyz/0")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/wav"


def test_audio_endpoint_404_for_missing(client):
    resp = client.get("/api/calls/audio/nonexistent-call/0")
    assert resp.status_code == 404


def test_gather_webhook_returns_twiml(client):
    from app.services.call_store import create_session, ScriptEntry
    sess = create_session("wh-test", "outbound", "+1234", "test goal", "en", "en-US-GuyNeural")
    sess.script = [
        ScriptEntry(idx=0, question="", answer="Hello!", audio_path="/tmp/nexus_calls/wh-test/0.wav", used=False),
        ScriptEntry(idx=1, question="How many people?", answer="2 people.", audio_path="/tmp/nexus_calls/wh-test/1.wav", used=False),
    ]
    import os; os.makedirs("/tmp/nexus_calls/wh-test", exist_ok=True)
    open("/tmp/nexus_calls/wh-test/0.wav", "wb").write(b"RIFF")

    with patch("app.api.router.validate_twilio_request", return_value=True):
        resp = client.post("/api/calls/gather", data={
            "CallSid": "CA999",
            "SpeechResult": "",
            "call_id": "wh-test",
            "turn": "0",
        })
    assert resp.status_code == 200
    assert "xml" in resp.headers["content-type"]
```

- [ ] **Step 2: Run to confirm failure**

```bash
docker exec virtual-company pytest tests/test_call_api_outbound.py -v 2>&1 | head -30
```

Expected: failures due to missing routes.

- [ ] **Step 3: Add outbound endpoints to app/api/router.py**

Open `app/api/router.py`. Add these imports at the top with the other imports:

```python
from pathlib import Path
from fastapi import BackgroundTasks, Request
from fastapi.responses import Response, FileResponse
from app.agents.tools import run_outbound_call
from app.services.telephony import (
    build_play_and_gather, build_say_and_gather, build_hangup, validate_twilio_request
)
from app.services import call_store
from app.agents.call_prep import match_utterance, cleanup_call_audio, _AUDIO_DIR
from app import config
```

Then add these routes to the router (before the end of the file):

```python
# ── Outbound call — user-initiated ─────────────────────────────────────────────

@router.post("/api/calls/outbound")
async def api_call_outbound(body: dict, background_tasks: BackgroundTasks):
    number   = body.get("number", "")
    goal     = body.get("goal", "")
    language = body.get("language", "en")
    if not number or not goal:
        return JSONResponse({"error": "number and goal required"}, status_code=400)
    result = await run_outbound_call(number=number, goal=goal, language=language)
    return result


# ── Audio serving — Twilio fetches pre-rendered WAV files ──────────────────────

@router.get("/api/calls/audio/{call_id}/{idx}")
async def api_call_audio(call_id: str, idx: int):
    wav_path = _AUDIO_DIR / call_id / f"{idx}.wav"
    if not wav_path.exists():
        return JSONResponse({"error": "audio not found"}, status_code=404)
    return FileResponse(str(wav_path), media_type="audio/wav")


# ── Outbound gather webhook — Twilio posts STT result here ─────────────────────

@router.post("/api/calls/gather")
async def api_calls_gather(request: Request, background_tasks: BackgroundTasks):
    form    = await request.form()
    params  = dict(form)
    sig     = request.headers.get("X-Twilio-Signature", "")
    url     = str(request.url)
    call_id = str(form.get("call_id", ""))
    turn    = int(form.get("turn", 0))
    speech  = str(form.get("SpeechResult", "")).strip()

    if config.TWILIO_AUTH_TOKEN and not validate_twilio_request(url, params, sig):
        return Response("Forbidden", status_code=403)

    sess = call_store.get_session(call_id)
    if not sess:
        return Response(build_hangup("Session expired. Goodbye."), media_type="application/xml")

    gather_url = f"{config.BASE_URL}/api/calls/gather?call_id={call_id}&turn={turn + 1}"

    # turn=0: play opening (idx=0 in script)
    if turn == 0 and sess.script:
        entry = sess.script[0]
        entry.used = True
        sess.status = "connected"
        call_store.add_turn(call_id, "nexus", entry.answer)
        audio_url = f"{config.BASE_URL}/api/calls/audio/{call_id}/0"
        return Response(
            build_play_and_gather(audio_url=audio_url, gather_action=gather_url, language=sess.language),
            media_type="application/xml",
        )

    # Subsequent turns: match speech to script
    if speech:
        call_store.add_turn(call_id, "them", speech)

        # Check if it's a goodbye signal
        goodbye_words = {"bye", "goodbye", "thank you", "that's all", "no thanks", "thanks bye"}
        if any(w in speech.lower() for w in goodbye_words):
            closing = next((e for e in sess.script if e.idx == len(sess.script) - 1), None)
            closing_text = closing.answer if closing else "Thank you. Goodbye!"
            call_store.add_turn(call_id, "nexus", closing_text)
            background_tasks.add_task(
                call_store.end_session, call_id, "success",
                f"Call completed. Last exchange: {speech[:80]}"
            )
            background_tasks.add_task(cleanup_call_audio, call_id)
            return Response(build_hangup(closing_text), media_type="application/xml")

        matched = match_utterance(speech, sess.script)
        if matched and matched.audio_path and Path(matched.audio_path).exists():
            matched.used = True
            call_store.add_turn(call_id, "nexus", matched.answer)
            audio_url = f"{config.BASE_URL}/api/calls/audio/{call_id}/{matched.idx}"
            return Response(
                build_play_and_gather(audio_url=audio_url, gather_action=gather_url, language=sess.language),
                media_type="application/xml",
            )

        # No match — fallback to Twilio TTS with a generic bridging line
        fallback = "Could you please repeat that?"
        call_store.add_turn(call_id, "nexus", fallback)
        return Response(
            build_say_and_gather(text=fallback, gather_action=gather_url, language=sess.language),
            media_type="application/xml",
        )

    # No speech detected — re-prompt once
    prompt = "Sorry, I didn't catch that. Could you please say that again?"
    return Response(
        build_say_and_gather(text=prompt, gather_action=gather_url, language=sess.language),
        media_type="application/xml",
    )
```

- [ ] **Step 4: Run tests**

```bash
docker exec virtual-company pytest tests/test_call_api_outbound.py -v
```

Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/api/router.py tests/test_call_api_outbound.py
git commit -m "feat(calls): add outbound call API, audio serving, and Twilio gather webhook"
```

---

## Task 8: Inbound Call API

**Files:**
- Modify: `app/api/router.py`
- Create: `tests/test_call_api_inbound.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_call_api_inbound.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def test_inbound_call_returns_twiml_greeting(client):
    with patch("app.api.router.validate_twilio_request", return_value=True):
        resp = client.post("/api/calls/inbound", data={
            "CallSid": "CA_inbound_001",
            "From": "+919876543210",
            "To": "+12025551234",
        })
    assert resp.status_code == 200
    content = resp.text
    assert "<Say" in content or "<Gather" in content
    assert "NEXUS" in content or "nexus" in content.lower()


def test_inbound_respond_returns_twiml(client):
    """After caller speaks, respond returns Say+Gather TwiML."""
    from app.services.call_store import create_session
    create_session("in-001", "inbound", "+919876543210", "inbound call", "en", "en-US-GuyNeural")

    with patch("app.api.router.validate_twilio_request", return_value=True):
        with patch("app.api.router._inbound_agent_reply", new_callable=AsyncMock) as mock_reply:
            mock_reply.return_value = "I can help with that. What else do you need?"
            resp = client.post("/api/calls/inbound/respond", data={
                "CallSid": "CA_inbound_001",
                "SpeechResult": "What is the status of my project?",
                "call_id": "in-001",
            })
    assert resp.status_code == 200
    assert "I can help" in resp.text
```

- [ ] **Step 2: Run to confirm failure**

```bash
docker exec virtual-company pytest tests/test_call_api_inbound.py -v 2>&1 | head -20
```

Expected: failures — inbound routes don't exist.

- [ ] **Step 3: Add inbound endpoints to app/api/router.py**

Add to `app/api/router.py` (after the outbound routes):

```python
# ── Inbound call helpers ────────────────────────────────────────────────────────

async def _inbound_agent_reply(call_id: str, speech: str) -> str:
    """Run a CEO/call_agent turn for an inbound call. Returns plain text reply."""
    import uuid
    from app.agents import runner as _runner
    thread_id = f"call-{call_id}"
    try:
        result = await asyncio.wait_for(
            _runner.run_agent("ceo", speech, thread_id=thread_id),
            timeout=10.0,
        )
        # Strip SPEAK tag if present
        import re as _re
        m = _re.search(r'\[SPEAK:\s*(.*?)\s*\|', result or "")
        return m.group(1) if m else (result or "I'm sorry, I couldn't process that.")
    except asyncio.TimeoutError:
        return "I'm processing that. Could you repeat your question?"
    except Exception as exc:
        logger.warning("Inbound agent reply failed: %s", exc)
        return "I'm having trouble right now. Please try again."


# ── Inbound call — Twilio calls our number ─────────────────────────────────────

@router.post("/api/calls/inbound")
async def api_calls_inbound(request: Request):
    form = await request.form()
    params = dict(form)
    sig = request.headers.get("X-Twilio-Signature", "")
    url = str(request.url)

    if config.TWILIO_AUTH_TOKEN and not validate_twilio_request(url, params, sig):
        return Response("Forbidden", status_code=403)

    caller    = str(form.get("From", "unknown"))
    call_sid  = str(form.get("CallSid", ""))
    call_id   = call_sid or caller.replace("+", "")

    call_store.create_session(
        call_id=call_id, direction="inbound",
        number=caller, goal="inbound call",
        language="en", speaker=config.BARK_SPEAKER,
    )

    respond_url = f"{config.BASE_URL}/api/calls/inbound/respond?call_id={call_id}"
    greeting = "Hi, this is NEXUS, your AI assistant. How can I help you today?"
    call_store.add_turn(call_id, "nexus", greeting)

    return Response(
        build_say_and_gather(text=greeting, gather_action=respond_url, language="en-US"),
        media_type="application/xml",
    )


@router.post("/api/calls/inbound/respond")
async def api_calls_inbound_respond(request: Request, background_tasks: BackgroundTasks):
    form    = await request.form()
    params  = dict(form)
    sig     = request.headers.get("X-Twilio-Signature", "")
    url     = str(request.url)
    call_id = str(form.get("call_id", ""))
    speech  = str(form.get("SpeechResult", "")).strip()

    if config.TWILIO_AUTH_TOKEN and not validate_twilio_request(url, params, sig):
        return Response("Forbidden", status_code=403)

    sess = call_store.get_session(call_id)
    respond_url = f"{config.BASE_URL}/api/calls/inbound/respond?call_id={call_id}"

    if speech:
        call_store.add_turn(call_id, "them", speech)

        goodbye_words = {"bye", "goodbye", "that's all", "thanks bye", "no thanks"}
        if any(w in speech.lower() for w in goodbye_words):
            farewell = "Thank you for calling. Have a great day! Goodbye."
            call_store.add_turn(call_id, "nexus", farewell)
            if sess:
                background_tasks.add_task(
                    call_store.end_session, call_id, "success",
                    f"Inbound call from {sess.number} completed."
                )
            return Response(build_hangup(farewell), media_type="application/xml")

        reply = await _inbound_agent_reply(call_id, speech)
        call_store.add_turn(call_id, "nexus", reply)
        return Response(
            build_say_and_gather(text=reply, gather_action=respond_url, language="en-US"),
            media_type="application/xml",
        )

    prompt = "I didn't catch that. Could you say it again?"
    return Response(
        build_say_and_gather(text=prompt, gather_action=respond_url, language="en-US"),
        media_type="application/xml",
    )
```

Also add `import asyncio` and `import logging` at the top of `router.py` if not already present:
```python
import asyncio
import logging
logger = logging.getLogger(__name__)
```

- [ ] **Step 4: Run tests**

```bash
docker exec virtual-company pytest tests/test_call_api_inbound.py -v
```

Expected: Both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/api/router.py tests/test_call_api_inbound.py
git commit -m "feat(calls): add inbound call webhooks with live agent response"
```

---

## Task 9: History + Search API

**Files:**
- Modify: `app/api/router.py`
- Create: `tests/test_call_api_history.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_call_api_history.py`:

```python
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def test_call_history_returns_list(client):
    with patch("app.api.router.call_store") as mock_store:
        mock_store.get_call_history.return_value = [
            {"id": "c1", "direction": "outbound", "number": "+91123", "goal": "Book table",
             "outcome": "success", "summary": "Table booked.", "started_at": "2026-06-14T10:00:00"},
        ]
        resp = client.get("/api/calls/history")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert data[0]["id"] == "c1"


def test_call_history_filters_passed(client):
    with patch("app.api.router.call_store") as mock_store:
        mock_store.get_call_history.return_value = []
        client.get("/api/calls/history?direction=outbound&outcome=success&number=+91")
        mock_store.get_call_history.assert_called_once_with(
            direction="outbound", outcome="success", number_prefix="+91", limit=50
        )


def test_call_transcript_returns_detail(client):
    with patch("app.api.router.call_store") as mock_store:
        mock_store.get_transcript.return_value = {
            "id": "c2", "goal": "Book flight",
            "transcript": [{"speaker": "nexus", "text": "Hello!", "timestamp": "2026-06-14T10:01:00"}],
        }
        resp = client.get("/api/calls/c2/transcript")
    assert resp.status_code == 200
    assert resp.json()["id"] == "c2"
    assert len(resp.json()["transcript"]) == 1


def test_call_transcript_404_for_missing(client):
    with patch("app.api.router.call_store") as mock_store:
        mock_store.get_transcript.return_value = None
        resp = client.get("/api/calls/nonexistent/transcript")
    assert resp.status_code == 404


def test_call_search_returns_results(client):
    with patch("app.api.router.call_store") as mock_store:
        mock_store.search_calls.return_value = [
            {"id": "c3", "goal": "Book flight to Mumbai", "summary": "Flight enquiry done."}
        ]
        resp = client.get("/api/calls/search?q=Mumbai")
    assert resp.status_code == 200
    assert resp.json()[0]["id"] == "c3"
```

- [ ] **Step 2: Run to confirm failure**

```bash
docker exec virtual-company pytest tests/test_call_api_history.py -v 2>&1 | head -20
```

Expected: failures — history/search routes don't exist.

- [ ] **Step 3: Add history + search endpoints to app/api/router.py**

Add after the inbound routes:

```python
# ── Call history + search ───────────────────────────────────────────────────────

@router.get("/api/calls/history")
async def api_calls_history(
    direction: str = "",
    outcome: str = "",
    number: str = "",
    limit: int = 50,
):
    return call_store.get_call_history(
        direction=direction, outcome=outcome,
        number_prefix=number, limit=limit,
    )


@router.get("/api/calls/search")
async def api_calls_search(q: str = "", limit: int = 20):
    if not q:
        return []
    return call_store.search_calls(q=q, limit=limit)


@router.get("/api/calls/{call_id}/transcript")
async def api_call_transcript(call_id: str):
    result = call_store.get_transcript(call_id)
    if result is None:
        return JSONResponse({"error": f"No call found: {call_id}"}, status_code=404)
    return result
```

- [ ] **Step 4: Run tests**

```bash
docker exec virtual-company pytest tests/test_call_api_history.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 5: Run full test suite to confirm no regressions**

```bash
docker exec virtual-company pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: All tests PASS (or pre-existing failures are unchanged).

- [ ] **Step 6: Commit**

```bash
git add app/api/router.py tests/test_call_api_history.py
git commit -m "feat(calls): add call history, transcript, and full-text search endpoints"
```

---

## Task 10: CallPanel.tsx — Frontend UI

**Files:**
- Create: `nexus-ui/src/components/CallPanel.tsx`
- Modify: `nexus-ui/src/store.ts` (handle `call_*` WS events)
- Modify: `nexus-ui/src/components/NexusScene.tsx` or sidebar (add entry point)

- [ ] **Step 1: Handle call WebSocket events in store.ts**

Open `nexus-ui/src/store.ts`. Find where WS messages are dispatched (look for `data.type === 'audio'` or similar). Add handling for call events in the same switch/if block:

```typescript
// In the WS message handler, add these cases alongside existing ones:
if (data.type === 'call_started') {
  set(state => ({
    activeCall: {
      call_id: data.call_id,
      number: data.number,
      goal: data.goal,
      status: 'dialing',
      transcript: [],
    }
  }))
}
if (data.type === 'call_turn') {
  set(state => ({
    activeCall: state.activeCall ? {
      ...state.activeCall,
      transcript: [...state.activeCall.transcript, { speaker: data.speaker, text: data.text }],
    } : null
  }))
}
if (data.type === 'call_complete') {
  set(state => ({
    activeCall: state.activeCall ? { ...state.activeCall, status: 'ended', summary: data.summary } : null
  }))
}
```

Also add `activeCall` to the Zustand store state type:

```typescript
// In the store state interface, add:
activeCall: {
  call_id: string
  number: string
  goal: string
  status: 'prep' | 'dialing' | 'connected' | 'ended'
  transcript: { speaker: string; text: string }[]
  summary?: string
} | null
```

And initialize it as `null` in the default state.

- [ ] **Step 2: Create nexus-ui/src/components/CallPanel.tsx**

```typescript
import React, { useState, useEffect, useRef } from 'react'

interface CallHistory {
  id: string
  direction: string
  number: string
  goal: string
  outcome: string
  summary: string
  started_at: string
}

interface TranscriptTurn {
  speaker: string
  text: string
  timestamp?: string
}

interface ActiveCallState {
  call_id: string
  number: string
  goal: string
  status: string
  transcript: TranscriptTurn[]
  summary?: string
}

const VOICE_OPTIONS = [
  { value: 'en-US-GuyNeural', label: 'Guy (US Male)' },
  { value: 'en-US-JennyNeural', label: 'Jenny (US Female)' },
  { value: 'en-GB-RyanNeural', label: 'Ryan (UK Male)' },
  { value: 'en-IN-PrabhatNeural', label: 'Prabhat (IN Male)' },
  { value: 'hi-IN-MadhurNeural', label: 'Madhur (Hindi Male)' },
]

const LANGUAGE_OPTIONS = [
  { value: 'en', label: 'English' },
  { value: 'hi', label: 'Hindi' },
  { value: 'es', label: 'Spanish' },
  { value: 'fr', label: 'French' },
  { value: 'de', label: 'German' },
]

function StatusDot({ status }: { status: string }) {
  const colors: Record<string, string> = {
    prep: '#f59e0b', dialing: '#3b82f6', connected: '#22c55e', ended: '#6b7280'
  }
  return (
    <span
      style={{
        display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
        background: colors[status] ?? '#6b7280', marginRight: 6,
        boxShadow: status === 'connected' ? '0 0 6px #22c55e' : 'none',
      }}
    />
  )
}

export default function CallPanel() {
  const [number, setNumber] = useState('')
  const [goal, setGoal] = useState('')
  const [language, setLanguage] = useState('en')
  const [voice, setVoice] = useState('en-US-GuyNeural')
  const [calling, setCalling] = useState(false)
  const [activeCall, setActiveCall] = useState<ActiveCallState | null>(null)
  const [history, setHistory] = useState<CallHistory[]>([])
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [transcript, setTranscript] = useState<TranscriptTurn[] | null>(null)
  const [searchQ, setSearchQ] = useState('')
  const [filterDirection, setFilterDirection] = useState('')
  const [filterOutcome, setFilterOutcome] = useState('')
  const transcriptEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetchHistory()
  }, [])

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [activeCall?.transcript])

  const fetchHistory = async (q?: string) => {
    try {
      let url = '/api/calls/history?limit=50'
      if (filterDirection) url += `&direction=${filterDirection}`
      if (filterOutcome) url += `&outcome=${filterOutcome}`
      const resp = await fetch(q ? `/api/calls/search?q=${encodeURIComponent(q)}` : url)
      setHistory(await resp.json())
    } catch (e) { console.error('Failed to fetch call history', e) }
  }

  const handleSearch = (e: React.ChangeEvent<HTMLInputElement>) => {
    setSearchQ(e.target.value)
    fetchHistory(e.target.value || undefined)
  }

  const handleCall = async () => {
    if (!number.trim() || !goal.trim() || calling) return
    setCalling(true)
    setActiveCall({ call_id: '', number, goal, status: 'prep', transcript: [] })
    try {
      const resp = await fetch('/api/calls/outbound', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ number, goal, language, voice }),
      })
      const data = await resp.json()
      if (data.error) {
        setActiveCall(prev => prev ? { ...prev, status: 'ended', summary: `Error: ${data.error}` } : null)
      } else {
        setActiveCall(prev => prev ? { ...prev, call_id: data.call_id, status: 'dialing' } : null)
      }
    } catch (e) {
      setActiveCall(prev => prev ? { ...prev, status: 'ended', summary: 'Network error' } : null)
    } finally {
      setCalling(false)
    }
  }

  const loadTranscript = async (callId: string) => {
    if (expandedId === callId) {
      setExpandedId(null); setTranscript(null); return
    }
    setExpandedId(callId)
    try {
      const resp = await fetch(`/api/calls/${callId}/transcript`)
      const data = await resp.json()
      setTranscript(data.transcript || [])
    } catch { setTranscript([]) }
  }

  const statusLabel: Record<string, string> = {
    prep: 'Preparing script...', dialing: 'Dialing...', connected: 'Connected', ended: 'Ended'
  }

  return (
    <div style={{ padding: 20, fontFamily: 'monospace', color: '#e2e8f0', maxWidth: 600, margin: '0 auto' }}>
      <h2 style={{ color: '#22c55e', marginBottom: 16, fontSize: 18 }}>📞 Call Panel</h2>

      {/* Outbound call form */}
      <div style={{ background: '#1e293b', borderRadius: 8, padding: 16, marginBottom: 20, border: '1px solid #334155' }}>
        <input
          placeholder="+91 98XXXXXXXX"
          value={number}
          onChange={e => setNumber(e.target.value)}
          style={{ width: '100%', padding: '8px 12px', marginBottom: 8, background: '#0f172a', border: '1px solid #475569', borderRadius: 6, color: '#e2e8f0', fontSize: 14, boxSizing: 'border-box' }}
        />
        <textarea
          placeholder="Goal: e.g. Book a table for 2 at 7pm at Spice Garden"
          value={goal}
          onChange={e => setGoal(e.target.value)}
          rows={2}
          style={{ width: '100%', padding: '8px 12px', marginBottom: 8, background: '#0f172a', border: '1px solid #475569', borderRadius: 6, color: '#e2e8f0', fontSize: 14, resize: 'none', boxSizing: 'border-box' }}
        />
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <select value={language} onChange={e => setLanguage(e.target.value)}
            style={{ flex: 1, padding: '6px 10px', background: '#0f172a', border: '1px solid #475569', borderRadius: 6, color: '#e2e8f0', fontSize: 13 }}>
            {LANGUAGE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <select value={voice} onChange={e => setVoice(e.target.value)}
            style={{ flex: 1, padding: '6px 10px', background: '#0f172a', border: '1px solid #475569', borderRadius: 6, color: '#e2e8f0', fontSize: 13 }}>
            {VOICE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <button
          onClick={handleCall}
          disabled={calling || !number.trim() || !goal.trim()}
          style={{ width: '100%', padding: '10px 0', background: calling ? '#374151' : '#22c55e', color: '#000', fontWeight: 700, border: 'none', borderRadius: 6, cursor: calling ? 'not-allowed' : 'pointer', fontSize: 14 }}>
          {calling ? 'Initiating call...' : '📞 Call'}
        </button>
      </div>

      {/* Active call live view */}
      {activeCall && (
        <div style={{ background: '#1e293b', borderRadius: 8, padding: 16, marginBottom: 20, border: '1px solid #22c55e' }}>
          <div style={{ marginBottom: 10, fontSize: 13, color: '#94a3b8' }}>
            <StatusDot status={activeCall.status} />
            <strong style={{ color: '#e2e8f0' }}>{activeCall.number}</strong>
            {' — '}{statusLabel[activeCall.status] ?? activeCall.status}
          </div>
          <div style={{ maxHeight: 220, overflowY: 'auto' }}>
            {activeCall.transcript.map((t, i) => (
              <div key={i} style={{ marginBottom: 6, fontSize: 13 }}>
                <span style={{ color: t.speaker === 'nexus' ? '#22c55e' : '#94a3b8', marginRight: 6 }}>
                  {t.speaker === 'nexus' ? '🤖 NEXUS:' : '🗣 Them:'}
                </span>
                <span style={{ color: '#e2e8f0' }}>{t.text}</span>
              </div>
            ))}
            {activeCall.status === 'ended' && activeCall.summary && (
              <div style={{ marginTop: 10, padding: '8px 10px', background: '#0f172a', borderRadius: 6, fontSize: 12, color: '#94a3b8' }}>
                ✅ {activeCall.summary}
              </div>
            )}
            <div ref={transcriptEndRef} />
          </div>
        </div>
      )}

      {/* Search + filters */}
      <div style={{ marginBottom: 12, display: 'flex', gap: 8 }}>
        <input
          placeholder="🔍 Search calls..."
          value={searchQ}
          onChange={handleSearch}
          style={{ flex: 2, padding: '7px 12px', background: '#1e293b', border: '1px solid #334155', borderRadius: 6, color: '#e2e8f0', fontSize: 13 }}
        />
        <select value={filterDirection} onChange={e => { setFilterDirection(e.target.value); fetchHistory() }}
          style={{ flex: 1, padding: '7px 10px', background: '#1e293b', border: '1px solid #334155', borderRadius: 6, color: '#e2e8f0', fontSize: 12 }}>
          <option value="">All directions</option>
          <option value="outbound">Outbound</option>
          <option value="inbound">Inbound</option>
        </select>
        <select value={filterOutcome} onChange={e => { setFilterOutcome(e.target.value); fetchHistory() }}
          style={{ flex: 1, padding: '7px 10px', background: '#1e293b', border: '1px solid #334155', borderRadius: 6, color: '#e2e8f0', fontSize: 12 }}>
          <option value="">All outcomes</option>
          <option value="success">Success</option>
          <option value="failed">Failed</option>
        </select>
      </div>

      {/* Call history */}
      <div>
        <div style={{ fontSize: 12, color: '#64748b', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 1 }}>
          Call History
        </div>
        {history.length === 0 && (
          <div style={{ color: '#475569', fontSize: 13, textAlign: 'center', padding: 20 }}>No calls yet.</div>
        )}
        {history.map(call => (
          <div key={call.id} style={{ marginBottom: 8 }}>
            <div
              onClick={() => loadTranscript(call.id)}
              style={{ background: '#1e293b', borderRadius: 6, padding: '10px 14px', cursor: 'pointer', border: '1px solid #334155', display: 'flex', alignItems: 'center', gap: 10, fontSize: 13 }}>
              <span>{call.outcome === 'success' ? '✅' : '❌'}</span>
              <span style={{ color: '#e2e8f0', minWidth: 130 }}>{call.number}</span>
              <span style={{ color: '#94a3b8', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{call.goal}</span>
              <span style={{ color: '#475569', fontSize: 11 }}>{new Date(call.started_at).toLocaleString()}</span>
            </div>
            {expandedId === call.id && transcript && (
              <div style={{ background: '#0f172a', borderRadius: '0 0 6px 6px', padding: '10px 14px', border: '1px solid #334155', borderTop: 'none' }}>
                {call.summary && <div style={{ color: '#94a3b8', fontSize: 12, marginBottom: 8 }}>📋 {call.summary}</div>}
                {transcript.map((t, i) => (
                  <div key={i} style={{ marginBottom: 5, fontSize: 12 }}>
                    <span style={{ color: t.speaker === 'nexus' ? '#22c55e' : '#60a5fa', marginRight: 6 }}>
                      {t.speaker === 'nexus' ? '🤖 NEXUS:' : '🗣 Them:'}
                    </span>
                    <span style={{ color: '#cbd5e1' }}>{t.text}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Add CallPanel to the main UI**

Open `nexus-ui/src/components/NexusScene.tsx` (or wherever the sidebar/tab navigation lives). Import and add the panel:

```typescript
import CallPanel from './CallPanel'
```

Find where other panels/tabs are rendered and add a Phone tab. The exact integration depends on the existing tab system. Look for where `OpsDrawer`, `AgentDetailView`, or similar panels are conditionally rendered, and add:

```typescript
{activeTab === 'calls' && <CallPanel />}
```

And add the tab button alongside the existing tab buttons:

```typescript
<button
  onClick={() => setActiveTab('calls')}
  style={{ /* match existing tab button styles */ }}
  title="Calls"
>
  📞
</button>
```

- [ ] **Step 4: Add 'voice' to the outbound POST body in run_outbound_call**

Open `app/agents/tools.py`. Update `run_outbound_call` to accept and pass through a `voice` param from the request body. Open `app/api/router.py` and update the `/api/calls/outbound` endpoint to extract `voice` from the body and pass it:

In `app/api/router.py`, update `api_call_outbound`:
```python
@router.post("/api/calls/outbound")
async def api_call_outbound(body: dict, background_tasks: BackgroundTasks):
    number   = body.get("number", "")
    goal     = body.get("goal", "")
    language = body.get("language", "en")
    voice    = body.get("voice", config.BARK_SPEAKER)
    if not number or not goal:
        return JSONResponse({"error": "number and goal required"}, status_code=400)
    result = await run_outbound_call(number=number, goal=goal, language=language, voice=voice)
    return result
```

In `app/agents/tools.py`, update `run_outbound_call` signature:
```python
async def run_outbound_call(number: str, goal: str, language: str = "en", voice: str = "") -> dict:
    ...
    speaker = voice or cfg.BARK_SPEAKER
    ...
```

- [ ] **Step 5: Build the frontend**

```bash
cd /home/subaru/projects/virtual-company/nexus-ui && npm run build 2>&1 | tail -10
```

Expected: Build completes with no TypeScript errors.

- [ ] **Step 6: Verify UI loads and CallPanel renders**

```bash
curl -s http://127.0.0.1:3031/ | grep -c "html"
```

Open `http://127.0.0.1:3031` in a browser, navigate to the Calls tab, and confirm:
- Form fields (number, goal, language, voice) render
- Call history section renders (empty is fine)
- Search bar is visible

- [ ] **Step 7: Commit**

```bash
git add nexus-ui/src/components/CallPanel.tsx nexus-ui/src/store.ts nexus-ui/src/components/NexusScene.tsx
git add app/api/router.py app/agents/tools.py
git commit -m "feat(calls): add CallPanel UI with live call view, history, search, and filters"
```

---

## Task 11: End-to-End Smoke Test

- [ ] **Step 1: Configure .env with Twilio credentials**

Add to your `.env` file in `/home/subaru/projects/virtual-company/`:
```
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_PHONE_NUMBER=+1XXXXXXXXXX
BASE_URL=https://your-cloudflare-tunnel-url.com
BARK_SPEAKER=en-US-GuyNeural
```

- [ ] **Step 2: Restart container to pick up new env vars**

```bash
docker compose up -d
```

- [ ] **Step 3: Verify call_agent appears in UI**

```bash
curl -s http://127.0.0.1:3031/api/agents | python3 -m json.tool | grep -A4 '"call_agent"'
```

Expected: shows call_agent with title `"Voice Call Specialist"`.

- [ ] **Step 4: Test outbound call via API**

```bash
curl -s -X POST http://127.0.0.1:3031/api/calls/outbound \
  -H "Content-Type: application/json" \
  -d '{"number": "+919876543210", "goal": "Test call — just say hello", "language": "en"}' \
  | python3 -m json.tool
```

Expected: `{"call_id": "<uuid>", "status": "dialing", "twilio_sid": "CA..."}` — Twilio phone rings.

- [ ] **Step 5: Check call history after call ends**

```bash
curl -s http://127.0.0.1:3031/api/calls/history | python3 -m json.tool
```

Expected: List with the completed call, outcome, and summary.

- [ ] **Step 6: Test search**

```bash
curl -s "http://127.0.0.1:3031/api/calls/search?q=hello" | python3 -m json.tool
```

Expected: Returns the call you just made (if "hello" is in the transcript or goal).

- [ ] **Step 7: Run full test suite**

```bash
docker exec virtual-company pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: All tests PASS.

- [ ] **Step 8: Final commit**

```bash
git add -A
git commit -m "feat(calls): complete telephony feature — Twilio bidirectional calling with pre-rendered TTS, history, search, and CallPanel UI"
```
