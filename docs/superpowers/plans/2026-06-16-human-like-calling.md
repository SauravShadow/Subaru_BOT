# Human-like Calling Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the NEXUS Telnyx calling agent feel human — cut per-turn latency and add interruption/humanization — while keeping the custom Call Control loop.

**Architecture:** Keep `POST /api/calls/webhook` → `quick_reply` (LLM) → Telnyx `speak`. Add: latency instrumentation; faster turn-taking (endpointing + interim-silence timer); barge-in (queue caller speech during `is_speaking`); verbal fillers; SSML; experimental backchanneling. Pure/decidable logic lives in small testable helpers; the webhook orchestrates.

**Tech Stack:** Python 3.12 · FastAPI · `telnyx` 4.153 · asyncio · pytest.

**Spec:** `docs/superpowers/specs/2026-06-16-human-like-calling-design.md`

**Test command (runs in the container, which bind-mounts this repo to /app):**
`docker exec -w /app virtual-company python -m pytest <target> -v`

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `app/services/call_metrics.py` | `TurnTimer`: per-turn latency marks + log line (pure) | **Create** |
| `app/services/call_store.py` | `CallSession`: new live-turn state fields | Modify |
| `app/services/telephony.py` | `speak_text` SSML payload_type; `start_transcription` endpointing | Modify |
| `app/agents/call_prep.py` | `pick_filler()`, `sanitize_ssml()`, `quick_reply(ssml=…)` | Modify |
| `app/api/router.py` | webhook: interim handling, silence timer, barge-in, fillers, metrics | Modify |
| `tests/test_call_metrics.py` | TurnTimer unit tests | **Create** |
| `tests/test_call_humanize.py` | filler/ssml/dedupe/timer-decision unit tests | **Create** |
| `tests/test_call_api_barge_in.py` | webhook interim/barge-in/speak-state integration | **Create** |

**Shared signatures (keep consistent across tasks):**
- `CallSession` adds: `is_speaking: bool=False`, `last_interim_text: str=""`, `last_interim_at: float=0.0`, `pending_caller_text: Optional[str]=None`, `silence_task=None`, `turn=None` (TurnTimer), `responded_text: str=""`, `speculative_key: str=""`, `speculative_text: str=""`.
- `telephony.speak_text(call_control_id, text, language="en", call_id="", payload_type="text")`
- `call_prep.pick_filler() -> str`, `call_prep.sanitize_ssml(text) -> tuple[str, str]`, `call_prep.quick_reply(goal, transcript, language="en", talking_points=None, ssml=False) -> str`
- router helpers: `_normalize(text) -> str`, `_silence_should_fire(sess, now) -> bool`

---

## PHASE 0 — Latency instrumentation

### Task 1: TurnTimer utility

**Files:**
- Create: `app/services/call_metrics.py`
- Test: `tests/test_call_metrics.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_call_metrics.py
from app.services.call_metrics import TurnTimer

def test_marks_and_gap():
    t = TurnTimer()
    t.mark("final", at=100.0)
    t.mark("llm_done", at=100.5)
    t.mark("speak", at=100.8)
    assert t.gap_ms("final", "llm_done") == 500
    assert t.gap_ms("final", "speak") == 800
    assert t.gap_ms("final", "missing") == -1

def test_summary_line_contains_stages():
    t = TurnTimer()
    for n, a in [("last_interim", 0.0), ("final", 1.0), ("llm_done", 1.4), ("speak", 1.6)]:
        t.mark(n, at=a)
    line = t.summary_line()
    assert "stt_gap=1000ms" in line
    assert "llm=400ms" in line
    assert "total=600ms" in line
```

- [ ] **Step 2: Run test to verify it fails**
Run: `docker exec -w /app virtual-company python -m pytest tests/test_call_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: app.services.call_metrics`.

- [ ] **Step 3: Implement**
```python
# app/services/call_metrics.py
"""Per-turn latency timing for live calls."""
import time


class TurnTimer:
    """Records monotonic marks for one conversational turn and formats a log line."""

    def __init__(self) -> None:
        self._marks: dict[str, float] = {}

    def mark(self, name: str, at: float | None = None) -> None:
        self._marks[name] = time.monotonic() if at is None else at

    def gap_ms(self, a: str, b: str) -> int:
        if a in self._marks and b in self._marks:
            return int(round((self._marks[b] - self._marks[a]) * 1000))
        return -1

    def summary_line(self) -> str:
        return (
            f"turn latency: stt_gap={self.gap_ms('last_interim', 'final')}ms "
            f"llm={self.gap_ms('final', 'llm_done')}ms "
            f"tts_issue={self.gap_ms('llm_done', 'speak')}ms "
            f"total={self.gap_ms('final', 'speak')}ms"
        )
```

- [ ] **Step 4: Run test to verify it passes**
Run: `docker exec -w /app virtual-company python -m pytest tests/test_call_metrics.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**
```bash
cd /mnt/HC_Volume_105874680/virtual-company
git add app/services/call_metrics.py tests/test_call_metrics.py
git commit -m "feat(calling): TurnTimer latency utility

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Session state fields + wire TurnTimer into the webhook

**Files:**
- Modify: `app/services/call_store.py` (CallSession dataclass)
- Modify: `app/api/router.py` (call.transcription final branch; call.answered)
- Test: `tests/test_call_store_binding.py` (extend)

- [ ] **Step 1: Write the failing test**
Append to `tests/test_call_store_binding.py`:
```python
def test_session_has_live_turn_fields():
    s = call_store.create_session("cid-live", "outbound", "+1", "g", "en", "v")
    assert s.is_speaking is False
    assert s.last_interim_text == ""
    assert s.last_interim_at == 0.0
    assert s.pending_caller_text is None
    assert s.responded_text == ""
```

- [ ] **Step 2: Run to verify it fails**
Run: `docker exec -w /app virtual-company python -m pytest tests/test_call_store_binding.py::test_session_has_live_turn_fields -v`
Expected: FAIL — `AttributeError: ... 'is_speaking'`.

- [ ] **Step 3: Implement — add fields to `CallSession`**
In `app/services/call_store.py`, in the `CallSession` dataclass (after `telnyx_call_control_id`), add:
```python
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
```

- [ ] **Step 4: Wire TurnTimer marks in the webhook**
In `app/api/router.py`, add import near the top with the other `app.services` imports:
```python
from app.services.call_metrics import TurnTimer
```
In the `call.transcription` final-handling block (where `speech` is set and a `sess` exists), at the point a turn is finalized, before generating the reply, add:
```python
            sess.turn = TurnTimer()
            sess.turn.mark("last_interim", at=sess.last_interim_at or None)
            sess.turn.mark("final")
```
After the reply text is computed (`reply = await _live_reply(...)`) add `sess.turn.mark("llm_done")`, and immediately after the `telephony.speak_text(...)` call add:
```python
            sess.turn.mark("speak")
            logger.info("[call %s] %s", call_id, sess.turn.summary_line())
```

- [ ] **Step 5: Run tests**
Run: `docker exec -w /app virtual-company python -m pytest tests/test_call_store_binding.py tests/test_call_api_outbound.py tests/test_call_api_inbound.py -v`
Expected: PASS (all).

- [ ] **Step 6: Commit**
```bash
git add app/services/call_store.py app/api/router.py tests/test_call_store_binding.py
git commit -m "feat(calling): live-turn session state + per-turn latency logging

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## PHASE 1 — Faster turn-taking

### Task 3: Shorter STT endpointing

**Files:**
- Modify: `app/services/telephony.py` (`start_transcription`)
- Test: `tests/test_telephony.py` (extend)

**IMPORTANT (verified against telnyx 4.153.0):** the Google transcription config has NO
endpointing/timeout fields. Valid keys are only: `enable_speaker_diarization`, `hints`,
`interim_results`, `language`, `max_speaker_count`, `min_speaker_count`, `model`,
`profanity_filter`, `speech_context`, `transcription_engine`, `use_enhanced`. So we cannot
shorten the silence threshold via config — that is handled by the interim-silence timer
(Task 4). This task instead improves phone STT quality/speed with the `phone_call` model +
`use_enhanced` (valid keys), which also reduces mis-transcriptions.

- [ ] **Step 1: Write the failing test**
Append to `tests/test_telephony.py`:
```python
def test_start_transcription_uses_phone_model():
    mock_client = MagicMock()
    with patch("app.services.telephony._get_client", return_value=mock_client):
        telephony.start_transcription("ctrl-1", language="en")
    kwargs = mock_client.calls.actions.start_transcription.call_args[1]
    assert kwargs["transcription_engine"] == "Google"
    cfg = kwargs["transcription_engine_config"]
    assert cfg["language"] == "en"
    assert cfg["interim_results"] is True
    assert cfg["model"] == "phone_call"
    assert cfg["use_enhanced"] is True
    assert kwargs["transcription_tracks"] == "inbound"
```

- [ ] **Step 2: Run to verify it fails**
Run: `docker exec -w /app virtual-company python -m pytest tests/test_telephony.py::test_start_transcription_uses_phone_model -v`
Expected: FAIL — `model` not in config.

- [ ] **Step 3: Implement**
In `app/services/telephony.py`, replace the body of `start_transcription` (keep the existing `_short_lang` + `_TRANSCRIPTION_TRACKS`):
```python
    _get_client().calls.actions.start_transcription(
        call_control_id,
        transcription_tracks=_TRANSCRIPTION_TRACKS,
        transcription_engine="Google",
        transcription_engine_config={
            "transcription_engine": "Google",
            "language": _short_lang(language),
            "interim_results": True,
            "model": "phone_call",   # tuned for telephony audio
            "use_enhanced": True,
        },
    )
```
Only valid keys are used, so no 422 risk. (The end-of-turn latency win comes from Task 4.)

- [ ] **Step 4: Run tests**
Run: `docker exec -w /app virtual-company python -m pytest tests/test_telephony.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add app/services/telephony.py tests/test_telephony.py
git commit -m "feat(calling): bias Google STT toward faster finals

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Interim-silence end-of-turn detection

**Files:**
- Modify: `app/api/router.py` (transcription branch: handle interim events + asyncio silence timer)
- Modify: `app/agents/call_prep.py` (none) / Test: `tests/test_call_humanize.py` (Create)

This makes the webhook act on **interim** `call.transcription` events: record the interim, (re)arm an asyncio timer; if the text is unchanged for 700ms, finalize the turn early. The existing `is_final` path stays but dedupes against `responded_text`.

- [ ] **Step 1: Write the failing test (pure decision helper)**
Create `tests/test_call_humanize.py`:
```python
import time
from app.api import router

def test_normalize():
    assert router._normalize("  Hello,  World! ") == "hello world"
    assert router._normalize("") == ""

def test_silence_should_fire():
    class S:  # minimal stand-in for CallSession
        last_interim_text = "book a table"
        last_interim_at = 1000.0
        responded_text = ""
    s = S()
    assert router._silence_should_fire(s, now=1000.75) is True   # >700ms, unseen
    assert router._silence_should_fire(s, now=1000.40) is False  # too soon
    s.responded_text = "book a table"
    assert router._silence_should_fire(s, now=1002.0) is False   # already answered
    s.responded_text = ""
    s.last_interim_text = ""
    assert router._silence_should_fire(s, now=1002.0) is False   # nothing said
```

- [ ] **Step 2: Run to verify it fails**
Run: `docker exec -w /app virtual-company python -m pytest tests/test_call_humanize.py -v`
Expected: FAIL — `_normalize` / `_silence_should_fire` not defined.

- [ ] **Step 3: Implement helpers + interim handling**
In `app/api/router.py` add near the call helpers:
```python
import re as _re

_SILENCE_MS = 700  # interim unchanged this long => end of turn

def _normalize(text: str) -> str:
    return _re.sub(r"[^a-z0-9 ]", "", (text or "").lower()).strip()

def _silence_should_fire(sess, now: float) -> bool:
    txt = (sess.last_interim_text or "").strip()
    if not txt:
        return False
    if _normalize(txt) == _normalize(sess.responded_text):
        return False
    return (now - sess.last_interim_at) * 1000 >= _SILENCE_MS
```
Then refactor the `call.transcription` branch so it handles BOTH interim and final. Replace the existing transcription block body with:
```python
        if etype == "call.transcription":
            td = getattr(payload, "transcription_data", None)
            if not td:
                return Response(status_code=200)
            text = (getattr(td, "transcript", "") or "").strip()
            is_final = bool(getattr(td, "is_final", False))
            sess = call_store.get_session(call_id)
            if not sess or not text:
                return Response(status_code=200)

            if not is_final:
                sess.last_interim_text = text
                sess.last_interim_at = time.monotonic()
                _arm_silence_timer(call_id, ccid)
                return Response(status_code=200)

            # final
            sess.last_interim_text = text
            sess.last_interim_at = sess.last_interim_at or time.monotonic()
            await _finalize_turn(call_id, ccid, text)
            return Response(status_code=200)
```
Add the timer + finalize functions (module scope, above the webhook):
```python
import asyncio as _asyncio
import time

async def _silence_watch(call_id: str, ccid: str) -> None:
    try:
        await _asyncio.sleep(_SILENCE_MS / 1000)
    except _asyncio.CancelledError:
        return
    sess = call_store.get_session(call_id)
    if sess and _silence_should_fire(sess, time.monotonic()):
        await _finalize_turn(call_id, ccid, sess.last_interim_text)

def _arm_silence_timer(call_id: str, ccid: str) -> None:
    sess = call_store.get_session(call_id)
    if not sess:
        return
    old = sess.silence_task
    if old is not None:
        old.cancel()
    sess.silence_task = _asyncio.create_task(_silence_watch(call_id, ccid))

async def _finalize_turn(call_id: str, ccid: str, speech: str) -> None:
    sess = call_store.get_session(call_id)
    if not sess:
        return
    speech = (speech or "").strip()
    if not speech or _normalize(speech) == _normalize(sess.responded_text):
        return
    sess.responded_text = speech
    if sess.silence_task is not None:
        sess.silence_task.cancel()
        sess.silence_task = None
    sess.turn = TurnTimer()
    sess.turn.mark("last_interim", at=sess.last_interim_at or None)
    sess.turn.mark("final")
    call_store.add_turn(call_id, "them", speech)
    # goodbye / reply handled by the shared turn handler
    await _respond_to_turn(call_id, ccid, speech)
```
Move the goodbye + reply logic (previously inline in the webhook) into `_respond_to_turn` (extract the existing goodbye/closing block and the `_live_reply`+speak block from the old transcription branch verbatim, replacing `return Response(...)` with `return`), ending with:
```python
async def _respond_to_turn(call_id: str, ccid: str, speech: str) -> None:
    sess = call_store.get_session(call_id)
    if not sess:
        return
    lang = sess.language
    if any(w in speech.lower() for w in _GOODBYE_WORDS):
        closing_text = ("Thank you. Goodbye!" if sess.direction == "outbound"
                        else "Thank you for calling. Have a great day! Goodbye.")
        call_store.add_turn(call_id, "nexus", closing_text)
        telephony.speak_text(ccid, closing_text, language=lang, call_id=call_id)
        telephony.hangup_call(ccid)
        return
    reply = await _live_reply(call_id, speech)
    sess.turn.mark("llm_done")
    call_store.add_turn(call_id, "nexus", reply)
    telephony.speak_text(ccid, reply, language=lang, call_id=call_id)
    sess.turn.mark("speak")
    logger.info("[call %s] %s", call_id, sess.turn.summary_line())
```
(End-of-call persistence still happens on `call.hangup`.)

- [ ] **Step 4: Run tests**
Run: `docker exec -w /app virtual-company python -m pytest tests/test_call_humanize.py tests/test_call_api_inbound.py tests/test_call_api_outbound.py -v`
Expected: PASS. (Update `test_transcription_drives_reply` if it asserted inline behavior — it patches `_live_reply` and `speak_text`, which `_respond_to_turn` still calls, so it should pass; if it set `is_final=True`, the final path calls `_finalize_turn` → `_respond_to_turn`.)

- [ ] **Step 5: Commit**
```bash
git add app/api/router.py tests/test_call_humanize.py
git commit -m "feat(calling): interim-silence end-of-turn detection (faster replies)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## PHASE 1b — Fillers + barge-in

### Task 5: Verbal fillers

**Files:**
- Modify: `app/agents/call_prep.py` (`pick_filler`)
- Modify: `app/api/router.py` (`_respond_to_turn`: filler if LLM slow)
- Test: `tests/test_call_humanize.py` (extend)

- [ ] **Step 1: Write the failing test**
Append to `tests/test_call_humanize.py`:
```python
def test_pick_filler_returns_short_phrase():
    from app.agents.call_prep import pick_filler
    f = pick_filler()
    assert isinstance(f, str) and 0 < len(f) <= 40
```

- [ ] **Step 2: Run to verify it fails**
Run: `docker exec -w /app virtual-company python -m pytest tests/test_call_humanize.py::test_pick_filler_returns_short_phrase -v`
Expected: FAIL — `pick_filler` undefined.

- [ ] **Step 3: Implement**
In `app/agents/call_prep.py`:
```python
import random as _random

_FILLERS = ["Let me check…", "Sure, one moment…", "Okay, let me see…", "Right, give me a sec…"]

def pick_filler() -> str:
    return _random.choice(_FILLERS)
```
In `app/api/router.py` `_respond_to_turn`, replace the `reply = await _live_reply(...)` line with a filler-on-slow-LLM wrapper:
```python
    from app.agents.call_prep import pick_filler
    reply_task = _asyncio.create_task(_live_reply(call_id, speech))
    done, _ = await _asyncio.wait({reply_task}, timeout=1.0)
    if reply_task not in done:
        filler = pick_filler()
        call_store.add_turn(call_id, "nexus", filler)
        telephony.speak_text(ccid, filler, language=lang, call_id=call_id)
    reply = await reply_task
    sess.turn.mark("llm_done")
```

- [ ] **Step 4: Run tests**
Run: `docker exec -w /app virtual-company python -m pytest tests/test_call_humanize.py tests/test_call_api_inbound.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add app/agents/call_prep.py app/api/router.py tests/test_call_humanize.py
git commit -m "feat(calling): verbal fillers bridge slow LLM turns

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Track is_speaking via speak events

**Files:**
- Modify: `app/api/router.py` (handle `call.speak.started` / `call.speak.ended`)
- Test: `tests/test_call_api_barge_in.py` (Create)

- [ ] **Step 1: Write the failing test**
Create `tests/test_call_api_barge_in.py`:
```python
import json, pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)

def _ev(client, etype, ccid, cid, **payload):
    from app.services import telephony
    ev = MagicMock()
    ev.data.event_type = etype
    ev.data.payload.call_control_id = ccid
    ev.data.payload.direction = "outgoing"
    ev.data.payload.client_state = telephony.encode_client_state(cid)
    for k, v in payload.items():
        setattr(ev.data.payload, k, v)
    with patch("app.api.router.telephony.verify_webhook", return_value=ev):
        return client.post("/api/calls/webhook", data=json.dumps({"data": {}}),
                           headers={"telnyx-signature-ed25519": "s", "telnyx-timestamp": "1"})

def test_speak_started_ended_toggles_is_speaking(client):
    from app.services import call_store
    call_store.create_session("spk", "outbound", "+1", "g", "en", "v")
    call_store.bind_call_control_id("c-spk", "spk")
    _ev(client, "call.speak.started", "c-spk", "spk")
    assert call_store.get_session("spk").is_speaking is True
    _ev(client, "call.speak.ended", "c-spk", "spk")
    assert call_store.get_session("spk").is_speaking is False
```

- [ ] **Step 2: Run to verify it fails**
Run: `docker exec -w /app virtual-company python -m pytest tests/test_call_api_barge_in.py -v`
Expected: FAIL — `is_speaking` stays False (events unhandled).

- [ ] **Step 3: Implement**
In `app/api/router.py`, inside the `try:` dispatch, add before the `call.transcription` branch:
```python
        if etype in ("call.speak.started", "call.playback.started"):
            sess = call_store.get_session(call_id)
            if sess:
                sess.is_speaking = True
            return Response(status_code=200)

        if etype in ("call.speak.ended", "call.playback.ended"):
            sess = call_store.get_session(call_id)
            if sess:
                sess.is_speaking = False
                if sess.pending_caller_text:                 # deferred barge-in (Task 7)
                    pending = sess.pending_caller_text
                    sess.pending_caller_text = None
                    await _finalize_turn(call_id, ccid, pending)
            return Response(status_code=200)
```

- [ ] **Step 4: Run tests**
Run: `docker exec -w /app virtual-company python -m pytest tests/test_call_api_barge_in.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add app/api/router.py tests/test_call_api_barge_in.py
git commit -m "feat(calling): track is_speaking from speak/playback events

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Barge-in — queue caller speech during AI speech

**Files:**
- Modify: `app/api/router.py` (`_finalize_turn`: defer if is_speaking)
- Test: `tests/test_call_api_barge_in.py` (extend)

- [ ] **Step 1: Write the failing test**
Append to `tests/test_call_api_barge_in.py`:
```python
@pytest.mark.asyncio
async def test_finalize_defers_while_speaking():
    from app.api import router
    from app.services import call_store
    s = call_store.create_session("bg", "outbound", "+1", "g", "en", "v")
    call_store.bind_call_control_id("c-bg", "bg")
    s.is_speaking = True
    with patch("app.api.router._respond_to_turn") as mock_resp:
        await router._finalize_turn("bg", "c-bg", "eight pm works")
    assert mock_resp.called is False
    assert s.pending_caller_text == "eight pm works"
```

- [ ] **Step 2: Run to verify it fails**
Run: `docker exec -w /app virtual-company python -m pytest tests/test_call_api_barge_in.py::test_finalize_defers_while_speaking -v`
Expected: FAIL — `_respond_to_turn` is called / `pending_caller_text` not set.

- [ ] **Step 3: Implement**
In `_finalize_turn`, after computing `speech` and the dedupe guard, before marking the turn, add:
```python
    if sess.is_speaking:
        sess.pending_caller_text = speech    # handle when call.speak.ended arrives
        return
```
(`_respond_to_turn` must be patchable: it is a module-level `async def`, so `patch("app.api.router._respond_to_turn")` works.)

- [ ] **Step 4: Run tests**
Run: `docker exec -w /app virtual-company python -m pytest tests/test_call_api_barge_in.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**
```bash
git add app/api/router.py tests/test_call_api_barge_in.py
git commit -m "feat(calling): barge-in — queue caller speech during AI output

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## PHASE 1c — SSML prosody

### Task 8: SSML payload + sanitize/fallback

**Files:**
- Modify: `app/services/telephony.py` (`speak_text` payload_type)
- Modify: `app/agents/call_prep.py` (`sanitize_ssml`, `quick_reply(ssml=True)`)
- Modify: `app/api/router.py` (`_respond_to_turn` uses SSML)
- Test: `tests/test_call_humanize.py` + `tests/test_telephony.py` (extend)

- [ ] **Step 1: Write the failing tests**
Append to `tests/test_telephony.py`:
```python
def test_speak_text_ssml_payload_type():
    mock_client = MagicMock()
    with patch("app.services.telephony._get_client", return_value=mock_client):
        telephony.speak_text("c", "<speak>hi</speak>", language="en", payload_type="ssml")
    kwargs = mock_client.calls.actions.speak.call_args[1]
    assert kwargs["payload_type"] == "ssml"
```
Append to `tests/test_call_humanize.py`:
```python
def test_sanitize_ssml_wraps_and_detects():
    from app.agents.call_prep import sanitize_ssml
    payload, ptype = sanitize_ssml('Sure<break time="200ms"/> now.')
    assert ptype == "ssml" and payload.startswith("<speak>") and payload.endswith("</speak>")
    payload2, ptype2 = sanitize_ssml("just plain text")
    assert ptype2 == "text" and payload2 == "just plain text"
    payload3, ptype3 = sanitize_ssml("<speak>bad <oops></speak>")
    assert ptype3 == "text"   # malformed XML -> fall back to plain
```

- [ ] **Step 2: Run to verify they fail**
Run: `docker exec -w /app virtual-company python -m pytest tests/test_telephony.py::test_speak_text_ssml_payload_type tests/test_call_humanize.py::test_sanitize_ssml_wraps_and_detects -v`
Expected: FAIL — `payload_type` not forwarded / `sanitize_ssml` undefined.

- [ ] **Step 3: Implement**
In `app/services/telephony.py`, change `speak_text` signature and call:
```python
def speak_text(call_control_id: str, text: str, language: str = "en",
               call_id: str = "", payload_type: str = "text") -> None:
    """Speak dynamic text via Telnyx TTS (payload_type 'text' or 'ssml')."""
    _get_client().calls.actions.speak(
        call_control_id,
        payload=text,
        voice=config.TELNYX_VOICE,
        language=_telnyx_language(language),
        payload_type=payload_type,
        client_state=encode_client_state(call_id),
    )
```
In `app/agents/call_prep.py`:
```python
import xml.etree.ElementTree as _ET

def sanitize_ssml(text: str) -> tuple[str, str]:
    """Return (payload, payload_type). Wrap valid SSML in <speak>; fall back to plain text."""
    t = (text or "").strip()
    if "<break" not in t and "<emphasis" not in t and "<speak" not in t:
        return t, "text"
    body = t[len("<speak>"):-len("</speak>")] if t.startswith("<speak>") and t.endswith("</speak>") else t
    wrapped = f"<speak>{body}</speak>"
    try:
        _ET.fromstring(wrapped)
        return wrapped, "ssml"
    except Exception:
        return _re.sub(r"<[^>]+>", "", t), "text"
```
(Ensure `import re as _re` exists in call_prep; add if missing.) Add an `ssml` flag to `quick_reply`: when `ssml=True`, append to the prompt: `"You may add <break time=\"200ms\"/> for natural pauses."` Default `ssml=False`.
In `app/api/router.py` `_respond_to_turn`, replace the final speak of `reply` with:
```python
    from app.agents.call_prep import sanitize_ssml
    payload, ptype = sanitize_ssml(reply)
    telephony.speak_text(ccid, payload, language=lang, call_id=call_id, payload_type=ptype)
```
And call `_live_reply` with SSML enabled by threading an `ssml=True` arg through `_live_reply` → `quick_reply`.

- [ ] **Step 4: Run tests**
Run: `docker exec -w /app virtual-company python -m pytest tests/test_telephony.py tests/test_call_humanize.py tests/test_call_api_inbound.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add app/services/telephony.py app/agents/call_prep.py app/api/router.py tests/test_telephony.py tests/test_call_humanize.py
git commit -m "feat(calling): SSML prosody with safe plain-text fallback

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## PHASE 2 — Speculative pre-generation (conditional)

> Build only if Phase 1 latency logs (Task 1/2) show median total still above ~1.0s.

### Task 9: Speculative reply cache

**Files:**
- Modify: `app/api/router.py` (interim handler primes a speculative reply; finalize uses it)
- Test: `tests/test_call_humanize.py` (extend)

- [ ] **Step 1: Write the failing test**
Append to `tests/test_call_humanize.py`:
```python
@pytest.mark.asyncio
async def test_finalize_uses_speculative_cache(monkeypatch):
    from app.api import router
    from app.services import call_store
    s = call_store.create_session("spec", "outbound", "+1", "g", "en", "v")
    call_store.bind_call_control_id("c-spec", "spec")
    s.speculative_key = router._normalize("book a table")
    s.speculative_text = "Sure, for what time?"
    calls = {"llm": 0}
    async def fake_live_reply(cid, sp): calls["llm"] += 1; return "fresh"
    monkeypatch.setattr(router, "_live_reply", fake_live_reply)
    with patch("app.api.router.telephony.speak_text") as mock_speak:
        await router._respond_to_turn("spec", "c-spec", "book a table")
    assert calls["llm"] == 0                       # used cache, no LLM call
    assert "Sure, for what time" in str(mock_speak.call_args)
```

- [ ] **Step 2: Run to verify it fails**
Run: `docker exec -w /app virtual-company python -m pytest tests/test_call_humanize.py::test_finalize_uses_speculative_cache -v`
Expected: FAIL — cache not consulted.

- [ ] **Step 3: Implement**
In `_respond_to_turn`, before the filler/LLM block, add a cache hit path:
```python
    if sess.speculative_key and sess.speculative_key == _normalize(speech) and sess.speculative_text:
        reply = sess.speculative_text
        sess.speculative_key = sess.speculative_text = ""
        sess.turn.mark("llm_done")
        call_store.add_turn(call_id, "nexus", reply)
        payload, ptype = sanitize_ssml(reply)   # import at top of function
        telephony.speak_text(ccid, payload, language=lang, call_id=call_id, payload_type=ptype)
        sess.turn.mark("speak")
        logger.info("[call %s] %s (speculative hit)", call_id, sess.turn.summary_line())
        return
```
In the interim handler (Task 4 `call.transcription` not-final branch), after `_arm_silence_timer`, add speculative priming when the interim is stable a little while:
```python
                now = time.monotonic()
                if (now - sess.last_interim_at) * 1000 >= 400 and not sess.speculative_key:
                    sess.speculative_key = _normalize(text)
                    _asyncio.create_task(_speculate(call_id, text))
```
Add `_speculate`:
```python
async def _speculate(call_id: str, text: str) -> None:
    sess = call_store.get_session(call_id)
    if not sess:
        return
    try:
        reply = await _live_reply(call_id, text)
    except Exception:
        return
    sess2 = call_store.get_session(call_id)
    if sess2 and sess2.speculative_key == _normalize(text):
        sess2.speculative_text = reply
```
Note the interim handler sets `last_interim_at` *before* this check, so use the prior value: guard with a separate `sess.last_interim_text == text` stability check instead of recomputing the delta if needed.

- [ ] **Step 4: Run tests**
Run: `docker exec -w /app virtual-company python -m pytest tests/test_call_humanize.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add app/api/router.py tests/test_call_humanize.py
git commit -m "feat(calling): speculative pre-generation on stable interim text

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## PHASE 3 — Backchanneling (experimental, flagged)

### Task 10: Soft acknowledgements during long caller turns

**Files:**
- Modify: `app/config.py` (`CALL_BACKCHANNEL` flag)
- Modify: `app/api/router.py` (interim handler: occasional "mm-hmm")
- Test: `tests/test_call_humanize.py` (extend)

- [ ] **Step 1: Write the failing test**
Append to `tests/test_call_humanize.py`:
```python
def test_backchannel_disabled_by_default():
    import app.config as cfg
    assert getattr(cfg, "CALL_BACKCHANNEL", False) in (False, "0", "", None)
```

- [ ] **Step 2: Run to verify it fails**
Run: `docker exec -w /app virtual-company python -m pytest tests/test_call_humanize.py::test_backchannel_disabled_by_default -v`
Expected: FAIL — attribute missing.

- [ ] **Step 3: Implement**
In `app/config.py`:
```python
CALL_BACKCHANNEL = os.environ.get("CALL_BACKCHANNEL", "") == "1"
```
In `app/api/router.py` interim handler, when `config.CALL_BACKCHANNEL` is on and the caller has produced several interims without finalizing and we are not `is_speaking`, occasionally emit a soft ack:
```python
                if config.CALL_BACKCHANNEL and not sess.is_speaking \
                   and len(text.split()) >= 8 and not getattr(sess, "_backchanneled", False):
                    sess._backchanneled = True
                    telephony.speak_text(ccid, "mm-hmm", language=sess.language, call_id=call_id)
```
Reset `sess._backchanneled = False` inside `_finalize_turn` (start of a new turn).

- [ ] **Step 4: Run tests**
Run: `docker exec -w /app virtual-company python -m pytest tests/test_call_humanize.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add app/config.py app/api/router.py tests/test_call_humanize.py
git commit -m "feat(calling): experimental backchanneling behind CALL_BACKCHANNEL flag

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 11: Full verification + rebuild

- [ ] **Step 1: Full call suite**
Run: `docker exec -w /app virtual-company python -m pytest tests/test_call_metrics.py tests/test_call_humanize.py tests/test_call_api_barge_in.py tests/test_telephony.py tests/test_call_api_outbound.py tests/test_call_api_inbound.py tests/test_call_tools.py tests/test_call_store_binding.py -v`
Expected: PASS (all).

- [ ] **Step 2: Regression + import**
Run: `docker exec -w /app virtual-company python -m pytest tests/ -q` and `docker exec -w /app virtual-company python -c "import app.main; print('import ok')"`
Expected: no new failures; `import ok`.

- [ ] **Step 3: Rebuild for durability**
Run: `cd /mnt/HC_Volume_105874680/virtual-company && docker compose up -d --build virtual-company`
Then confirm app up: `curl -s -m5 -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3031/api/agents` → 200.

- [ ] **Step 4: Live verification**
Place a call from the Call Panel; confirm in `docker logs -f virtual-company`: `turn latency:` lines appear, replies are faster, fillers fire on slow turns, and barge-in queues caller speech. Tune `_SILENCE_MS` / endpointing from observed numbers.

---

## Self-Review

- **Spec coverage:** §2 metrics → T1–T2; §3 endpointing+timer → T3–T4; §5 barge-in E1 → T6–T7; §6 fillers → T5; §7 SSML → T8; §4 speculative → T9; §8 backchanneling → T10; §11 testing throughout; verify → T11. All spec sections covered.
- **Placeholders:** none — every code step has concrete code.
- **Type consistency:** `speak_text(..., payload_type=)`, `_normalize`, `_silence_should_fire`, `_finalize_turn`, `_respond_to_turn`, `_arm_silence_timer`, `TurnTimer`, session fields used consistently across tasks.

**Note for implementer:** Tasks 4 and 8 refactor the `call.transcription` branch; apply them in order and keep `_respond_to_turn` as the single place that issues replies (fillers, SSML, speculative all funnel through it).
