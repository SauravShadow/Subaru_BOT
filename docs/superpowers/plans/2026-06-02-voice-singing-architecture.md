# Voice, Singing & Extensible Output Architecture — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace browser SpeechSynthesis with Bark (self-hosted), add real singing, and refactor executor.py into a clean extensible TagRegistry pipeline.

**Architecture:** Bark runs as a dedicated Docker sidecar (`bark-svc`) with `/speak`, `/sing`, `/filler`, `/health` endpoints. A new `app/output/` layer (TagRegistry + OutputPipeline) replaces all scattered regex in executor.py — every LLM backend now calls `await pipeline.process(full_resp, agent_id, send)` instead of copy-pasted tag logic. The browser keeps `SpeechSynthesis` as a fallback when Bark is unavailable.

**Tech Stack:** Python 3.12, FastAPI, suno-bark (PyPI), httpx, pytest, asyncio; vanilla JS (no build step); Docker Compose.

---

## File Map

**Created:**
- `bark-svc/Dockerfile`
- `bark-svc/requirements.txt`
- `bark-svc/main.py`
- `bark-svc/filler_pool.py`
- `app/services/bark_client.py`
- `app/output/__init__.py`
- `app/output/pipeline.py`
- `app/output/registry.py`
- `app/output/handlers/__init__.py`
- `app/output/handlers/speak.py`
- `app/output/handlers/sing.py`
- `app/output/handlers/image.py`
- `app/output/handlers/email.py`
- `tests/test_pipeline.py`
- `tests/test_bark_client.py`
- `tests/test_handlers.py`

**Modified:**
- `app/agents/executor.py` — remove all tag regex, call `pipeline.process()` at end of each backend
- `app/agents/tools.py` — remove `generate_image` function
- `app/agents/definitions.py` — add VOICE & SINGING directives to all personas
- `app/api/router.py` — add `GET /api/filler` endpoint
- `app/api/websocket.py` — remove `parse_emails` call (moves to email handler)
- `app/services/delegation.py` — remove EMAIL_USER from `clean_response`
- `app/config.py` — add `BARK_SVC_URL`
- `app/static/app-v5.js` — AudioQueue, filler fetch, `case "audio"`, singing indicator, fallback
- `app/static/index.html` — add `#singing-indicator` element
- `docker-compose.yml` — bark-svc service, volume, depends_on, env var

---

## Task 1: Bark Sidecar — `/health` + filler pool

**Files:**
- Create: `bark-svc/requirements.txt`
- Create: `bark-svc/Dockerfile`
- Create: `bark-svc/filler_pool.py`
- Create: `bark-svc/main.py`

- [ ] **Step 1: Create `bark-svc/requirements.txt`**

```
fastapi==0.115.0
uvicorn[standard]==0.30.0
suno-bark==0.0.1
numpy==1.26.4
scipy==1.13.0
```

- [ ] **Step 2: Create `bark-svc/Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ffmpeg git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 9001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9001"]
```

- [ ] **Step 3: Create `bark-svc/filler_pool.py`**

```python
"""Pre-generates filler audio clips on startup. All clips served from memory."""
import random
import base64
import logging
import io
import numpy as np
from scipy.io.wavfile import write as wav_write

logger = logging.getLogger(__name__)

FILLER_POOL: dict[str, list[bytes]] = {
    "thinking": [],
    "health":   [],
    "facts":    [],
    "creative": [],
}

FILLER_TEXTS = {
    "thinking": [
        "Hmm, let me think on that for a second...",
        "Okay, processing... give me just a moment.",
        "Right, let me work through this...",
    ],
    "health": [
        "Quick tip while I think — drink some water, you probably haven't today.",
        "Fun fact: a 5-minute walk every hour improves focus by 20 percent.",
        "While I prep this — your eyes need a break from the screen every 20 minutes.",
    ],
    "facts": [
        "Did you know honey never expires? Archaeologists found 3000-year-old honey still good.",
        "Interesting thing while I work — the universe is 13.8 billion years old.",
        "While I'm thinking — octopuses have three hearts and blue blood.",
    ],
    "creative": [
        "Setting the stage, give me just a second...",
        "Warming up the vocals, one moment...",
        "Getting into character...",
    ],
}

_SAMPLE_RATE = 24000


def _audio_array_to_wav_bytes(audio_array: np.ndarray) -> bytes:
    """Convert float32 numpy array from Bark to WAV bytes."""
    pcm = (audio_array * 32767).astype(np.int16)
    buf = io.BytesIO()
    wav_write(buf, _SAMPLE_RATE, pcm)
    return buf.getvalue()


def generate_clip(text: str) -> bytes:
    """Generate a single Bark audio clip. Returns WAV bytes."""
    from bark import generate_audio, SAMPLE_RATE
    audio = generate_audio(text, history_prompt="v2/en_speaker_2")
    return _audio_array_to_wav_bytes(audio)


def build_pool() -> None:
    """Called once on startup. Generates all filler clips."""
    logger.info("Building filler pool (%d clips)...",
                sum(len(v) for v in FILLER_TEXTS.values()))
    for category, texts in FILLER_TEXTS.items():
        for text in texts:
            try:
                wav = generate_clip(text)
                FILLER_POOL[category].append(wav)
                logger.info("  ✓ %s: %s", category, text[:40])
            except Exception as exc:
                logger.error("  ✗ filler failed (%s): %s", text[:40], exc)
    logger.info("Filler pool ready.")


def pick(context: str = "") -> bytes | None:
    """Return a random pre-built filler clip based on context keywords."""
    ctx = context.lower()
    if any(w in ctx for w in ["sing", "song", "music", "rap", "hum", "perform"]):
        pool = FILLER_POOL["creative"]
    elif any(w in ctx for w in ["health", "food", "sleep", "tired", "eat"]):
        pool = FILLER_POOL["health"]
    elif any(w in ctx for w in ["code", "build", "fix", "debug", "error"]):
        pool = FILLER_POOL["thinking"]
    else:
        pool = FILLER_POOL["thinking"] + FILLER_POOL["facts"]
    return random.choice(pool) if pool else None


def wav_to_b64(wav_bytes: bytes) -> str:
    return base64.b64encode(wav_bytes).decode("ascii")
```

- [ ] **Step 4: Create `bark-svc/main.py` — health endpoint only first**

```python
"""Bark TTS sidecar — /speak /sing /filler /health"""
import base64
import io
import logging
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel
from scipy.io.wavfile import write as wav_write

import filler_pool

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

_model_ready = False
_SAMPLE_RATE = 24000

EMOTION_PROFILES = {
    "excited":   {"speaker": "v2/en_speaker_6", "temperature": 0.9},
    "calm":      {"speaker": "v2/en_speaker_2", "temperature": 0.6},
    "sad":       {"speaker": "v2/en_speaker_3", "temperature": 0.5},
    "whisper":   {"speaker": "v2/en_speaker_0", "temperature": 0.4},
    "energetic": {"speaker": "v2/en_speaker_9", "temperature": 1.0},
}
DEFAULT_EMOTION = EMOTION_PROFILES["calm"]

STYLE_SPEAKER_MAP = {
    "hip hop": "v2/en_speaker_6",
    "rap":     "v2/en_speaker_6",
    "calm":    "v2/en_speaker_2",
    "soft":    "v2/en_speaker_0",
    "slow":    "v2/en_speaker_3",
    "fast":    "v2/en_speaker_9",
    "energetic": "v2/en_speaker_9",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model_ready
    logger.info("Loading Bark model...")
    from bark import preload_models
    preload_models()
    logger.info("Bark model loaded. Building filler pool...")
    filler_pool.build_pool()
    _model_ready = True
    logger.info("bark-svc ready.")
    yield


app = FastAPI(lifespan=lifespan)


def _array_to_b64(audio: np.ndarray) -> str:
    pcm = (audio * 32767).astype(np.int16)
    buf = io.BytesIO()
    wav_write(buf, _SAMPLE_RATE, pcm)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _style_to_speaker(style: str) -> str:
    style_lower = style.lower()
    for keyword, speaker in STYLE_SPEAKER_MAP.items():
        if keyword in style_lower:
            return speaker
    return "v2/en_speaker_6"


@app.get("/health")
def health():
    return {"ready": _model_ready}


class SpeakRequest(BaseModel):
    text: str
    emotion: str = "calm"
    agent_id: str = ""


@app.post("/speak")
async def speak(req: SpeakRequest):
    from bark import generate_audio
    profile  = EMOTION_PROFILES.get(req.emotion, DEFAULT_EMOTION)
    audio    = generate_audio(req.text, history_prompt=profile["speaker"])
    return {"audio": _array_to_b64(audio)}


class SingRequest(BaseModel):
    lyrics: str
    style:  str = "expressive"


@app.post("/sing")
async def sing(req: SingRequest):
    from bark import generate_audio
    speaker  = _style_to_speaker(req.style)
    bark_text = f"♪ {req.lyrics} ♪"
    audio     = generate_audio(bark_text, history_prompt=speaker)
    return {"audio": _array_to_b64(audio)}


@app.get("/filler")
def filler(context: str = ""):
    wav = filler_pool.pick(context)
    if wav is None:
        return {"audio": None}
    return {"audio": filler_pool.wav_to_b64(wav)}
```

- [ ] **Step 5: Build the sidecar image to verify it compiles (no tests yet — model download would be too slow)**

```bash
cd /home/subaru/projects/virtual-company
docker build -t bark-svc-test ./bark-svc 2>&1 | tail -5
```
Expected: `Successfully built <id>` (will take 2-3 min on first run — downloads PyTorch)

- [ ] **Step 6: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add bark-svc/
git commit -m "feat(bark-svc): add Bark TTS sidecar with speak/sing/filler/health"
```

---

## Task 2: `bark_client.py` — HTTP client with fallback

**Files:**
- Create: `app/services/bark_client.py`
- Create: `tests/test_bark_client.py`
- Modify: `app/config.py:57` — add `BARK_SVC_URL`

- [ ] **Step 1: Add `BARK_SVC_URL` to `app/config.py`**

At the end of `app/config.py`, add:

```python
# Bark TTS sidecar
BARK_SVC_URL = os.environ.get("BARK_SVC_URL", "http://bark-svc:9001")
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_bark_client.py`:

```python
"""Tests for bark_client — verifies timeout/None fallback without hitting real sidecar."""
import pytest
import httpx
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_speak_returns_base64_on_success():
    from app.services import bark_client
    mock_resp = AsyncMock()
    mock_resp.json.return_value = {"audio": "dGVzdA=="}
    mock_resp.raise_for_status = lambda: None

    with patch("httpx.AsyncClient.post", return_value=mock_resp):
        result = await bark_client.speak("Hello", "calm")
    assert result == "dGVzdA=="


@pytest.mark.asyncio
async def test_speak_returns_none_on_timeout():
    from app.services import bark_client
    with patch("httpx.AsyncClient.post", side_effect=httpx.TimeoutException("timeout")):
        result = await bark_client.speak("Hello", "calm")
    assert result is None


@pytest.mark.asyncio
async def test_sing_returns_base64_on_success():
    from app.services import bark_client
    mock_resp = AsyncMock()
    mock_resp.json.return_value = {"audio": "c2luZw=="}
    mock_resp.raise_for_status = lambda: None

    with patch("httpx.AsyncClient.post", return_value=mock_resp):
        result = await bark_client.sing("La la la", "hip hop")
    assert result == "c2luZw=="


@pytest.mark.asyncio
async def test_sing_returns_none_on_connection_error():
    from app.services import bark_client
    with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("refused")):
        result = await bark_client.sing("La la la", "hip hop")
    assert result is None


@pytest.mark.asyncio
async def test_get_filler_returns_base64():
    from app.services import bark_client
    mock_resp = AsyncMock()
    mock_resp.json.return_value = {"audio": "ZmlsbGVy"}
    mock_resp.raise_for_status = lambda: None

    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        result = await bark_client.get_filler("sing me a song")
    assert result == "ZmlsbGVy"


@pytest.mark.asyncio
async def test_get_filler_returns_none_when_bark_down():
    from app.services import bark_client
    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("refused")):
        result = await bark_client.get_filler("any context")
    assert result is None
```

- [ ] **Step 3: Run to verify it fails**

```bash
cd /home/subaru/projects/virtual-company
docker exec virtual-company python -m pytest tests/test_bark_client.py -v 2>&1 | tail -15
```
Expected: `ModuleNotFoundError: No module named 'app.services.bark_client'`

- [ ] **Step 4: Create `app/services/bark_client.py`**

```python
"""HTTP client for the bark-svc sidecar. Returns None on any failure — callers degrade gracefully."""
import logging
import httpx
from app import config

logger = logging.getLogger(__name__)
_TIMEOUT = 15.0


async def speak(text: str, emotion: str = "calm") -> str | None:
    """POST /speak → base64 WAV string, or None if bark-svc is unavailable."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{config.BARK_SVC_URL}/speak",
                json={"text": text, "emotion": emotion},
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()["audio"]
    except Exception as exc:
        logger.warning("bark_client.speak failed: %s", exc)
        return None


async def sing(lyrics: str, style: str = "expressive") -> str | None:
    """POST /sing → base64 WAV string, or None if bark-svc is unavailable."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{config.BARK_SVC_URL}/sing",
                json={"lyrics": lyrics, "style": style},
                timeout=30.0,
            )
            resp.raise_for_status()
            return resp.json()["audio"]
    except Exception as exc:
        logger.warning("bark_client.sing failed: %s", exc)
        return None


async def get_filler(context: str = "") -> str | None:
    """GET /filler → base64 WAV string, or None if unavailable / pool not ready."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{config.BARK_SVC_URL}/filler",
                params={"context": context},
                timeout=5.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("audio")
    except Exception as exc:
        logger.warning("bark_client.get_filler failed: %s", exc)
        return None
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
docker exec virtual-company python -m pytest tests/test_bark_client.py -v 2>&1 | tail -15
```
Expected: `6 passed`

- [ ] **Step 6: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/services/bark_client.py app/config.py tests/test_bark_client.py
git commit -m "feat: add bark_client HTTP client with timeout/None fallback"
```

---

## Task 3: OutputPipeline core — `pipeline.py` + `registry.py`

**Files:**
- Create: `app/output/__init__.py`
- Create: `app/output/handlers/__init__.py`
- Create: `app/output/registry.py`
- Create: `app/output/pipeline.py`
- Create: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pipeline.py`:

```python
"""Tests for OutputPipeline — verifies tag dispatch and display text stripping."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import re


def _make_handler(tag: str, return_text: str = "", bark_ok: bool = False):
    """Build a minimal mock handler module."""
    h = MagicMock()
    h.TAG = tag
    h.PATTERN = re.compile(rf'\[{tag}:\s*(.*?)\]', re.DOTALL)
    h.handle = AsyncMock(return_value=(return_text, bark_ok))
    return h


@pytest.mark.asyncio
async def test_pipeline_dispatches_speak_tag():
    from app.output import pipeline
    send = AsyncMock()
    speak_handler = _make_handler("SPEAK", "Hello world", bark_ok=True)

    with patch.dict("app.output.registry.REGISTRY", {"SPEAK": speak_handler}, clear=True):
        await pipeline.process("[SPEAK: Hello world | emotion: calm]", "ceo", send)

    speak_handler.handle.assert_called_once()
    args = speak_handler.handle.call_args[0]
    assert "Hello world" in args[0]


@pytest.mark.asyncio
async def test_pipeline_strips_tag_from_display():
    from app.output import pipeline
    send = AsyncMock()
    speak_handler = _make_handler("SPEAK", "cleaned text", bark_ok=True)

    with patch.dict("app.output.registry.REGISTRY", {"SPEAK": speak_handler}, clear=True):
        await pipeline.process("[SPEAK: cleaned text | emotion: calm]", "ceo", send)

    # Should send assistant message with handler's return text, not raw tag
    calls = [c for c in send.call_args_list if c[0][0].get("type") == "assistant"]
    assert any("cleaned text" in str(c) for c in calls)
    assert not any("[SPEAK:" in str(c) for c in calls)


@pytest.mark.asyncio
async def test_pipeline_sets_bark_ok_true_when_audio_sent():
    from app.output import pipeline
    send = AsyncMock()
    speak_handler = _make_handler("SPEAK", "hi", bark_ok=True)

    with patch.dict("app.output.registry.REGISTRY", {"SPEAK": speak_handler}, clear=True):
        await pipeline.process("[SPEAK: hi | emotion: excited]", "ceo", send)

    assistant_calls = [c[0][0] for c in send.call_args_list if c[0][0].get("type") == "assistant"]
    assert any(c.get("bark_ok") is True for c in assistant_calls)


@pytest.mark.asyncio
async def test_pipeline_sets_bark_ok_false_when_no_audio():
    from app.output import pipeline
    send = AsyncMock()
    speak_handler = _make_handler("SPEAK", "hi", bark_ok=False)

    with patch.dict("app.output.registry.REGISTRY", {"SPEAK": speak_handler}, clear=True):
        await pipeline.process("[SPEAK: hi | emotion: calm]", "ceo", send)

    assistant_calls = [c[0][0] for c in send.call_args_list if c[0][0].get("type") == "assistant"]
    assert any(c.get("bark_ok") is False for c in assistant_calls)


@pytest.mark.asyncio
async def test_pipeline_handles_no_tags():
    from app.output import pipeline
    send = AsyncMock()

    with patch.dict("app.output.registry.REGISTRY", {}, clear=True):
        await pipeline.process("Plain text with no tags", "ceo", send)

    assistant_calls = [c[0][0] for c in send.call_args_list if c[0][0].get("type") == "assistant"]
    assert len(assistant_calls) == 1
    assert assistant_calls[0]["message"]["content"][0]["text"] == "Plain text with no tags"


@pytest.mark.asyncio
async def test_pipeline_empty_display_sends_nothing():
    from app.output import pipeline
    send = AsyncMock()
    speak_handler = _make_handler("SPEAK", "", bark_ok=True)  # handler strips everything

    with patch.dict("app.output.registry.REGISTRY", {"SPEAK": speak_handler}, clear=True):
        await pipeline.process("[SPEAK: hello | emotion: calm]", "ceo", send)

    assistant_calls = [c[0][0] for c in send.call_args_list if c[0][0].get("type") == "assistant"]
    # Empty display → no assistant message sent
    assert len(assistant_calls) == 0
```

- [ ] **Step 2: Run to verify they fail**

```bash
docker exec virtual-company python -m pytest tests/test_pipeline.py -v 2>&1 | tail -10
```
Expected: `ModuleNotFoundError: No module named 'app.output'`

- [ ] **Step 3: Create `app/output/__init__.py` and `app/output/handlers/__init__.py`**

```bash
mkdir -p /home/subaru/projects/virtual-company/app/output/handlers
touch /home/subaru/projects/virtual-company/app/output/__init__.py
touch /home/subaru/projects/virtual-company/app/output/handlers/__init__.py
```

- [ ] **Step 4: Create `app/output/registry.py`**

```python
"""TagRegistry — maps tag names to handler modules.
To add a new output capability: create handlers/mytag.py and add one entry here.
"""
# Handlers imported lazily to avoid circular imports at module load time.
# registry.REGISTRY is the single source of truth for all output tags.

def _load_registry() -> dict:
    from app.output.handlers import speak, sing, image, email as email_handler
    return {
        "SPEAK":          speak,
        "SING":           sing,
        "GENERATE_IMAGE": image,
        "EMAIL_USER":     email_handler,
    }


# Populated on first access — avoids import-time circular dependency issues.
_registry: dict | None = None


def get_registry() -> dict:
    global _registry
    if _registry is None:
        _registry = _load_registry()
    return _registry


# Convenience alias used in tests via patch.dict("app.output.registry.REGISTRY", ...)
REGISTRY: dict = {}  # populated by get_registry() on first pipeline.process() call
```

- [ ] **Step 5: Create `app/output/pipeline.py`**

```python
"""OutputPipeline — post-processes every LLM response.

Scans for registered output tags, dispatches each to its handler,
strips tags from the display text, and sends a single assistant message
with bark_ok flag for frontend TTS fallback logic.
"""
import logging
from typing import Callable, Awaitable

from app.output import registry as _reg

logger = logging.getLogger(__name__)

Sender = Callable[[dict], Awaitable[None]]


async def process(text: str, agent_id: str, send: Sender) -> str:
    """
    Process all registered output tags in `text`.

    For each tag found:
      - Calls handler.handle(args, agent_id, send)
      - handler returns (display_text, bark_ok)
      - Replaces the raw tag in display with display_text
      - Tracks whether any handler delivered audio (bark_ok)

    Sends a single {type: "assistant"} message with bark_ok flag.
    Returns the cleaned display text.
    """
    reg = _reg.get_registry()
    # Sync REGISTRY alias used in tests
    _reg.REGISTRY.update(reg)

    display  = text
    bark_ok  = False

    for tag_name, handler in reg.items():
        matches = list(handler.PATTERN.finditer(text))
        for match in matches:
            try:
                result_text, audio_sent = await handler.handle(
                    match.group(1), agent_id, send
                )
                display = handler.PATTERN.sub(result_text, display, count=1)
                if audio_sent:
                    bark_ok = True
            except Exception as exc:
                logger.error("Handler %s failed: %s", tag_name, exc)
                display = handler.PATTERN.sub("", display, count=1)

    display = display.strip()
    if display:
        await send({
            "type":    "assistant",
            "agent":   agent_id,
            "message": {"content": [{"type": "text", "text": display}]},
            "bark_ok": bark_ok,
        })
    return display
```

- [ ] **Step 6: Run tests — they'll still fail (handlers not created yet), that's expected**

```bash
docker exec virtual-company python -m pytest tests/test_pipeline.py -v 2>&1 | tail -10
```
Expected: `ModuleNotFoundError: No module named 'app.output.handlers.speak'`

- [ ] **Step 7: Commit skeleton**

```bash
cd /home/subaru/projects/virtual-company
git add app/output/ tests/test_pipeline.py
git commit -m "feat(output): add OutputPipeline skeleton and TagRegistry"
```

---

## Task 4: `speak.py` and `sing.py` handlers

**Files:**
- Create: `app/output/handlers/speak.py`
- Create: `app/output/handlers/sing.py`
- Create: `tests/test_handlers.py`

- [ ] **Step 1: Write failing handler tests**

Create `tests/test_handlers.py`:

```python
"""Unit tests for speak and sing handlers."""
import pytest
import re
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_speak_handler_sends_audio_when_bark_works():
    from app.output.handlers import speak
    send = AsyncMock()
    with patch("app.services.bark_client.speak", return_value="dGVzdA=="):
        text, bark_ok = await speak.handle("Hello there | emotion: excited", "ceo", send)
    assert bark_ok is True
    send.assert_called_once()
    call_data = send.call_args[0][0]
    assert call_data["type"] == "audio"
    assert call_data["data"] == "dGVzdA=="
    assert call_data["mode"] == "speak"


@pytest.mark.asyncio
async def test_speak_handler_returns_text_and_false_when_bark_down():
    from app.output.handlers import speak
    send = AsyncMock()
    with patch("app.services.bark_client.speak", return_value=None):
        text, bark_ok = await speak.handle("Hello there | emotion: calm", "ceo", send)
    assert bark_ok is False
    assert "Hello there" in text
    send.assert_not_called()


@pytest.mark.asyncio
async def test_speak_handler_defaults_to_calm_when_no_emotion():
    from app.output.handlers import speak
    send = AsyncMock()
    with patch("app.services.bark_client.speak", return_value="abc") as mock_speak:
        await speak.handle("Just text no emotion tag", "ceo", send)
    mock_speak.assert_called_once_with("Just text no emotion tag", "calm")


@pytest.mark.asyncio
async def test_sing_handler_sends_audio_with_sing_mode():
    from app.output.handlers import sing
    send = AsyncMock()
    with patch("app.services.bark_client.sing", return_value="c2luZw=="):
        text, bark_ok = await sing.handle(
            "La la la\nSinging now | style: hip hop, fast", "ceo", send
        )
    assert bark_ok is True
    call_data = send.call_args[0][0]
    assert call_data["type"] == "audio"
    assert call_data["mode"] == "sing"


@pytest.mark.asyncio
async def test_sing_handler_returns_lyrics_as_text_when_bark_down():
    from app.output.handlers import sing
    send = AsyncMock()
    with patch("app.services.bark_client.sing", return_value=None):
        text, bark_ok = await sing.handle("La la la | style: pop", "ceo", send)
    assert bark_ok is False
    assert "La la la" in text
    send.assert_not_called()


def test_speak_pattern_matches_full_tag():
    from app.output.handlers import speak
    sample = "[SPEAK: Hello world | emotion: excited]"
    m = speak.PATTERN.search(sample)
    assert m is not None
    assert "Hello world" in m.group(1)


def test_sing_pattern_matches_multiline():
    from app.output.handlers import sing
    sample = "[SING: Look at the cash\nI'm bubbling | style: hip hop]"
    m = sing.PATTERN.search(sample)
    assert m is not None
    assert "bubbling" in m.group(1)
```

- [ ] **Step 2: Run to verify they fail**

```bash
docker exec virtual-company python -m pytest tests/test_handlers.py -v 2>&1 | tail -10
```
Expected: `ModuleNotFoundError: No module named 'app.output.handlers.speak'`

- [ ] **Step 3: Create `app/output/handlers/speak.py`**

```python
"""SPEAK handler — converts [SPEAK: text | emotion: X] to Bark TTS audio."""
import re
import logging
from typing import Callable, Awaitable

from app.services import bark_client

logger  = logging.getLogger(__name__)
TAG     = "SPEAK"
PATTERN = re.compile(r'\[SPEAK:\s*(.*?)\]', re.DOTALL)

Sender = Callable[[dict], Awaitable[None]]

_VALID_EMOTIONS = {"excited", "calm", "sad", "whisper", "energetic"}


def _parse_args(args: str) -> tuple[str, str]:
    """Split 'text | emotion: X' → (text, emotion). Defaults to calm."""
    if " | emotion:" in args:
        parts   = args.split(" | emotion:", 1)
        text    = parts[0].strip()
        emotion = parts[1].strip().lower()
    elif " | emotion:" in args.lower():
        parts   = args.lower().split(" | emotion:", 1)
        text    = args[:args.lower().index(" | emotion:")].strip()
        emotion = parts[1].strip()
    else:
        text    = args.strip()
        emotion = "calm"
    if emotion not in _VALID_EMOTIONS:
        emotion = "calm"
    return text, emotion


async def handle(args: str, agent_id: str, send: Sender) -> tuple[str, bool]:
    """
    Returns (display_text, bark_ok).
    display_text: the spoken text to show in chat (not the raw tag).
    bark_ok: True if audio was delivered to browser.
    """
    text, emotion = _parse_args(args)
    audio = await bark_client.speak(text, emotion)
    if audio:
        await send({"type": "audio", "mode": "speak", "data": audio})
        return text, True
    # Bark unavailable — return text so frontend uses SpeechSynthesis fallback
    return text, False
```

- [ ] **Step 4: Create `app/output/handlers/sing.py`**

```python
"""SING handler — converts [SING: lyrics | style: X] to Bark singing audio."""
import re
import logging
from typing import Callable, Awaitable

from app.services import bark_client

logger  = logging.getLogger(__name__)
TAG     = "SING"
PATTERN = re.compile(r'\[SING:\s*(.*?)\]', re.DOTALL)

Sender = Callable[[dict], Awaitable[None]]


def _parse_sing_args(args: str) -> tuple[str, str]:
    """Split 'lyrics | style: X' → (lyrics, style). Style defaults to 'expressive'."""
    if " | style:" in args:
        parts  = args.split(" | style:", 1)
        lyrics = parts[0].strip()
        style  = parts[1].strip()
    else:
        lyrics = args.strip()
        style  = "expressive"
    return lyrics, style


async def handle(args: str, agent_id: str, send: Sender) -> tuple[str, bool]:
    """
    Returns (display_text, bark_ok).
    On Bark success: sends audio with mode="sing", returns ("", True).
    On Bark failure: returns (lyrics, False) so lyrics are shown as text.
    """
    lyrics, style = _parse_sing_args(args)
    audio = await bark_client.sing(lyrics, style)
    if audio:
        await send({"type": "audio", "mode": "sing", "data": audio})
        return "", True
    # Bark unavailable — show lyrics as text instead
    return lyrics, False
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
docker exec virtual-company python -m pytest tests/test_handlers.py -v 2>&1 | tail -15
```
Expected: `7 passed`

- [ ] **Step 6: Now run pipeline tests too — should all pass**

```bash
docker exec virtual-company python -m pytest tests/test_pipeline.py tests/test_handlers.py -v 2>&1 | tail -15
```
Expected: `13 passed`

- [ ] **Step 7: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/output/handlers/speak.py app/output/handlers/sing.py tests/test_handlers.py
git commit -m "feat(output): add speak and sing handlers with Bark client integration"
```

---

## Task 5: `image.py` and `email.py` handlers

**Files:**
- Create: `app/output/handlers/image.py`
- Create: `app/output/handlers/email.py`
- Modify: `app/agents/tools.py` — remove `generate_image` function

- [ ] **Step 1: Create `app/output/handlers/image.py`**

Move the existing `generate_image` logic from `app/agents/tools.py` here:

```python
"""IMAGE handler — converts [GENERATE_IMAGE: description] to a generated image."""
import asyncio
import base64
import re
import urllib.parse
import urllib.request
import logging
from typing import Callable, Awaitable

logger  = logging.getLogger(__name__)
TAG     = "GENERATE_IMAGE"
PATTERN = re.compile(r'\[GENERATE_IMAGE:\s*(.*?)\]', re.DOTALL)

Sender = Callable[[dict], Awaitable[None]]


async def _fetch_image(prompt: str) -> dict:
    """Fetch from Pollinations.ai. Returns {ok, data, mime_type, size} or {ok:False, error}."""
    try:
        encoded = urllib.parse.quote(prompt)
        url = (
            f"https://image.pollinations.ai/prompt/{encoded}"
            f"?width=512&height=512&nologo=true"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

        def _do():
            resp = urllib.request.urlopen(req, timeout=45)
            return resp.read(), resp.headers.get("Content-Type", "image/png")

        data, mime = await asyncio.get_event_loop().run_in_executor(None, _do)
        return {"ok": True, "data": base64.b64encode(data).decode("ascii"),
                "mime_type": mime, "size": len(data)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def handle(args: str, agent_id: str, send: Sender) -> tuple[str, bool]:
    """Generate image and send it. Returns ("", False) — images carry no Bark audio."""
    prompt = args.strip()
    await send({"type": "tool_call", "agent": agent_id,
                "tool": "generate_image", "label": "Generating Image",
                "path": prompt[:60]})
    result = await _fetch_image(prompt)
    if result.get("ok"):
        await send({
            "type":  "assistant",
            "agent": agent_id,
            "message": {"content": [{
                "type":       "image",
                "media_type": result["mime_type"],
                "data":       result["data"],
            }]},
        })
        logger.info("Image sent for prompt: %s", prompt[:60])
    else:
        logger.error("Image generation failed: %s", result.get("error"))
    return "", False
```

- [ ] **Step 2: Create `app/output/handlers/email.py`**

```python
"""EMAIL handler — converts [EMAIL_USER: addr | Subject] body to sent email."""
import re
import logging
from typing import Callable, Awaitable

logger  = logging.getLogger(__name__)
TAG     = "EMAIL_USER"
PATTERN = re.compile(r'\[EMAIL_USER:([^\]]+)\]\s*(.*?)(?=\[EMAIL_USER:|\[DELEGATE:|$)',
                     re.DOTALL)

Sender = Callable[[dict], Awaitable[None]]


def _parse_email_args(header: str, body: str) -> tuple[str | None, str, str]:
    """Parse 'addr | Subject' header → (recipient, subject, body)."""
    header = header.strip()
    body   = body.strip()
    if "|" in header:
        parts     = header.split("|", 1)
        recipient = parts[0].strip()
        subject   = parts[1].strip()
    elif "@" in header and "." in header:
        recipient = header
        subject   = "Notification from Shadow Garden"
    else:
        recipient = None   # sends to USER_EMAIL
        subject   = header
    return recipient, subject, body


async def handle(args: str, agent_id: str, send: Sender) -> tuple[str, bool]:
    """Send email and strip tag from display. Returns ("", False) — no audio."""
    from app.services import email as email_svc
    # args here is the header (PATTERN group 1), but the body is group 2.
    # Because PATTERN captures both header and body, args = "header\x00body" split by \x00.
    # We split on the first \x00 inserted by pipeline (see pipeline.py note below).
    # EMAIL_USER is special: its PATTERN captures 2 groups.
    # pipeline.process() passes group(1) + "\x00" + group(2) for 2-group handlers.
    if "\x00" in args:
        header, body = args.split("\x00", 1)
    else:
        header = args
        body   = ""
    recipient, subject, body = _parse_email_args(header, body)
    result = await email_svc.send_mail(f"[Shadow Garden] {subject}", body, to=recipient)
    await send({
        "type": "email_sent", "subject": subject,
        "ok": result.get("ok"), "error": result.get("error", ""),
    })
    return "", False
```

> **Note on EMAIL_USER's 2-group pattern:** `pipeline.py` needs a small update to handle handlers whose PATTERN has 2 capture groups. See Task 6, Step 3 for the pipeline update.

- [ ] **Step 3: Remove `generate_image` from `app/agents/tools.py`**

Open `app/agents/tools.py`, find the `generate_image` function (starts around line 230+) and delete the entire function including its docstring. It is now in `app/output/handlers/image.py`.

Run this to verify it's gone:
```bash
grep -n "def generate_image" /home/subaru/projects/virtual-company/app/agents/tools.py
```
Expected: no output

- [ ] **Step 4: Update `pipeline.py` to handle 2-group patterns (for EMAIL_USER)**

In `app/output/pipeline.py`, replace the inner `for match in matches:` block with:

```python
        for match in matches:
            try:
                # Handlers with 2 capture groups (e.g. EMAIL_USER) get groups joined by \x00
                if match.lastindex and match.lastindex >= 2:
                    handler_args = match.group(1) + "\x00" + (match.group(2) or "")
                else:
                    handler_args = match.group(1)
                result_text, audio_sent = await handler.handle(
                    handler_args, agent_id, send
                )
                display = handler.PATTERN.sub(result_text, display, count=1)
                if audio_sent:
                    bark_ok = True
            except Exception as exc:
                logger.error("Handler %s failed: %s", tag_name, exc)
                display = handler.PATTERN.sub("", display, count=1)
```

- [ ] **Step 5: Run all tests**

```bash
docker exec virtual-company python -m pytest tests/test_pipeline.py tests/test_handlers.py tests/test_bark_client.py -v 2>&1 | tail -20
```
Expected: all pass

- [ ] **Step 6: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/output/handlers/image.py app/output/handlers/email.py \
        app/agents/tools.py app/output/pipeline.py
git commit -m "feat(output): add image and email handlers, remove generate_image from tools.py"
```

---

## Task 6: Refactor `executor.py`

**Files:**
- Modify: `app/agents/executor.py`
- Modify: `app/api/websocket.py` — remove `parse_emails` call
- Modify: `app/services/delegation.py` — remove EMAIL_USER from `clean_response`

- [ ] **Step 1: Remove `generate_image` import from executor.py**

In `app/agents/executor.py`, find the import block at the top:

```python
from app.agents.tools import (
    local_bash, local_read, local_write, local_edit,
    parse_tool_call, summarize_output, generate_image,
)
```

Change to:

```python
from app.agents.tools import (
    local_bash, local_read, local_write, local_edit,
    parse_tool_call, summarize_output,
)
```

Also add the pipeline import near the top of the file (after the existing imports):

```python
from app.output import pipeline
```

- [ ] **Step 2: Replace the Claude agent's final tag-handling block**

In `app/agents/executor.py`, find the block inside `run_claude_agent()` that starts at the successful response path (around line 453). Replace everything from `if full_resp.strip():` down to the end of the image block with:

```python
    try:
        mem_svc.save_memory(agent_id, prompt, mem_type="user_query", importance=0.4)
        if full_resp.strip():
            mem_svc.save_memory(agent_id, full_resp[:500], mem_type="agent_response", importance=0.3)
    except Exception:
        pass

    if full_resp.strip():
        await pipeline.process(full_resp, agent_id, send)

    return full_resp
```

Verify the removed block included:
- `import re as _re`
- `clean_resp = ...`
- `re.sub(r'\[GENERATE_IMAGE:...`
- `re.sub(r'\[DONE:...`
- `await send({"type": "assistant" ...})`
- `img_match = _re.search(r'\[GENERATE_IMAGE:...`
- The entire image generation `if img_match:` block

- [ ] **Step 3: Replace the Gemini agent's final block**

In `run_gemini_agent()`, find the block that builds `display_text` and handles the image (around line 537). Replace from `display_text = _re.sub(...)` to `return text` with:

```python
        try:
            mem_svc.save_memory(agent_id, prompt, mem_type="user_query", importance=0.4)
            mem_svc.save_memory(agent_id, text[:500], mem_type="agent_response", importance=0.3)
        except Exception:
            pass

        await pipeline.process(text, agent_id, send)
        return text
```

- [ ] **Step 4: Replace the tgpt agent's final block**

In `run_tgpt_agent()`, find the final block that builds `clean_resp` and sends it (around line 353). Replace from `if full_resp.strip():` down to the final `return full_resp` with:

```python
    try:
        mem_svc.save_memory(agent_id, prompt, mem_type="user_query", importance=0.4)
        if full_resp.strip():
            mem_svc.save_memory(agent_id, full_resp[:500], mem_type="agent_response", importance=0.3)
    except Exception:
        pass

    if full_resp.strip():
        await pipeline.process(full_resp, agent_id, send)

    return full_resp
```

- [ ] **Step 5: Update `app/api/websocket.py` — remove `parse_emails` call**

In `websocket.py`, find the CEO handler block (around line 186):

```python
        # Send any emails
        for target, subj, body in deleg_svc.parse_emails(full_resp):
            result = await email_svc.send_mail(f"[Shadow Garden] {subj}", body, to=target)
            await session.send({
                "type": "email_sent", "subject": subj,
                "ok": result["ok"], "error": result.get("error", ""),
            })
```

Delete these lines entirely. The email handler in the pipeline now handles this.

Also update `state.record` call to only strip delegate tags (not email):

```python
    state.record(agent_id, "assistant", deleg_svc.clean_delegations(full_resp))
```

- [ ] **Step 6: Update `app/services/delegation.py`**

Rename `clean_response` to `clean_delegations` and only strip DELEGATE tags (EMAIL_USER is now handled by the pipeline):

```python
"""Delegation service — parses CEO output and spawns background worker tasks."""
import re

_DELEGATE_RE = re.compile(
    r'\[DELEGATE:(\w+)\]\s*(.*?)(?=\[DELEGATE:|$)', re.DOTALL
)
_EMAIL_RE = re.compile(
    r'\[EMAIL_USER:([^\]]+)\]\s*(.*?)(?=\[DELEGATE:|\[EMAIL_USER:|$)', re.DOTALL
)


def parse_delegations(text: str) -> list[tuple[str, str]]:
    from app.agents.definitions import all_agents
    agents = all_agents()
    return [
        (m.group(1).strip(), m.group(2).strip())
        for m in _DELEGATE_RE.finditer(text)
        if m.group(1).strip() in agents
    ]


def parse_emails(text: str) -> list[tuple]:
    """Kept for scheduler.py compatibility. Pipeline handles emails for live responses."""
    results = []
    for m in _EMAIL_RE.finditer(text):
        header    = m.group(1).strip()
        body      = m.group(2).strip()
        recipient = None
        subject   = header
        if "|" in header:
            parts     = header.split("|", 1)
            recipient = parts[0].strip()
            subject   = parts[1].strip()
        elif "@" in header and "." in header:
            recipient = header
            subject   = "Notification"
        results.append((recipient, subject, body))
    return results


def clean_delegations(text: str) -> str:
    """Strip DELEGATE tags only — EMAIL_USER stripped by OutputPipeline."""
    return _DELEGATE_RE.sub("", text).strip()


def clean_response(text: str) -> str:
    """Legacy alias — use clean_delegations() for new code."""
    return clean_delegations(text)
```

- [ ] **Step 7: Smoke test the running container**

```bash
curl -s http://localhost:3031/api/capabilities | python3 -m json.tool | head -10
```
Expected: valid JSON, no 500 error

```bash
docker logs virtual-company --tail 20 2>&1 | grep -i "error\|exception\|import"
```
Expected: no new import errors

- [ ] **Step 8: Run all tests**

```bash
docker exec virtual-company python -m pytest tests/ -v 2>&1 | tail -20
```
Expected: all pass

- [ ] **Step 9: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/agents/executor.py app/api/websocket.py app/services/delegation.py
git commit -m "refactor(executor): remove tag regex, route all output through OutputPipeline"
```

---

## Task 7: Persona directives + `/api/filler` endpoint

**Files:**
- Modify: `app/agents/definitions.py`
- Modify: `app/api/router.py`

- [ ] **Step 1: Add VOICE & SINGING directives to `_ceo_persona()` in `definitions.py`**

In `_ceo_persona()`, find the `COMMUNICATION:` section. Insert the following block **before** it:

```python
VOICE & SINGING DIRECTIVES:
- Wrap all responses in: [SPEAK: your full reply | emotion: calm|excited|sad|whisper|energetic]
  Match emotion to context: user sounds sad → calm, user is hyped → energetic, good news → excited.
  Example: [SPEAK: That's done! | emotion: excited]
- If asked to sing, rap, hum, or perform ANYTHING:
  Compose full lyrics matching the song's style and energy.
  Output ONLY: [SING: <full lyrics with line breaks> | style: <genre, tempo, artist vibe>]
  NEVER write lyrics as plain text. NEVER say "I'll sing...". Just output the tag directly.
  Example: [SING: Look at the cash, look at the cash... | style: hip hop, Anderson .Paak, energetic, fast]
```

- [ ] **Step 2: Add VOICE & SINGING directives to `_worker_persona()`**

In `_worker_persona()`, find the `_inner()` function body. Add after `Stack: {stack}`:

```python
VOICE DIRECTIVE: Wrap your response in [SPEAK: your reply | emotion: calm|excited|energetic].
```

- [ ] **Step 3: Add `/api/filler` to `app/api/router.py`**

Find the router file's imports and add at the end of the file:

```python
@router.get("/api/filler")
async def get_filler(context: str = ""):
    """Return a pre-built Bark filler clip based on context keywords."""
    from app.services import bark_client
    audio = await bark_client.get_filler(context)
    return {"audio": audio}
```

- [ ] **Step 4: Verify endpoint exists**

```bash
curl -s http://localhost:3031/api/filler?context=sing | python3 -m json.tool
```
Expected: `{"audio": null}` (null because bark-svc not wired yet — that's fine for now)

- [ ] **Step 5: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/agents/definitions.py app/api/router.py
git commit -m "feat: add VOICE/SINGING persona directives and /api/filler endpoint"
```

---

## Task 8: Frontend — `AudioQueue`, filler, audio WebSocket, singing indicator

**Files:**
- Modify: `app/static/app-v5.js`
- Modify: `app/static/index.html`

- [ ] **Step 1: Add `b64ToBlob` helper to `app-v5.js`**

Find the `// ── Voice Engine` section (around line 787). Insert directly above it:

```javascript
// ── Audio helpers ────────────────────────────────────────────────────────────

function b64ToBlob(b64, mime = "audio/wav") {
  const bytes = atob(b64);
  const buf   = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) buf[i] = bytes.charCodeAt(i);
  return new Blob([buf], { type: mime });
}

function showSingingIndicator(on) {
  const el = document.getElementById("singing-indicator");
  if (el) el.style.display = on ? "flex" : "none";
}

const AudioQueue = {
  _queue:   [],
  _playing: false,

  push(base64, mode = "speak") {
    if (!base64) return;
    this._queue.push({ base64, mode });
    if (!this._playing) this._next();
  },

  async _next() {
    if (!this._queue.length) { this._playing = false; return; }
    this._playing  = true;
    const { base64, mode } = this._queue.shift();
    const blob = b64ToBlob(base64, "audio/wav");
    const url  = URL.createObjectURL(blob);
    const el   = new Audio(url);
    if (mode === "sing") showSingingIndicator(true);
    el.onended = () => {
      URL.revokeObjectURL(url);
      if (mode === "sing") showSingingIndicator(false);
      this._next();
    };
    el.onerror = () => { URL.revokeObjectURL(url); this._next(); };
    el.play().catch(() => this._next());
  }
};
```

- [ ] **Step 2: Add `case "audio"` to the WebSocket dispatch switch**

In `app-v5.js`, find the `dispatch` function's switch statement. Find `case "assistant":` block. Add a new case **before** it:

```javascript
    case "audio": {
      if (_ttsEnabled) AudioQueue.push(obj.data, obj.mode || "speak");
      break;
    }
```

- [ ] **Step 3: Update `case "assistant"` to use bark_ok fallback**

Find the existing `case "assistant":` block. It currently ends with `break;`. Add the fallback check before the `break`:

```javascript
    case "assistant": {
      const content = obj.message?.content || [];
      const texts = content.filter(b => b.type === "text" && b.text).map(b => b.text);
      const images = content.filter(b => b.type === "image" && b.data).map(b => ({
        media_type: b.media_type || "image/png",
        data: b.data
      }));
      if (texts.length > 0 || images.length > 0) {
        appendMsg(agentId, "assistant", texts.join("\n"), images);
      }
      // bark_ok: false means Bark didn't deliver audio — fall back to browser TTS
      if (_ttsEnabled && obj.bark_ok === false && texts.length > 0) {
        speakResponse(texts.join("\n"), agentId);
      }
      break;
    }
```

- [ ] **Step 4: Update `case "done"` to NOT always call speakResponse**

Find the `case "done":` block (around line 537). It currently calls `speakResponse(lastMsg.content, agentId)` unconditionally. Remove that call — the `case "assistant"` handler above now owns TTS triggering:

```javascript
    case "done":
    case "worker_done": {
      setWorkerState(agentId, "done");
      setReactorState("idle");
      clearThinking();
      if (obj.summary) appendMsg(agentId, "assistant", `✓ ${obj.summary}`);
      break;
    }
```

- [ ] **Step 5: Add filler fetch to `sendMsgText`**

In `sendMsgText()`, after `S.ws.send(JSON.stringify(payload));`, add:

```javascript
  // Fire filler audio immediately — plays while LLM + Bark generate the real response
  if (_ttsEnabled) {
    fetch("/api/filler?context=" + encodeURIComponent(text))
      .then(r => r.json())
      .then(({ audio }) => { if (audio) AudioQueue.push(audio, "filler"); })
      .catch(() => {});  // silent fail if bark-svc not ready
  }
```

- [ ] **Step 6: Add singing indicator to `app/static/index.html`**

Find the reactor/status area in `index.html` (search for `reactor` or the main chat header). Add the indicator inside the header area:

```html
<div id="singing-indicator" style="display:none; align-items:center; gap:6px; color:var(--cyan); font-size:13px; padding: 4px 10px;">
  <span style="animation: pulse 1s infinite;">🎵</span>
  <span>singing...</span>
</div>
```

Also add the pulse animation to the CSS section in index.html (or style-v5.css):

```css
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.3; }
}
```

- [ ] **Step 7: Pause recognition during AudioQueue playback (prevent mic picking up Bark audio)**

In the `AudioQueue._next()` method, add recognition pause/resume around playback. Update the `_next` method:

```javascript
  async _next() {
    if (!this._queue.length) { this._playing = false; return; }
    this._playing  = true;
    const { base64, mode } = this._queue.shift();
    const blob = b64ToBlob(base64, "audio/wav");
    const url  = URL.createObjectURL(blob);
    const el   = new Audio(url);
    if (mode === "sing") showSingingIndicator(true);
    // Pause mic while audio plays to prevent feedback loop
    if (_voiceEnabled && _recognition) { try { _recognition.stop(); } catch(e) {} }
    el.onended = () => {
      URL.revokeObjectURL(url);
      if (mode === "sing") showSingingIndicator(false);
      if (_voiceEnabled && _recognition) { try { _recognition.start(); } catch(e) {} }
      this._next();
    };
    el.onerror = () => { URL.revokeObjectURL(url); this._next(); };
    el.play().catch(() => this._next());
  }
```

- [ ] **Step 8: Verify UI loads without JS errors**

```bash
curl -s http://localhost:3031/ | grep -c "AudioQueue\|singing-indicator"
```
Expected: `2` (both appear in the served HTML/JS)

Open `http://<server-ip>:3031` in browser → open Dev Tools console → verify no JS errors on load.

- [ ] **Step 9: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/static/app-v5.js app/static/index.html
git commit -m "feat(frontend): add AudioQueue, Bark audio playback, singing indicator, filler on send"
```

---

## Task 9: Docker Compose wiring + end-to-end smoke test

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Update `docker-compose.yml`**

Add `bark-svc` service and wire up the volume and dependency:

```yaml
  bark-svc:
    build: ./bark-svc
    container_name: bark-svc
    volumes:
      - bark-models:/root/.cache/suno/bark_v0
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9001/health"]
      interval: 10s
      timeout: 5s
      retries: 30
      start_period: 120s
```

In the `virtual-company` service, add under `environment:`:

```yaml
      - BARK_SVC_URL=http://bark-svc:9001
```

And add `depends_on` under the `virtual-company` service:

```yaml
    depends_on:
      bark-svc:
        condition: service_healthy
```

At the bottom of the file, add the volume:

```yaml
volumes:
  bark-models:
```

- [ ] **Step 2: Build and start bark-svc**

```bash
cd /home/subaru/projects/virtual-company
docker-compose build bark-svc 2>&1 | tail -5
docker-compose up -d bark-svc
```

Wait for it to be healthy (first run downloads Bark model ~1.5GB — takes 3-5 min):

```bash
until docker inspect bark-svc --format='{{.State.Health.Status}}' | grep -q healthy; do
  echo "waiting for bark-svc..."; sleep 10
done && echo "bark-svc is healthy"
```

- [ ] **Step 3: Test Bark endpoints directly**

```bash
# Health
curl -s http://localhost:9001/health
# Expected: {"ready":true}

# Filler
curl -s "http://localhost:9001/filler?context=coding" | python3 -c "
import sys, json, base64
d = json.load(sys.stdin)
print('audio bytes:', len(base64.b64decode(d['audio'])) if d.get('audio') else 'None')
"
# Expected: audio bytes: <some number, e.g. 48000+>

# Speak
curl -s -X POST http://localhost:9001/speak \
  -H 'Content-Type: application/json' \
  -d '{"text":"Hello from Shadow Garden","emotion":"excited"}' | python3 -c "
import sys, json, base64
d = json.load(sys.stdin)
print('audio bytes:', len(base64.b64decode(d['audio'])))
"
# Expected: audio bytes: <non-zero number>
```

- [ ] **Step 4: Restart virtual-company to pick up BARK_SVC_URL**

```bash
docker-compose stop virtual-company
docker-compose up -d virtual-company
sleep 5
curl -s http://localhost:3031/api/filler?context=sing | python3 -m json.tool
```
Expected: `{"audio": "<base64 string>"}` — not null

- [ ] **Step 5: End-to-end test — voice response**

Open `http://<server-ip>:3031` in Chrome.
1. Enable TTS (toggle in header)
2. Type: `Hey, how are you doing?`
3. Expected:
   - Filler audio plays immediately ("Hmm, let me think...")
   - After ~3-5s, Bark-generated response audio plays
   - No browser SpeechSynthesis fallback fires (bark_ok should be true)
4. Open Dev Tools → Network → filter `filler` → confirm `/api/filler` request fires on send

- [ ] **Step 6: End-to-end test — singing**

Type: `Sing Bubbling by Anderson Paak`
Expected:
- "Warming up the vocals..." filler plays immediately
- 🎵 singing... indicator appears
- Full Bark-generated song audio plays
- Indicator disappears when audio ends
- Chat shows lyrics as text (from the SING tag stripped correctly)

- [ ] **Step 7: End-to-end test — fallback when Bark down**

```bash
docker stop bark-svc
```

Type: `Hello, what can you do?`
Expected:
- No filler audio (bark-svc down, filler returns null silently)
- Response text appears in chat
- Browser `SpeechSynthesis` kicks in (bark_ok: false triggers `speakResponse()`)
- Voice sounds robotic — that's the fallback working correctly

```bash
docker start bark-svc
```

- [ ] **Step 8: Run full test suite**

```bash
docker exec virtual-company python -m pytest tests/ -v 2>&1 | tail -20
```
Expected: all pass

- [ ] **Step 9: Final commit**

```bash
cd /home/subaru/projects/virtual-company
git add docker-compose.yml
git commit -m "feat: wire bark-svc into docker-compose with health gate and BARK_SVC_URL"
```

- [ ] **Step 10: Push to GitHub**

```bash
cd /home/subaru/projects/virtual-company
git remote set-url origin https://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@github.com/SauravShadow/Subaru_BOT.git
git push origin main
git remote set-url origin https://github.com/SauravShadow/Subaru_BOT.git
```

---

## Self-Review Checklist

- [x] Bark sidecar: `/speak`, `/sing`, `/filler`, `/health` — Task 1
- [x] Filler pool with context-aware selection — Task 1, `filler_pool.py`
- [x] `bark_client.py` with timeout + None fallback — Task 2
- [x] `OutputPipeline` with `TagRegistry` — Task 3
- [x] `speak.py` handler (SPEAK tag → Bark TTS) — Task 4
- [x] `sing.py` handler (SING tag → Bark singing) — Task 4
- [x] `image.py` handler (GENERATE_IMAGE tag) — Task 5
- [x] `email.py` handler (EMAIL_USER tag) — Task 5
- [x] `executor.py` refactor — all three backends call `pipeline.process()` — Task 6
- [x] `delegation.py` updated — Task 6
- [x] `websocket.py` email sending removed — Task 6
- [x] Persona directives (SPEAK/SING) in `definitions.py` — Task 7
- [x] `/api/filler` endpoint — Task 7
- [x] `AudioQueue` in frontend — Task 8
- [x] `case "audio"` WebSocket handler — Task 8
- [x] `bark_ok: false` → `speakResponse()` fallback — Task 8
- [x] Singing indicator `#singing-indicator` — Task 8
- [x] Filler fires on `sendMsgText` — Task 8
- [x] Mic pause during AudioQueue playback — Task 8
- [x] `docker-compose.yml` bark-svc + volume + depends_on — Task 9
- [x] End-to-end tests: voice, singing, fallback — Task 9
