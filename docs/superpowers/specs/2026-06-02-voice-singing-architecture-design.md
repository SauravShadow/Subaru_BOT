# Voice, Singing & Extensible Output Architecture

**Date:** 2026-06-02
**Status:** Approved for implementation
**Goal:** Replace browser SpeechSynthesis with Bark (self-hosted), add real singing capability, and refactor `executor.py` into a clean extensible output pipeline.

---

## 1. Problem Statement

Three separate problems addressed together:

1. **Voice quality is robotic.** Current TTS uses browser `SpeechSynthesis` — OS-level text-to-speech with no emotional range and zero singing capability.
2. **Singing is fake.** When asked to sing, the bot writes lyrics as plain text. The user wants actual sung audio.
3. **executor.py is a 1,068-line monolith.** Tag handling (`[GENERATE_IMAGE:]`, `[EMAIL_USER:]`) is copy-pasted across three backends (Claude, Gemini, tgpt). Adding any new output capability requires touching all three.

---

## 2. Chosen Approach

**Approach A: TagRegistry + Bark Sidecar**

- `executor.py` becomes LLM-routing only (~320 lines)
- New `app/output/` layer handles all output tags via a registry
- Bark runs as a dedicated Docker sidecar (keeps ML deps out of the app container)
- Browser `SpeechSynthesis` remains as a graceful fallback when Bark is unavailable

---

## 3. Architecture Overview

```
┌─────────────────────── Browser ───────────────────────────┐
│  Web Speech API (STT) ──► WebSocket ──► FastAPI           │
│  AudioQueue ◄──────────── WebSocket ◄──                   │
│  SpeechSynthesis ◄──── fallback when bark_ok: false       │
└───────────────────────────────────────────────────────────┘
                               │
              ┌────────────────┴─────────────────┐
              ▼                                   ▼
   ┌─────────────────────┐            ┌──────────────────────┐
   │   app container     │            │   bark-svc container  │
   │                     │  HTTP      │                       │
   │  executor.py        │◄──────────►│  POST /speak          │
   │  (LLM routing only) │            │  POST /sing           │
   │                     │            │  GET  /filler         │
   │  OutputPipeline     │            │  GET  /health         │
   │  TagRegistry        │            │                       │
   │  └─ speak.py        │            │  Bark model loaded    │
   │  └─ sing.py         │            │  once on startup      │
   │  └─ image.py        │            │  Filler pool pre-built│
   │  └─ email.py        │            └──────────────────────┘
   │  └─ [future].py     │
   └─────────────────────┘
```

---

## 4. New File Structure

```
app/
├── agents/
│   ├── executor.py          (~320 lines — LLM routing + tool loops only)
│   ├── definitions.py       (personas — gains SPEAK/SING directives)
│   ├── backend_state.py     (unchanged)
│   └── tools.py             (bash/read/write — generate_image removed)
├── output/                  ← NEW
│   ├── __init__.py
│   ├── pipeline.py          ← scans LLM output, dispatches tags, strips them
│   ├── registry.py          ← maps tag names → handler modules
│   └── handlers/
│       ├── speak.py         ← [SPEAK: text | emotion: excited]
│       ├── sing.py          ← [SING: lyrics | style: hip hop, fast]
│       ├── image.py         ← [GENERATE_IMAGE: description]
│       └── email.py         ← [EMAIL_USER: addr | subject] body
├── services/
│   └── bark_client.py       ← NEW: HTTP client for bark-svc
└── ... (all other files unchanged)

bark-svc/                    ← NEW Docker service
├── Dockerfile
├── main.py                  ← FastAPI app with /speak /sing /filler /health
├── filler_pool.py           ← pre-generates 15 filler clips on startup
└── requirements.txt
```

---

## 5. TagRegistry & OutputPipeline

### registry.py
Maps tag names to handler modules. Adding a new tag = one line here + one new file in `handlers/`.

```python
from app.output.handlers import speak, sing, image, email

REGISTRY = {
    "SPEAK":          speak,
    "SING":           sing,
    "GENERATE_IMAGE": image,
    "EMAIL_USER":     email,
}
```

### Handler contract
Every handler must export:
- `TAG: str` — the tag name
- `PATTERN: re.Pattern` — compiled regex matching the full tag
- `async handle(args: str, agent_id: str, send: Sender) -> tuple[str, bool]`
  - Returns `(display_text, bark_ok)` — display_text goes back into the response, bark_ok signals audio delivery

### pipeline.py
Single call at the end of every backend (replaces all scattered regex):

```python
async def process(text: str, agent_id: str, send: Sender) -> str:
    display = text
    bark_ok = False
    for tag_name, handler in REGISTRY.items():
        for match in handler.PATTERN.finditer(text):
            result_text, audio_sent = await handler.handle(
                match.group(1), agent_id, send
            )
            display = handler.PATTERN.sub(result_text, display, count=1)
            if audio_sent:
                bark_ok = True
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

### executor.py after refactor
Every backend's final block becomes identical:

```python
await pipeline.process(full_resp, agent_id, send)
return full_resp
```

---

## 6. Bark Sidecar

### Endpoints

| Method | Path | Input | Output |
|--------|------|-------|--------|
| POST | `/speak` | `{text, emotion, agent_id}` | `{audio: base64_wav}` |
| POST | `/sing` | `{lyrics, style}` | `{audio: base64_wav}` |
| GET | `/filler` | `?context=<user_msg>` | `{audio: base64_wav}` |
| GET | `/health` | — | `{ready: bool}` |

### Emotion → Bark speaker profiles

| Emotion | Speaker | Temperature |
|---------|---------|-------------|
| excited | v2/en_speaker_6 | 0.9 |
| calm | v2/en_speaker_2 | 0.6 |
| sad | v2/en_speaker_3 | 0.5 |
| whisper | v2/en_speaker_0 | 0.4 |
| energetic | v2/en_speaker_9 | 1.0 |

### Filler pool (pre-generated on startup)

```python
FILLER_POOL = {
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
```

Context-aware selection:
- Coding/debug request → "thinking" category
- Health/food/sleep mention → "health" category
- Sing/music/creative → "creative" category
- Default → random from thinking + facts

### docker-compose.yml additions

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
    start_period: 90s

virtual-company:
  depends_on:
    bark-svc:
      condition: service_healthy
  environment:
    - BARK_SVC_URL=http://bark-svc:9001

volumes:
  bark-models:
```

---

## 7. Singing Pipeline

### Tag format (in LLM output)
```
[SING: Look at the cash, look at the cash...
       Look at my mesh, look at my stash...
       I'm bubbling! | style: hip hop, Anderson .Paak, energetic, fast, punchy bass]
```

### sing.py handler
```python
async def handle(args: str, agent_id: str, send: Sender) -> tuple[str, bool]:
    lyrics, style = _parse_sing_args(args)   # splits on " | style:"
    bark_text = f"♪ {lyrics} ♪"
    speaker = _style_to_speaker(style)       # maps genre/energy to speaker profile
    audio = await bark_client.sing(bark_text, speaker)
    if audio:
        await send({"type": "audio", "mode": "sing", "data": audio})
        return "", True
    # Bark down — show lyrics as text
    return lyrics, False
```

### Persona directive (added to all agents in definitions.py)
Placed before `AVAILABLE TOOLS:` so Gemini's clean_persona strip preserves it:

```
VOICE & SINGING DIRECTIVES:
- Wrap all responses: [SPEAK: your full reply | emotion: calm|excited|sad|whisper|energetic]
- If asked to sing, rap, hum, or perform — compose full lyrics matching the style and energy.
  Output ONLY: [SING: <lyrics with line breaks> | style: <genre, tempo, artist vibe>]
  NEVER write lyrics as plain text. NEVER say "I'll sing..." — just output the tag directly.
- Match emotion to context: sad user → calm, hyped user → energetic.
```

---

## 8. Frontend Changes (app-v5.js)

### What stays (unchanged)
- `SpeechRecognition` / wake word "hey subaru" — voice input fully unchanged
- `speakResponse()` — becomes the Bark fallback
- `AGENT_VOICES` — used by fallback speakResponse()
- `detectEmotion()` — used by fallback speakResponse()

### What changes
- `speakResponse()` no longer called on every assistant message — only when `bark_ok: false`
- New `AudioQueue` plays Bark audio in order (filler first, then real response)
- New filler fetch fires on every message send
- New `case "audio"` handler in WebSocket message switch
- New singing visual indicator `#singing-indicator`

### AudioQueue
```javascript
const AudioQueue = {
  _queue: [], _playing: false,
  push(base64, mode = "speak") {
    this._queue.push({ base64, mode });
    if (!this._playing) this._next();
  },
  async _next() {
    if (!this._queue.length) { this._playing = false; return; }
    this._playing = true;
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
    el.play();
  }
};
```

### Updated WebSocket message handling
```javascript
case "audio":
  if (_ttsEnabled) AudioQueue.push(msg.data, msg.mode || "speak");
  break;
case "assistant":
  // ... existing render logic ...
  if (_ttsEnabled && !msg.bark_ok) {
    speakResponse(lastMsg.content, agentId);  // fallback to SpeechSynthesis
  }
  break;
```

### Filler on send
```javascript
async function sendMsgText(text) {
  // ... existing logic ...
  if (_ttsEnabled) {
    fetch("/api/filler?context=" + encodeURIComponent(text))
      .then(r => r.json())
      .then(({ audio }) => { if (audio) AudioQueue.push(audio, "filler"); });
  }
}
```

---

## 9. Error Handling & Degradation

| Scenario | Behaviour |
|---|---|
| Bark working | Bark audio via AudioQueue |
| Bark down / timeout | `bark_ok: false` → `speakResponse()` SpeechSynthesis fallback |
| User disables TTS | No filler fetch, no audio, text only |
| `[SING:]` + Bark down | Lyrics shown as text in chat |
| Filler pool not ready | `/api/filler` returns empty, browser skips silently |
| Bark first boot (~60s warmup) | `depends_on: service_healthy` holds app until ready |
| New tag needed | Add `handlers/newtag.py` + one line in `registry.py` — nothing else changes |

---

## 10. Implementation Order

1. **Bark sidecar** — `bark-svc/` Docker service, `/speak` `/sing` `/filler` `/health`
2. **bark_client.py** — HTTP client with timeout + None fallback
3. **app/output/** — `pipeline.py`, `registry.py`, handlers (speak, sing, image, email)
4. **executor.py refactor** — remove tag regex, call `pipeline.process()` at end of each backend
5. **definitions.py** — add VOICE & SINGING directives to all personas
6. **router.py** — add `/api/filler` endpoint
7. **app-v5.js** — AudioQueue, filler on send, `case "audio"`, singing indicator, fallback logic
8. **docker-compose.yml** — bark-svc service, volume, depends_on, BARK_SVC_URL env var
