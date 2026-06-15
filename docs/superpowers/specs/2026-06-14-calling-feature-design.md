# Calling Feature Design
**Date:** 2026-06-14
**Status:** Approved

## Overview

Add bidirectional telephony to NEXUS virtual company using Twilio. NEXUS gets a single Twilio phone number used for both inbound (people call NEXUS) and outbound (NEXUS calls any number worldwide). A dedicated `call_agent` handles all telephony. Outbound calls use pre-rendered Bark TTS audio (zero latency during live calls); inbound calls use Twilio TTS (instant response). Fully automated — no human bridges or live participation. Agents can autonomously make calls as part of task execution.

---

## Goals

- User can trigger outbound calls from the UI (number + goal + language)
- CEO/agents can autonomously trigger outbound calls via `make_call` tool
- NEXUS answers inbound calls on the Twilio number with full agent intelligence
- Outbound calls pre-generate a Q&A script and Bark audio before dialing — zero Bark latency during the live call
- Unexpected questions fall back to Twilio TTS
- Full call transcript saved to SQLite and shown in UI after each call
- Bark voice upgraded to a mature adult male preset (`v2/en_speaker_6`), configurable
- Supports calling any country globally via Twilio's 180+ country network
- Twilio number is the sole caller ID — no Airtel integration

---

## Architecture

### Components

| Component | Location | Purpose |
|---|---|---|
| `telephony.py` | `app/services/telephony.py` | Twilio SDK wrapper, outbound dialer, TwiML response builders |
| `call_prep.py` | `app/agents/call_prep.py` | Script generation (LLM) + Bark pre-render engine |
| `call_store.py` | `app/services/call_store.py` | In-memory audio buffer during call; SQLite transcript after |
| `call_agent` | `app/agents/definitions.py` | Dedicated agent in the NEXUS roster |
| `CallPanel.tsx` | `nexus-ui/src/components/CallPanel.tsx` | UI for initiating calls and viewing history/transcripts |

### Existing Files Modified

| File | Change |
|---|---|
| `app/agents/tools.py` | Add `make_call(number, goal, language)` tool |
| `app/api/router.py` | Add call endpoints (see API section) |
| `app/config.py` | Add `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`, `BARK_SPEAKER` |
| `bark-lite/` | Accept `speaker` param, default `v2/en_speaker_6` |
| `app/agents/definitions.py` | Register `call_agent` |

### Environment Variables

```
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_PHONE_NUMBER=+1XXXXXXXXXX
BARK_SPEAKER=v2/en_speaker_6   # default; changeable per call from UI
```

---

## Call Agent

Dedicated agent in the NEXUS roster — owns all telephony.

```python
"call_agent": {
    "name": "Call Agent",
    "role": "Handles all voice calls — outbound script prep, live call state machine, inbound responses, transcripts",
    "tools": ["make_call", "get_call_transcript", "list_calls"],
    "icon": "📞",
}
```

**Invocation paths:**
1. **User → UI** → `POST /api/calls/outbound` → call_agent directly
2. **CEO → delegation** → `make_call(number, goal, language)` tool → call_agent
3. **Inbound** → Twilio webhook `/api/calls/inbound` → call_agent handles live

The call_agent runs as a standard LangGraph node — gets full Claude/Gemini/tgpt fallback, memory access, and can use browser/email tools during pre-call prep.

---

## Outbound Call Flow

### Phase 1: Pre-call Prep (before dialing)

1. call_agent receives `(number, goal, language)`
2. LLM generates a call script:
   - Opening line
   - 8–12 expected Q&A pairs covering likely responses
   - Closing line
3. Each script line is sent to Bark (`v2/en_speaker_6`, or configured speaker) → base64 WAV
4. WAVs stored in `call_store` keyed by `call_id + index`
5. Twilio `calls.create()` dials the number with webhook pointing to `/api/calls/gather`

**Example script** (goal: "Book a table for 2 at 7pm"):
```
opening:             "Hi, I'm calling to book a table for 2 people this evening at 7pm."
Q: "How many people?" → A: "2 people please."
Q: "What time?"       → A: "7pm would be perfect."
Q: "Name?"            → A: "Under Saurav please."
Q: "Phone number?"    → A: "I'll confirm on this number."
Q: "Any allergies?"   → A: "No allergies, thank you."
closing:             "That's wonderful, thank you so much!"
```

### Phase 2: Live Call

```
Twilio picks up → plays opening WAV via <Play>
Twilio <Gather> listens (STT, configurable language)
       │
       ▼
POST /api/calls/gather fires with transcription
       │
       ├─ fuzzy match vs script → <Play> pre-rendered WAV  (zero latency)
       ├─ no match              → <Say> Twilio TTS response (generated on-the-fly by LLM)
       └─ hangup detected       → <Hangup>
       │
       ▼
Loop back to <Gather>
```

Fuzzy matching uses normalized string similarity (threshold ~0.6). On no-match, LLM generates a contextual response within 1–2 seconds and Twilio TTS speaks it.

### Phase 3: Post-call

1. Full transcript written to SQLite (`calls` table)
2. call_agent summarizes outcome (one sentence)
3. WebSocket broadcasts `{type: "call_complete", call_id, summary, transcript}` to UI
4. If CEO-delegated, outcome returned as tool result to CEO

---

## Inbound Call Flow

```
Someone dials Twilio number
       │
POST /api/calls/inbound (Twilio webhook)
       │
call_agent greets with Twilio TTS: "Hi, this is NEXUS. How can I help?"
       │
<Gather> listens
       │
POST /api/calls/inbound/respond fires with transcription
       │
call_agent LangGraph turn (has memory, tools, full context)
       │
<Say> Twilio TTS response (instant)
       │
Loop → <Gather>
       │
Caller hangs up → transcript saved → WS broadcast
```

Inbound uses **Twilio TTS exclusively** — caller is on the line, no time for Bark pre-rendering. The agent has full tool access (memory, browser, email, projects).

---

## API Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/calls/outbound` | User-initiated call from UI |
| `POST` | `/api/calls/inbound` | Twilio webhook — inbound call arrives |
| `POST` | `/api/calls/inbound/respond` | Twilio webhook — inbound STT result, returns TwiML |
| `POST` | `/api/calls/gather` | Twilio webhook — outbound STT result, fuzzy match, returns TwiML |
| `GET` | `/api/calls/audio/{call_id}/{idx}` | Serves pre-rendered Bark WAV (Twilio fetches this URL) |
| `GET` | `/api/calls/history` | List past calls — supports `?q=`, `?number=`, `?direction=`, `?from=`, `?to=`, `?outcome=` filters |
| `GET` | `/api/calls/{call_id}/transcript` | Full transcript for a call |
| `GET` | `/api/calls/search?q=<text>` | Full-text search across all call transcripts and summaries |

All Twilio webhooks return TwiML (XML). The audio endpoint must be publicly reachable by Twilio — served via the existing Cloudflare tunnel.

---

## Data Storage

### In-memory (during call lifetime)
```python
# call_store.py
_active_calls: dict[str, CallSession] = {}

@dataclass
class CallSession:
    call_id: str
    direction: str          # "outbound" | "inbound"
    number: str
    goal: str
    language: str
    script: list[ScriptEntry]    # Q&A pairs with pre-rendered audio paths
    transcript: list[Turn]
    started_at: datetime
```

### SQLite (after call ends)
New `calls` table in `nexus_memory.db`:
```sql
CREATE TABLE calls (
    id TEXT PRIMARY KEY,
    direction TEXT,
    number TEXT,
    goal TEXT,
    language TEXT,
    outcome TEXT,
    summary TEXT,
    transcript_json TEXT,
    started_at TEXT,
    ended_at TEXT
);
```

Pre-rendered WAV files live in a temp dir (`/tmp/nexus_calls/{call_id}/`) and are cleaned up after the call ends.

---

## UI: CallPanel

New `CallPanel.tsx` — accessible from main NEXUS sidebar.

```
┌─────────────────────────────────────────────┐
│  📞 CALL PANEL                              │
│                                             │
│  ┌─────────────────────────────────────┐   │
│  │  +91 98XXXXXXXX          [Call]     │   │
│  │  Goal: Book a table for 2 at 7pm    │   │
│  │  Language: English ▼    Voice: 6 ▼  │   │
│  └─────────────────────────────────────┘   │
│                                             │
│  ACTIVE CALL ──────────────────────────     │
│  🔴 Dialing +91-98XXXXXXXX...              │
│  ✅ Connected — Pre-call prep complete      │
│  🗣  Them: "How can I help you?"           │
│  🤖 NEXUS: "Hi, booking table for 2..."   │
│  🗣  Them: "What time?"                    │
│  🤖 NEXUS: "7pm please."                  │
│  ✅ Call ended — Table booked              │
│                                             │
│  CALL HISTORY ─────────────────────────     │
│  ✅ +91-9812345678  Book table   2m ago    │
│  ✅ +1-415-555-0100 Flight info  1h ago    │
│  ❌ +44-20-1234567  Visa query   3h ago    │
└─────────────────────────────────────────────┘
```

**Elements:**
- Phone number input (international format)
- Goal/instruction textarea
- Language dropdown (English, Hindi, Spanish, French, etc.)
- Voice preset selector (Bark speaker `v2/en_speaker_0` through `v2/en_speaker_9`)
- Real-time call log streamed via existing WebSocket
- Active call status: dialing → prep → connected → turn-by-turn → ended
- Call history with ✅/❌ outcome and one-line summary
- Clicking history item expands full turn-by-turn transcript
- **Search bar** — searches across all call transcripts and summaries in real-time
- **Filters** — direction (inbound/outbound), outcome (success/failed), date range, phone number prefix
- History is persistent across restarts (SQLite-backed)

**Entry points:**
- Sidebar icon in main NEXUS UI
- Agent task view — when CEO delegates a call, shows inline in agent task feed

---

## Voice Configuration

```python
# app/config.py
BARK_SPEAKER = os.getenv("BARK_SPEAKER", "v2/en_speaker_6")  # deep adult male
```

Bark speaker presets available: `v2/en_speaker_0` through `v2/en_speaker_9`. Speaker 6 is the recommended default (deeper, more professional). Configurable per-call from the UI voice selector.

For non-English calls, Bark has multilingual presets (`v2/es_speaker_*`, `v2/hi_speaker_*`, etc.) — the call_agent selects the appropriate preset based on the `language` param.

---

## Language Support

| Layer | Languages | Notes |
|---|---|---|
| Bark TTS (outbound pre-rendered) | EN, ES, FR, DE, HI, IT, JA, KO, PT, RU, ZH | EN quality is best |
| Twilio STT (speech recognition) | 30+ languages | Configured via `<Gather language="...">` |
| Twilio TTS (inbound + fallback) | 50+ languages | Via `<Say language="...">` |
| Script generation (LLM) | Any language | Claude/Gemini generate in target language |

---

## Security

- Twilio webhook requests validated via `X-Twilio-Signature` header on all inbound webhooks
- Audio files served at `/api/calls/audio/{call_id}/{idx}` — `call_id` is a UUID, not guessable
- Temp audio files deleted immediately after call ends
- `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN` in `.env`, never committed

---

## Out of Scope

- Live call monitoring / listen-in (fully automated, no bridging)
- Call recording (transcript only, no audio recording stored)
- Airtel number integration
- Video calls
- Conference calls with multiple parties
