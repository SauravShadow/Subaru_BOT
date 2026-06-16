# Human-like Calling Agent — Design Spec

**Date:** 2026-06-16
**Status:** Approved (brainstorm → spec). Supersedes the exploratory notes in
`.gemini/antigravity-ide/brain/.../calling_agent_brainstorming.md`.

**Goal:** Make the NEXUS Telnyx calling agent feel like a natural human conversationalist —
primarily by cutting per-turn latency and adding interruption/humanization behaviors — while
**keeping the custom Call Control loop** (webhook → LLM → Telnyx `speak`). Telnyx's native
real-time Voice AI is intentionally out of scope (noted as an alternative in the appendix).

---

## 1. Grounding: how the loop actually works today

This corrects drift in the original brainstorm. As of 2026-06-16 the live implementation is:

- **Transport:** Telnyx **Call Control**. One webhook `POST /api/calls/webhook`
  (Ed25519-verified) dispatches `call.initiated/answered/transcription/hangup` in
  `app/api/router.py`. SDK wrapped in `app/services/telephony.py`.
- **STT:** `start_transcription` with an explicit **Google engine**,
  `transcription_engine_config={language:<short>, interim_results: True}`, track `inbound`
  (remote party only). **Interim results are already enabled** — interim
  `call.transcription` events already arrive; today we **drop everything except
  `is_final`**.
- **Reply:** `_live_reply()` → `call_prep.quick_reply()` (gemini-3.5-flash, 4s timeout;
  fallback Claude CLI; then a canned line). Passes the generated script answers as
  `talking_points` (guidance, not canned text).
- **Output:** Telnyx **`speak` (server TTS)**, single voice (`TELNYX_VOICE=female`),
  `payload_type` currently defaults to text. **No pre-rendered WAV playback** (bark
  pre-render was removed). The original doc's "speak (WAV)" is therefore outdated.
- **No interruption support:** there is **no `is_speaking` state** and **no `speak_stop`
  action exists in the Telnyx SDK** (verified against telnyx 4.153.0: actions include
  `stop_playback`, `stop_gather`, `stop_transcription`, … but nothing to stop an
  in-progress `speak`).

### Latency model (to be replaced by measurement — see §2)
Approximate current per-turn budget (~2.5–4.0s), dominant cost first:
1. **STT end-of-turn silence** before `is_final` (~1.2–2.0s) — the biggest lever.
2. **LLM inference** (`quick_reply`, gemini-flash) (~0.5–2.5s; 4s timeout).
3. **Telnyx `speak` TTS** synthesis + playback start (~0.3–0.6s).
4. Webhook network hops (~tens of ms).

Target: median turn response **< 1.2s** (stretch ~0.9s).

---

## 2. Measure first (prerequisite for every later phase)

Before optimizing, instrument the loop so each change is validated against real numbers.

- Add monotonic timestamps to the live session for: `last_interim_at`, `final_at`,
  `llm_done_at`, `speak_issued_at`.
- On each completed turn, log a single structured line:
  `turn latency: stt_gap=<final-last_interim>ms llm=<llm_done-final>ms tts_issue=<speak-llm_done>ms total=<speak-final>ms`.
- Optionally expose the last-N turn latencies on `GET /api/calls/{id}/live` for the dashboard.

This section ships first and stays — it gates whether Phase 2 (speculative) is even needed.

---

## 3. Phase 1 — Cut the turn-taking gap (low risk)

Two complementary, low-risk changes:

1. **Tune Google endpointing.** Set a shorter end-of-speech window in
   `transcription_engine_config` (e.g. enable Google's `single_utterance`/end-of-speech
   sensitivity where available) so `is_final` arrives sooner. Keep `interim_results: True`.
2. **Server-side interim-silence timer.** Track `last_interim_text` / `last_interim_at`.
   When interim text is **non-empty and unchanged for ~700ms**, treat it as end-of-turn and
   respond immediately — without waiting for `is_final`. When `is_final` later arrives,
   ignore it if we already responded to that text (dedupe by normalized text).

**Edge cases:** debounce so a single turn never triggers two replies; reset the timer on
every new interim; ignore empty/whitespace interims; cap one in-flight reply per call.

**Expected:** ~1.5s → ~0.9s STT gap. Measure (§2) before deciding on Phase 2.

---

## 4. Phase 2 — Speculative pre-generation (conditional)

**Only build this if Phase 1's measured latency is still too high.**

- When the interim-silence timer is *close* to firing (e.g. text stable ~400ms), fire
  `quick_reply` **speculatively** on the current interim text; cache the result on the
  session keyed by the normalized interim text.
- On end-of-turn (timer fire or `is_final`): if the final text matches the speculative
  key, `speak` the cached reply immediately (saves the LLM round-trip); otherwise discard
  and generate normally.
- **Concurrency:** at most one speculative request in flight; abort/ignore stale results
  when the interim text changes (compare-and-swap on the key).

Complexity is real (races, wasted LLM calls, dedupe) — hence gated on measured need.

---

## 5. Barge-in (interruption) — corrected design

**Constraint:** Telnyx `speak` cannot be stopped mid-utterance (no `speak_stop`). So true
hard cut-off is **not possible while we use `speak`**. Two options:

### Option E1 — Pragmatic (chosen for this plan)
- Keep `speak`. Enforce **one short sentence per reply** (quick_reply already aims for this;
  add a hard length cap) so the un-interruptible window is small.
- Track `is_speaking` via `call.speak.started` / `call.speak.ended` events.
- If the caller speaks (interim transcription) **while** `is_speaking`, do **not** hard-stop;
  instead **queue** their utterance and handle it as the next turn the moment
  `call.speak.ended` arrives. This avoids dropping their input and avoids overlap chaos.

### Option E2 — True hard barge-in (documented, not built now)
- Deliver AI audio via **`start_playback` (stoppable) + `stop_playback`** instead of `speak`.
  Requires pre-synthesizing each reply to an audio file/URL (a TTS round-trip or bark),
  which reintroduces latency and partially conflicts with the single-voice / low-latency
  goals. Or use **bidirectional media streaming** (`streaming_start`) for full control.
- Revisit only if E1's "no hard interrupt" proves insufficient in real use.

---

## 6. Verbal fillers (perceived-latency win, low risk)

- If `quick_reply` has not returned within **~1.0s**, immediately `speak` a short filler
  ("Let me check…", "Sure, one sec…") chosen at random, then `speak` the real reply when
  ready. Resets the caller's wait clock and buys the LLM time.
- Guard against double-speak: only one filler per turn; skip if the reply already returned.
- Respects `is_speaking` (don't filler-over an in-progress line).

---

## 7. SSML prosody (polish)

- Prompt the LLM to optionally wrap output in SSML (`<break time="..."/>`,
  `<emphasis>`); send via `speak(payload_type="ssml")` (Telnyx supports it).
- Sanitize/validate: if the model returns malformed SSML, fall back to plain text
  (`payload_type="text"`) so a bad tag never fails the `speak` (recall: a failed command
  no longer 500s — it's caught — but a silent no-audio turn is still bad).

---

## 8. Backchanneling (experimental — last, behind a flag)

- During a long caller turn (several interims, no pause), optionally play a very short, soft
  acknowledgement ("mm-hmm"). **Highest risk** (talking over the caller; timing-sensitive;
  with `speak` it can't be cut). Behind a config flag, off by default, last phase, may be cut
  after evaluation.

---

## 9. State model changes

Add to `CallSession` (in `app/services/call_store.py`):
- `is_speaking: bool` — set on `call.speak.started`, cleared on `call.speak.ended`.
- `last_interim_text: str`, `last_interim_at: float` — for the interim-silence timer.
- `pending_caller_text: str | None` — queued barge-in utterance (E1).
- `speculative_reply: dict | None` — `{key, text}` cache (Phase 2 only).
- latency timestamps (§2).

Interim handling moves into the `call.transcription` branch of `api_calls_webhook`, which
must now process **interim** events (timer/speculation/barge-in), not just finals.

---

## 10. Phasing & exit criteria

| Phase | Scope | Ship gate |
|-------|-------|-----------|
| 0 | Latency instrumentation (§2) | metrics visible per turn |
| 1 | Endpointing tune + interim-silence timer (§3) | median total < ~1.5s, no double-replies |
| 1b | Verbal fillers (§6) + barge-in E1 (§5) | no overlap/echo; caller turns never dropped |
| 1c | SSML prosody (§7) | natural prosody; malformed-SSML falls back cleanly |
| 2 | Speculative pre-gen (§4) — only if Phase 1 insufficient | measured total < ~1.0s |
| 3 | Backchanneling (§8) — experimental, flagged | qualitative; cut if it talks over caller |

Each phase is independently shippable and measured against §2.

---

## 11. Testing

- Unit-test pure logic: interim-silence timer (state machine), dedupe of
  interim-vs-final, SSML sanitize/fallback, filler trigger threshold, barge-in queue.
- Mock Telnyx command calls (as existing call tests do) — assert the right action fires for
  each event/timing scenario.
- Manual live-call verification per phase (place a call, watch the live dashboard +
  latency log).

---

## Appendix A — Alternative not chosen: Telnyx native Voice AI

Telnyx offers `start_ai_assistant` / `start_conversation_relay` / `gather_using_ai` and
bidirectional media streaming, which provide native streaming STT+LLM+TTS with built-in
turn-taking and barge-in (sub-second). This would replace most of the custom loop but cedes
control and ties us to Telnyx's stack. Out of scope per the chosen "optimize the custom
loop" direction; revisit if custom optimization plateaus above target latency.
