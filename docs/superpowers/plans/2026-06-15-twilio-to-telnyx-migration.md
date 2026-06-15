# Twilio → Telnyx (Call Control) Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Twilio SDK + TwiML calling feature with the Telnyx Python SDK using the **Call Control** (event-driven JSON command) model, preserving the agent-facing behavior (`make_call`, transcripts, inbound handling).

**Architecture:** Twilio's model is "Telnyx fetches a URL that returns TwiML XML per turn." Call Control is the inverse: we `dial`/`answer` a call, Telnyx POSTs lifecycle **events** (`call.initiated`, `call.answered`, `call.transcription`, `call.hangup`, …) to a single webhook, and we reply by issuing **commands** (`answer`, `start_playback`, `speak`, `start_transcription`, `hangup`). Speech-to-text moves from Twilio's per-turn `Gather input="speech"` to a continuous `start_transcription` stream whose final `call.transcription` events become the caller's turns. The five Twilio webhooks collapse into one `/api/calls/webhook` event dispatcher; the WAV-serving endpoint stays. Our internal `call_id` is carried across events via `client_state` (base64) with a `call_control_id → call_id` map as backup.

**Tech Stack:** Python 3 · FastAPI · `telnyx>=4.0.0` (new `from telnyx import Telnyx` client) · pytest. Telnyx resources used: `client.calls.dial`, `client.calls.actions.{answer,speak,start_playback,start_transcription,hangup}`, `client.webhooks.unwrap`.

**New config / credentials (placeholders only — user fills in):**
- `TELNYX_API_KEY` — REST API key
- `TELNYX_PUBLIC_KEY` — webhook signing public key (Ed25519, for `webhooks.unwrap`)
- `TELNYX_CONNECTION_ID` — Call Control Application / connection id (required by `calls.dial`)
- `TELNYX_PHONE_NUMBER` — the `from_` number
- `TELNYX_VOICE` — TTS voice for `speak` (default `female`)
- `BASE_URL` — unchanged (public tunnel URL)

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `app/services/telephony.py` | Telnyx Call Control SDK wrapper: client, dial, command wrappers, webhook verify, client_state codec | **Rewrite** |
| `app/config.py` | swap `TWILIO_*` → `TELNYX_*` vars | Modify |
| `app/services/call_store.py` | rename `twilio_sid`→`telnyx_call_control_id`; add ccid↔call_id binding | Modify |
| `app/api/router.py` | replace 4 TwiML webhooks with one event-driven `/api/calls/webhook`; keep audio endpoint | Modify |
| `app/agents/tools.py` | `run_outbound_call` uses Telnyx; webhook_url + return key | Modify |
| `app/agents/definitions.py` | persona text "Twilio"→"Telnyx" | Modify |
| `requirements.txt` | `twilio>=9.0.0` → `telnyx>=4.0.0` | Modify |
| `docker-compose.yml` | `TWILIO_*` env → `TELNYX_*` env | Modify |
| `.env` | remove live Twilio creds; add Telnyx placeholders | Modify |
| `.env.example` | add Telnyx placeholders | Modify |
| `tests/test_telephony.py` | rewrite for Call Control wrappers | **Rewrite** |
| `tests/test_call_api_outbound.py` | rewrite for event webhook | **Rewrite** |
| `tests/test_call_api_inbound.py` | rewrite for event webhook | **Rewrite** |
| `tests/test_call_tools.py` | update mock return keys | Modify |

**Event → action map (the core behavioral contract):**

| Event | Direction | Action |
|-------|-----------|--------|
| `call.initiated` | inbound (`direction == "incoming"`) | create session keyed by `call_control_id`; `answer` |
| `call.initiated` | outbound | no-op (session already exists) |
| `call.answered` | outbound | status→connected; add opening as nexus turn; `start_playback` idx 0; `start_transcription` (inbound track) |
| `call.answered` | inbound | add greeting nexus turn; `speak` greeting; `start_transcription` (inbound track) |
| `call.transcription` (final only) | both | add "them" turn → goodbye? `speak` closing + `hangup` : outbound→`match_utterance` then `start_playback`/`speak`; inbound→`quick_reply` then `speak` |
| `call.hangup` | both | `end_session(outcome,summary)` + `cleanup_call_audio` |

Tests run via the project's docker exec convention (see CLAUDE.md / memory), e.g.:
`docker exec <nexus-container> python -m pytest tests/test_telephony.py -v`
Locally `python -m pytest …` works too; commands below show the pytest target.

---

### Task 1: Config — swap Twilio vars for Telnyx

**Files:**
- Modify: `app/config.py:62-66`

- [ ] **Step 1: Replace the Twilio config block**

In `app/config.py`, replace lines 62-66 (the `# Twilio telephony` block) with:

```python
# Telnyx telephony (Call Control)
TELNYX_API_KEY       = os.environ.get("TELNYX_API_KEY",       "")
TELNYX_PUBLIC_KEY    = os.environ.get("TELNYX_PUBLIC_KEY",    "")  # webhook Ed25519 signing key
TELNYX_CONNECTION_ID = os.environ.get("TELNYX_CONNECTION_ID", "")  # Call Control Application id
TELNYX_PHONE_NUMBER  = os.environ.get("TELNYX_PHONE_NUMBER",  "")
TELNYX_VOICE         = os.environ.get("TELNYX_VOICE",         "female")  # Telnyx `speak` voice
BASE_URL             = os.environ.get("BASE_URL", "")  # public Cloudflare tunnel URL e.g. https://nexus.example.com
```

- [ ] **Step 2: Verify import still works**

Run: `python -c "import app.config as c; print(c.TELNYX_API_KEY, c.TELNYX_VOICE)"`
Expected: prints two values (empty string then `female`), no error, and no remaining `TWILIO` attribute.

- [ ] **Step 3: Confirm no other module reads TWILIO_* from config**

Run: `grep -rn "config.TWILIO\|cfg.TWILIO\|TWILIO_" app/ | grep -v config.py`
Expected: only hits in `telephony.py`, `router.py`, `tools.py` (handled in later tasks). Note them.

- [ ] **Step 4: Commit**

```bash
git add app/config.py
git commit -m "feat(telephony): swap Twilio config vars for Telnyx Call Control"
```

---

### Task 2: telephony.py — Telnyx Call Control wrapper (TDD)

**Files:**
- Rewrite: `app/services/telephony.py`
- Rewrite: `tests/test_telephony.py`

- [ ] **Step 1: Write the failing tests**

Replace the entire contents of `tests/test_telephony.py` with:

```python
import base64
import pytest
from unittest.mock import MagicMock, patch

import app.config as cfg
from app.services import telephony


def test_encode_decode_client_state_roundtrips():
    token = telephony.encode_client_state("call-abc")
    # client_state is base64 per Telnyx requirement
    assert base64.b64decode(token).decode() == "call-abc"
    assert telephony.decode_client_state(token) == "call-abc"


def test_decode_client_state_handles_empty():
    assert telephony.decode_client_state("") == ""
    assert telephony.decode_client_state(None) == ""


def test_dial_outbound_calls_telnyx(monkeypatch):
    monkeypatch.setattr(cfg, "TELNYX_PHONE_NUMBER", "+15551234567")
    monkeypatch.setattr(cfg, "TELNYX_CONNECTION_ID", "conn-1")
    mock_resp = MagicMock()
    mock_resp.data.call_control_id = "ctrl-xyz"
    mock_client = MagicMock()
    mock_client.calls.dial.return_value = mock_resp

    with patch("app.services.telephony._get_client", return_value=mock_client):
        ccid = telephony.dial_outbound(
            to="+919876543210",
            call_id="call-abc",
            webhook_url="https://example.com/api/calls/webhook",
        )

    assert ccid == "ctrl-xyz"
    kwargs = mock_client.calls.dial.call_args[1]
    assert kwargs["to"] == "+919876543210"
    assert kwargs["from_"] == "+15551234567"
    assert kwargs["connection_id"] == "conn-1"
    assert kwargs["webhook_url"] == "https://example.com/api/calls/webhook"
    assert telephony.decode_client_state(kwargs["client_state"]) == "call-abc"


def test_play_audio_issues_start_playback():
    mock_client = MagicMock()
    with patch("app.services.telephony._get_client", return_value=mock_client):
        telephony.play_audio("ctrl-1", "https://x/audio/c/0", call_id="c")
    kwargs = mock_client.calls.actions.start_playback.call_args[1]
    args = mock_client.calls.actions.start_playback.call_args[0]
    assert args[0] == "ctrl-1"
    assert kwargs["audio_url"] == "https://x/audio/c/0"


def test_speak_text_issues_speak():
    mock_client = MagicMock()
    with patch("app.services.telephony._get_client", return_value=mock_client):
        telephony.speak_text("ctrl-1", "Hello there", language="en", call_id="c")
    args = mock_client.calls.actions.speak.call_args[0]
    kwargs = mock_client.calls.actions.speak.call_args[1]
    assert args[0] == "ctrl-1"
    assert kwargs["payload"] == "Hello there"
    assert kwargs["language"] == "en"


def test_answer_and_hangup_and_transcription():
    mock_client = MagicMock()
    with patch("app.services.telephony._get_client", return_value=mock_client):
        telephony.answer_call("ctrl-1", call_id="c")
        telephony.start_transcription("ctrl-1", language="en")
        telephony.hangup_call("ctrl-1")
    assert mock_client.calls.actions.answer.call_args[0][0] == "ctrl-1"
    assert mock_client.calls.actions.start_transcription.call_args[0][0] == "ctrl-1"
    assert mock_client.calls.actions.hangup.call_args[0][0] == "ctrl-1"


def test_verify_webhook_returns_event(monkeypatch):
    monkeypatch.setattr(cfg, "TELNYX_PUBLIC_KEY", "pub-key")
    mock_event = MagicMock()
    mock_client = MagicMock()
    mock_client.webhooks.unwrap.return_value = mock_event
    with patch("app.services.telephony._get_client", return_value=mock_client):
        ev = telephony.verify_webhook('{"x":1}', {"telnyx-signature-ed25519": "s"})
    assert ev is mock_event
    kwargs = mock_client.webhooks.unwrap.call_args[1]
    assert kwargs["key"] == "pub-key"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_telephony.py -v`
Expected: FAIL — `AttributeError`/`ImportError` (functions `encode_client_state`, `dial_outbound`, etc. not yet defined in new form).

- [ ] **Step 3: Rewrite telephony.py**

Replace the entire contents of `app/services/telephony.py` with:

```python
"""Telnyx Call Control wrapper — outbound dialer, call-control commands, webhook verify."""
import base64
import logging
from typing import Optional

from telnyx import Telnyx

from app import config

logger = logging.getLogger(__name__)

_TRANSCRIPTION_TRACKS = "inbound"  # transcribe the remote party, not our own TTS


def _get_client() -> Telnyx:
    if not config.TELNYX_API_KEY:
        raise RuntimeError("TELNYX_API_KEY not configured")
    return Telnyx(api_key=config.TELNYX_API_KEY, public_key=config.TELNYX_PUBLIC_KEY or None)


def encode_client_state(call_id: str) -> str:
    """Telnyx requires client_state to be base64-encoded."""
    return base64.b64encode((call_id or "").encode()).decode()


def decode_client_state(token: Optional[str]) -> str:
    if not token:
        return ""
    try:
        return base64.b64decode(token).decode()
    except Exception:
        return ""


def dial_outbound(to: str, call_id: str, webhook_url: str) -> str:
    """Dial a number via Telnyx Call Control. Returns the call_control_id."""
    if not config.TELNYX_PHONE_NUMBER:
        raise RuntimeError("TELNYX_PHONE_NUMBER not configured")
    if not config.TELNYX_CONNECTION_ID:
        raise RuntimeError("TELNYX_CONNECTION_ID not configured")
    client = _get_client()
    resp = client.calls.dial(
        connection_id=config.TELNYX_CONNECTION_ID,
        to=to,
        from_=config.TELNYX_PHONE_NUMBER,
        webhook_url=webhook_url,
        client_state=encode_client_state(call_id),
    )
    ccid = resp.data.call_control_id
    logger.info("Dialed %s → call_control_id %s", to, ccid)
    return ccid


def answer_call(call_control_id: str, call_id: str = "") -> None:
    _get_client().calls.actions.answer(
        call_control_id, client_state=encode_client_state(call_id)
    )


def play_audio(call_control_id: str, audio_url: str, call_id: str = "") -> None:
    """Play a pre-rendered WAV (Telnyx fetches audio_url)."""
    _get_client().calls.actions.start_playback(
        call_control_id, audio_url=audio_url, client_state=encode_client_state(call_id)
    )


def speak_text(call_control_id: str, text: str, language: str = "en",
               call_id: str = "") -> None:
    """Speak dynamic text via Telnyx TTS."""
    _get_client().calls.actions.speak(
        call_control_id,
        payload=text,
        voice=config.TELNYX_VOICE,
        language=language,
        client_state=encode_client_state(call_id),
    )


def start_transcription(call_control_id: str, language: str = "en") -> None:
    """Begin streaming STT on the remote party's audio (yields call.transcription events)."""
    _get_client().calls.actions.start_transcription(
        call_control_id,
        language=language,
        transcription_tracks=_TRANSCRIPTION_TRACKS,
    )


def hangup_call(call_control_id: str) -> None:
    _get_client().calls.actions.hangup(call_control_id)


def verify_webhook(payload: str, headers: dict):
    """Verify the Telnyx Ed25519 signature and return the parsed event.

    Raises if the signature is invalid. `payload` is the raw request body (str);
    `headers` must include telnyx-signature-ed25519 and telnyx-timestamp.
    """
    client = _get_client()
    return client.webhooks.unwrap(payload, headers=headers, key=config.TELNYX_PUBLIC_KEY)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_telephony.py -v`
Expected: PASS (all 7 tests).

- [ ] **Step 5: Commit**

```bash
git add app/services/telephony.py tests/test_telephony.py
git commit -m "feat(telephony): rewrite wrapper for Telnyx Call Control"
```

---

### Task 3: call_store.py — rename SID field, add ccid↔call_id binding (TDD)

**Files:**
- Modify: `app/services/call_store.py:44` and add functions near the in-memory store
- Test: `tests/test_call_store_binding.py` (Create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_call_store_binding.py`:

```python
from app.services import call_store


def test_bind_and_resolve_call_control_id():
    call_store.create_session("cid-1", "outbound", "+1", "goal", "en", "v")
    call_store.bind_call_control_id("ctrl-1", "cid-1")
    assert call_store.resolve_call_id("ctrl-1") == "cid-1"


def test_resolve_unknown_returns_none():
    assert call_store.resolve_call_id("nope") is None


def test_session_has_call_control_id_field():
    sess = call_store.create_session("cid-2", "outbound", "+1", "goal", "en", "v")
    assert sess.telnyx_call_control_id is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_call_store_binding.py -v`
Expected: FAIL — `AttributeError: module 'app.services.call_store' has no attribute 'bind_call_control_id'` and no `telnyx_call_control_id` field.

- [ ] **Step 3: Implement the changes**

In `app/services/call_store.py`, change line 44 from:

```python
    twilio_sid: Optional[str] = None
```

to:

```python
    telnyx_call_control_id: Optional[str] = None
```

Then, immediately after the `_active: dict[str, "CallSession"] = {}` line (line 13), add:

```python
_ccid_to_call_id: dict[str, str] = {}
```

And after the `get_session` function (after line 99), add:

```python
def bind_call_control_id(call_control_id: str, call_id: str) -> None:
    """Map a Telnyx call_control_id to our internal call_id."""
    _ccid_to_call_id[call_control_id] = call_id


def resolve_call_id(call_control_id: str) -> Optional[str]:
    return _ccid_to_call_id.get(call_control_id)
```

Finally, in `end_session` (line 108), after `sess = _active.pop(call_id, None)` and the `if not sess: return`, drop any reverse mapping for this call:

```python
    for ccid, cid in list(_ccid_to_call_id.items()):
        if cid == call_id:
            _ccid_to_call_id.pop(ccid, None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_call_store_binding.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add app/services/call_store.py tests/test_call_store_binding.py
git commit -m "feat(telephony): track Telnyx call_control_id and ccid->call_id binding"
```

---

### Task 4: tools.py — run_outbound_call via Telnyx (TDD)

**Files:**
- Modify: `app/agents/tools.py:343-373`
- Modify: `tests/test_call_tools.py` (mock return keys)

- [ ] **Step 1: Update the tests**

In `tests/test_call_tools.py`, replace every `"twilio_sid": "CA..."` in mock return values with `"call_control_id": "ctrl-1"`. Specifically:
- `test_make_call_tool_returns_call_id`: `mock_run.return_value = {"call_id": "abc-123", "status": "dialing", "call_control_id": "ctrl-1"}`
- `test_handle_make_call_tags_fires_and_strips`: `fake_run` returns `{"call_id": "abc-123", "status": "dialing", "call_control_id": "ctrl-1"}`

Then add a new test asserting the not-configured guard uses Telnyx:

```python
@pytest.mark.asyncio
async def test_run_outbound_call_requires_telnyx_key(monkeypatch):
    import app.config as cfg
    from app.agents import tools
    monkeypatch.setattr(cfg, "TELNYX_API_KEY", "")
    res = await tools.run_outbound_call(number="+1", goal="hi", language="en")
    assert "error" in res
    assert "TELNYX_API_KEY" in res["error"]
```

- [ ] **Step 2: Run tests to verify the new one fails**

Run: `python -m pytest tests/test_call_tools.py -v`
Expected: `test_run_outbound_call_requires_telnyx_key` FAILS (current guard checks `TWILIO_ACCOUNT_SID`).

- [ ] **Step 3: Update run_outbound_call**

In `app/agents/tools.py`, in `run_outbound_call` (lines 343-373):

Replace the import + guard:

```python
    from app.agents.call_prep import generate_script, prerender_audio
    from app.services.telephony import dial_outbound

    if not cfg.TWILIO_ACCOUNT_SID:
        return {"error": "Twilio not configured — set TWILIO_ACCOUNT_SID in .env"}
```

with:

```python
    from app.agents.call_prep import generate_script, prerender_audio
    from app.services.telephony import dial_outbound

    if not cfg.TELNYX_API_KEY:
        return {"error": "Telnyx not configured — set TELNYX_API_KEY in .env"}
```

Replace the dial block (lines 369-373):

```python
    webhook_url = f"{cfg.BASE_URL}/api/calls/gather?call_id={call_id}&turn=0"
    twilio_sid = dial_outbound(to=number, call_id=call_id, webhook_url=webhook_url)
    sess.twilio_sid = twilio_sid

    return {"call_id": call_id, "status": "dialing", "twilio_sid": twilio_sid}
```

with:

```python
    webhook_url = f"{cfg.BASE_URL}/api/calls/webhook"
    call_control_id = dial_outbound(to=number, call_id=call_id, webhook_url=webhook_url)
    sess.telnyx_call_control_id = call_control_id
    call_store.bind_call_control_id(call_control_id, call_id)

    return {"call_id": call_id, "status": "dialing", "call_control_id": call_control_id}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_call_tools.py -v`
Expected: PASS (all tests including the new guard test).

- [ ] **Step 5: Commit**

```bash
git add app/agents/tools.py tests/test_call_tools.py
git commit -m "feat(telephony): dial outbound calls via Telnyx in run_outbound_call"
```

---

### Task 5: router.py — single event-driven webhook (TDD)

**Files:**
- Modify: `app/api/router.py:23-27` (imports), `568-742` (replace webhooks)
- Rewrite: `tests/test_call_api_outbound.py`, `tests/test_call_api_inbound.py`

- [ ] **Step 1: Write the failing tests (outbound)**

Replace the entire contents of `tests/test_call_api_outbound.py` with:

```python
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def _event(event_type, payload):
    return {"data": {"event_type": event_type, "payload": payload}}


def test_outbound_call_returns_call_id(client):
    with patch("app.agents.tools.run_outbound_call", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"call_id": "test-call-1", "status": "dialing", "call_control_id": "ctrl-1"}
        resp = client.post("/api/calls/outbound", json={
            "number": "+919876543210",
            "goal": "Book a table for 2 at 7pm",
            "language": "en",
        })
    assert resp.status_code == 200
    assert resp.json()["call_id"] == "test-call-1"
    assert resp.json()["status"] == "dialing"


def test_audio_endpoint_serves_wav(client):
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


def test_webhook_answered_plays_opening(client):
    from app.services import call_store, telephony
    from app.services.call_store import ScriptEntry
    sess = call_store.create_session("wh-out", "outbound", "+1234", "goal", "en", "en-US-GuyNeural")
    sess.script = [ScriptEntry(idx=0, question="", answer="Hello!", audio_path="/tmp/x/0.wav", used=False)]
    call_store.bind_call_control_id("ctrl-out", "wh-out")

    ev = MagicMock()
    ev.data.event_type = "call.answered"
    ev.data.payload.call_control_id = "ctrl-out"
    ev.data.payload.direction = "outgoing"
    ev.data.payload.client_state = telephony.encode_client_state("wh-out")

    with patch("app.api.router.telephony.verify_webhook", return_value=ev), \
         patch("app.api.router.telephony.play_audio") as mock_play, \
         patch("app.api.router.telephony.start_transcription") as mock_tr:
        resp = client.post("/api/calls/webhook",
                           data=json.dumps(_event("call.answered", {})),
                           headers={"telnyx-signature-ed25519": "s", "telnyx-timestamp": "1"})
    assert resp.status_code == 200
    assert mock_play.called
    assert mock_tr.called


def test_webhook_hangup_ends_session(client):
    from app.services import call_store, telephony
    call_store.create_session("wh-end", "outbound", "+1", "goal", "en", "v")
    call_store.bind_call_control_id("ctrl-end", "wh-end")
    ev = MagicMock()
    ev.data.event_type = "call.hangup"
    ev.data.payload.call_control_id = "ctrl-end"
    ev.data.payload.client_state = telephony.encode_client_state("wh-end")

    with patch("app.api.router.telephony.verify_webhook", return_value=ev), \
         patch("app.api.router.call_store.end_session") as mock_end, \
         patch("app.api.router.cleanup_call_audio") as mock_cleanup:
        resp = client.post("/api/calls/webhook",
                           data=json.dumps(_event("call.hangup", {})),
                           headers={"telnyx-signature-ed25519": "s", "telnyx-timestamp": "1"})
    assert resp.status_code == 200
    assert mock_end.called
```

- [ ] **Step 2: Write the failing tests (inbound)**

Replace the entire contents of `tests/test_call_api_inbound.py` with:

```python
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def _post(client, ev):
    return client.post("/api/calls/webhook",
                       data=json.dumps({"data": {}}),
                       headers={"telnyx-signature-ed25519": "s", "telnyx-timestamp": "1"})


def test_inbound_initiated_answers_call(client):
    from app.services import telephony
    ev = MagicMock()
    ev.data.event_type = "call.initiated"
    ev.data.payload.call_control_id = "ctrl-in"
    ev.data.payload.direction = "incoming"
    ev.data.payload.from_ = "+919876543210"
    ev.data.payload.client_state = ""

    with patch("app.api.router.telephony.verify_webhook", return_value=ev), \
         patch("app.api.router.telephony.answer_call") as mock_answer:
        resp = _post(client, ev)
    assert resp.status_code == 200
    assert mock_answer.called
    # session created keyed by call_control_id
    from app.services import call_store
    assert call_store.get_session("ctrl-in") is not None


def test_inbound_answered_speaks_greeting(client):
    from app.services import call_store, telephony
    call_store.create_session("ctrl-in2", "inbound", "+1", "inbound call", "en", "v")
    call_store.bind_call_control_id("ctrl-in2", "ctrl-in2")
    ev = MagicMock()
    ev.data.event_type = "call.answered"
    ev.data.payload.call_control_id = "ctrl-in2"
    ev.data.payload.direction = "incoming"
    ev.data.payload.client_state = telephony.encode_client_state("ctrl-in2")

    with patch("app.api.router.telephony.verify_webhook", return_value=ev), \
         patch("app.api.router.telephony.speak_text") as mock_speak, \
         patch("app.api.router.telephony.start_transcription"):
        resp = _post(client, ev)
    assert resp.status_code == 200
    assert mock_speak.called
    assert "NEXUS" in mock_speak.call_args[0][1] or "NEXUS" in str(mock_speak.call_args)


def test_transcription_drives_reply(client):
    from app.services import call_store, telephony
    call_store.create_session("ctrl-in3", "inbound", "+1", "inbound call", "en", "v")
    call_store.bind_call_control_id("ctrl-in3", "ctrl-in3")
    ev = MagicMock()
    ev.data.event_type = "call.transcription"
    ev.data.payload.call_control_id = "ctrl-in3"
    ev.data.payload.direction = "incoming"
    ev.data.payload.client_state = telephony.encode_client_state("ctrl-in3")
    ev.data.payload.transcription_data.transcript = "What is my project status?"
    ev.data.payload.transcription_data.is_final = True

    with patch("app.api.router.telephony.verify_webhook", return_value=ev), \
         patch("app.api.router._inbound_agent_reply", new_callable=AsyncMock) as mock_reply, \
         patch("app.api.router.telephony.speak_text") as mock_speak:
        mock_reply.return_value = "I can help with that."
        resp = _post(client, ev)
    assert resp.status_code == 200
    assert mock_speak.called
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_call_api_outbound.py tests/test_call_api_inbound.py -v`
Expected: FAIL — `/api/calls/webhook` route does not exist (404) and `app.api.router.telephony` not imported as a module alias.

- [ ] **Step 4: Update router imports**

In `app/api/router.py`, replace lines 23-27:

```python
from app.services.telephony import (
    build_play_and_gather, build_say_and_gather, build_hangup, validate_twilio_request
)
from app.services import call_store
from app.agents.call_prep import match_utterance, cleanup_call_audio, quick_reply, _AUDIO_DIR
```

with:

```python
from app.services import telephony
from app.services import call_store
from app.agents.call_prep import match_utterance, cleanup_call_audio, quick_reply, _AUDIO_DIR
```

- [ ] **Step 5: Replace the webhook block**

In `app/api/router.py`, delete everything from the `# ── Outbound gather webhook` comment (line 578) through the end of `api_calls_inbound_respond` (line 742) — i.e. the `api_calls_gather`, `_inbound_agent_reply`, `api_calls_inbound`, and `api_calls_inbound_respond` functions — but **keep** `_inbound_agent_reply`. Re-add `_inbound_agent_reply` and the new single webhook. Replace that whole span with:

```python
# ── Live-call helpers ──────────────────────────────────────────────────────────

_GOODBYE_WORDS = {"bye", "goodbye", "thank you", "that's all", "no thanks", "thanks bye"}


async def _inbound_agent_reply(call_id: str, speech: str) -> str:
    """Generate a live inbound reply via the Gemini-flash fast path (quick_reply)."""
    sess = call_store.get_session(call_id)
    goal       = sess.goal if sess else "inbound call"
    language   = sess.language if sess else "en"
    transcript = sess.transcript if sess else []
    return await quick_reply(goal, transcript, language)


def _audio_url(call_id: str, idx: int) -> str:
    return f"{config.BASE_URL}/api/calls/audio/{call_id}/{idx}"


# ── Telnyx Call Control webhook — single event dispatcher ───────────────────────

@router.post("/api/calls/webhook")
async def api_calls_webhook(request: Request, background_tasks: BackgroundTasks):
    body = (await request.body()).decode()

    if config.TELNYX_PUBLIC_KEY:
        try:
            event = telephony.verify_webhook(body, dict(request.headers))
        except Exception as exc:
            logger.warning("Telnyx webhook verification failed: %s", exc)
            return Response("Forbidden", status_code=403)
    else:
        event = telephony.verify_webhook(body, dict(request.headers))

    data       = event.data
    etype      = data.event_type
    payload    = data.payload
    ccid       = payload.call_control_id
    state_id   = telephony.decode_client_state(getattr(payload, "client_state", ""))
    direction  = getattr(payload, "direction", "")
    is_inbound = direction in ("incoming", "inbound")

    # Resolve our internal call_id: client_state → ccid map → (inbound) ccid itself
    call_id = state_id or call_store.resolve_call_id(ccid) or (ccid if is_inbound else "")

    if etype == "call.initiated":
        if is_inbound:
            caller = getattr(payload, "from_", "") or "unknown"
            call_store.create_session(
                call_id=ccid, direction="inbound", number=caller,
                goal="inbound call", language="en", speaker=config.BARK_SPEAKER,
            )
            call_store.bind_call_control_id(ccid, ccid)
            telephony.answer_call(ccid, call_id=ccid)
        return Response(status_code=200)

    if etype == "call.answered":
        sess = call_store.get_session(call_id)
        if sess and sess.direction == "outbound" and sess.script:
            entry = sess.script[0]
            entry.used = True
            sess.status = "connected"
            call_store.add_turn(call_id, "nexus", entry.answer)
            telephony.play_audio(ccid, _audio_url(call_id, 0), call_id=call_id)
        elif sess:  # inbound
            greeting = "Hi, this is NEXUS, your AI assistant. How can I help you today?"
            call_store.add_turn(call_id, "nexus", greeting)
            telephony.speak_text(ccid, greeting, language=sess.language, call_id=call_id)
        telephony.start_transcription(ccid, language=(sess.language if sess else "en"))
        return Response(status_code=200)

    if etype == "call.transcription":
        td = getattr(payload, "transcription_data", None)
        if not td or not getattr(td, "is_final", False):
            return Response(status_code=200)
        speech = (getattr(td, "transcript", "") or "").strip()
        sess = call_store.get_session(call_id)
        if not speech or not sess:
            return Response(status_code=200)
        call_store.add_turn(call_id, "them", speech)

        if any(w in speech.lower() for w in _GOODBYE_WORDS):
            if sess.direction == "outbound":
                closing = next((e for e in sess.script if e.idx == len(sess.script) - 1), None)
                closing_text = closing.answer if closing else "Thank you. Goodbye!"
            else:
                closing_text = "Thank you for calling. Have a great day! Goodbye."
            call_store.add_turn(call_id, "nexus", closing_text)
            telephony.speak_text(ccid, closing_text, language=sess.language, call_id=call_id)
            telephony.hangup_call(ccid)
            background_tasks.add_task(
                call_store.end_session, call_id, "success",
                f"Call completed. Last exchange: {speech[:80]}")
            background_tasks.add_task(cleanup_call_audio, call_id)
            return Response(status_code=200)

        if sess.direction == "outbound":
            matched = match_utterance(speech, sess.script)
            if matched and matched.audio_path and Path(matched.audio_path).exists():
                matched.used = True
                call_store.add_turn(call_id, "nexus", matched.answer)
                telephony.play_audio(ccid, _audio_url(call_id, matched.idx), call_id=call_id)
                return Response(status_code=200)

        reply = await _inbound_agent_reply(call_id, speech)
        call_store.add_turn(call_id, "nexus", reply)
        telephony.speak_text(ccid, reply, language=sess.language, call_id=call_id)
        return Response(status_code=200)

    if etype == "call.hangup":
        if call_id and call_store.get_session(call_id):
            background_tasks.add_task(
                call_store.end_session, call_id, "success", "Call ended.")
            background_tasks.add_task(cleanup_call_audio, call_id)
        return Response(status_code=200)

    return Response(status_code=200)
```

Note: the `api_call_audio` endpoint (lines 570-575) is unchanged and stays above this block.

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_call_api_outbound.py tests/test_call_api_inbound.py -v`
Expected: PASS (all tests).

- [ ] **Step 7: Commit**

```bash
git add app/api/router.py tests/test_call_api_outbound.py tests/test_call_api_inbound.py
git commit -m "feat(telephony): replace TwiML webhooks with Telnyx Call Control event dispatcher"
```

---

### Task 6: Persona text + dependency + deployment config

**Files:**
- Modify: `app/agents/definitions.py:22,135` (and any other "Twilio" mention)
- Modify: `requirements.txt:18`
- Modify: `docker-compose.yml:32-34`
- Modify: `.env`, `.env.example`

- [ ] **Step 1: Update persona text**

Run: `grep -rn "Twilio" app/agents/definitions.py`
Replace each occurrence of "Twilio" with "Telnyx" (line 22: "via Twilio" → "via Telnyx"; line 135: "NEXUS Twilio number" → "NEXUS Telnyx number").

- [ ] **Step 2: Swap the SDK dependency**

In `requirements.txt`, change line 18 from `twilio>=9.0.0` to `telnyx>=4.0.0`.

- [ ] **Step 3: Update docker-compose env**

In `docker-compose.yml`, replace lines 32-34:

```yaml
      - TWILIO_ACCOUNT_SID=${TWILIO_ACCOUNT_SID:-}
      - TWILIO_AUTH_TOKEN=${TWILIO_AUTH_TOKEN:-}
      - TWILIO_PHONE_NUMBER=${TWILIO_PHONE_NUMBER:-}
```

with:

```yaml
      - TELNYX_API_KEY=${TELNYX_API_KEY:-}
      - TELNYX_PUBLIC_KEY=${TELNYX_PUBLIC_KEY:-}
      - TELNYX_CONNECTION_ID=${TELNYX_CONNECTION_ID:-}
      - TELNYX_PHONE_NUMBER=${TELNYX_PHONE_NUMBER:-}
      - TELNYX_VOICE=${TELNYX_VOICE:-female}
```

- [ ] **Step 4: Update .env (remove live Twilio creds, add Telnyx placeholders)**

In `.env`, replace the Twilio block (the 5 lines starting `# Twilio telephony` through `BASE_URL=...`, but keep `BARK_SPEAKER` and `BASE_URL`) with:

```
# Telnyx telephony (Call Control)
TELNYX_API_KEY=
TELNYX_PUBLIC_KEY=
TELNYX_CONNECTION_ID=
TELNYX_PHONE_NUMBER=
TELNYX_VOICE=female
BARK_SPEAKER=en-US-GuyNeural
BASE_URL=https://botsubaru.saurav-info.xyz
```

(This deletes the live Twilio Account SID/Auth Token/number that were committed in `.env`.)

- [ ] **Step 5: Update .env.example**

Append to `.env.example`:

```
# Telnyx telephony (Call Control)
TELNYX_API_KEY=
TELNYX_PUBLIC_KEY=
TELNYX_CONNECTION_ID=
TELNYX_PHONE_NUMBER=
TELNYX_VOICE=female
BASE_URL=
```

- [ ] **Step 6: Verify no Twilio references remain**

Run: `grep -rni "twilio" app/ tests/ requirements.txt docker-compose.yml .env .env.example`
Expected: no output (zero matches).

- [ ] **Step 7: Commit**

```bash
git add app/agents/definitions.py requirements.txt docker-compose.yml .env .env.example
git commit -m "chore(telephony): swap Twilio deps/config/personas for Telnyx"
```

---

### Task 7: Full verification

- [ ] **Step 1: Install the new dependency**

Run: `pip install 'telnyx>=4.0.0'` (or rebuild the container image so `requirements.txt` is applied).
Expected: `telnyx` installs; `python -c "from telnyx import Telnyx"` succeeds.

- [ ] **Step 2: Run the full call test suite**

Run: `python -m pytest tests/test_telephony.py tests/test_call_store_binding.py tests/test_call_tools.py tests/test_call_api_outbound.py tests/test_call_api_inbound.py -v`
Expected: PASS (all tests).

- [ ] **Step 3: Run the entire test suite for regressions**

Run: `python -m pytest -q`
Expected: no new failures versus the pre-migration baseline.

- [ ] **Step 4: Import smoke test**

Run: `python -c "import app.main"`
Expected: no ImportError (confirms router/telephony/tools wiring is consistent).

- [ ] **Step 5: Final commit (if any cleanup was needed)**

```bash
git add -A
git commit -m "test(telephony): verify Telnyx migration end-to-end"
```

---

## Post-migration manual steps (user, outside this plan)

1. Create a Telnyx **Call Control Application**; set its webhook URL to `${BASE_URL}/api/calls/webhook`. Put its id in `TELNYX_CONNECTION_ID`.
2. Buy/assign a Telnyx number → `TELNYX_PHONE_NUMBER`; attach it to the Call Control Application for inbound.
3. Copy the API key → `TELNYX_API_KEY` and the public key → `TELNYX_PUBLIC_KEY`.
4. Redeploy (rebuild container so `telnyx` is installed) and verify with a live test call.
5. **Rotate the old Twilio Auth Token** — it was previously committed to `.env`/git history; decommission the Twilio number/account.
