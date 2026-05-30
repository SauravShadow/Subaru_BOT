# Floating Workers + Voice Fix — Design Spec

**Goal:** Replace the static bottom orb row with draggable floating worker cards that orbit the arc reactor and show live task status, and fix the broken/robotic voice system.

**Date:** 2026-05-30

---

## Section 1 — Voice Fixes

### 1a. Mic button wired to nothing
The 🎤 button in the command bar (`id="voice-btn"`, `index.html:68`) has no `onclick` handler. Add `onclick="toggleVoiceMode()"`. The header pill button works, but the cmdbar button the user actually clicks does not.

### 1b. Robotic TTS — voiceschanged race
`speakResponse()` calls `speechSynthesis.getVoices()` at speak-time. Chrome hasn't finished loading premium voice packages at that point, so it always falls back to the robotic system default. Fix: preload voices on the `voiceschanged` event into a module-level `_voices` array, also try loading immediately (Firefox/Safari already have voices synchronously). On speak, prefer voices with "Google" or "Microsoft" in the name for the matching language — Chrome ships "Google US English" which sounds significantly more human than the OS default.

**Voice preference order:**
1. Google or Microsoft voice matching agent's language
2. Any voice matching agent's language
3. OS default

---

## Section 2 — Floating Worker Cards

### Layout
Workers start in orbital positions around the arc reactor, computed as fixed coordinates on an ellipse. Five positions (one per agent):
- CEO: top-center (~46% left, 12% top)
- Backend: right (~76% left, 35% top)
- Frontend: bottom-right (~65% left, 68% top)
- QA: bottom-left (~28% left, 68% top)
- DevOps: left (~18% left, 35% top)

The `#workers-wrap` container uses `position:fixed; inset:0; pointer-events:none` so it covers the whole viewport without blocking clicks. Each `.worker-card` uses `position:absolute; pointer-events:all`.

### Draggable
`mousedown` on the card header starts a drag. If movement exceeds 4px threshold, it's a drag; otherwise it's a click (→ switch active agent). On `mouseup`, pixel positions are saved to `localStorage["workerPositions"]` as `{agentId: {left, top}}`. On reload, saved positions restore; if no saved position, the orbital default is used.

### Two visual states per card

**Idle (compact, ~110px wide):**
- Colored avatar circle + agent name + role title
- Colored border if this is the currently active agent (`.selected`)
- No status section shown

**Working (expanded, up to 220px wide):**
- Same header
- Status section below a separator: current action line + elapsed timer
- Pulsing border animation matching agent color
- Action line updates on every `tool_call` event
- Timer counts up from when `thinking` event fired

**State transitions (driven by WebSocket events):**
- `thinking` → `setWorkerState(agentId, "working", "Thinking…")` — expand, start timer
- `tool_call` → `setWorkerState(agentId, "working", label)` — update action line only (timer keeps running)
- `done` / `worker_done` → `setWorkerState(agentId, "done")` — flash "✓ Done" in green for 1.8s, then collapse
- `state_sync` → `renderWorkerCards()` — rebuild all cards from fresh agent state

### Removed
The `.orbs-wrap` HTML element and all `.orb*` CSS rules are removed entirely. `renderOrbs()` and `setOrbState()` are replaced by `renderWorkerCards()` and `setWorkerState()`.

---

## Files Changed

| File | Change |
|------|--------|
| `app/static/index.html` | Add `onclick` to voice-btn; replace `orbs-wrap` div with `workers-wrap` |
| `app/static/app-v5.js` | Replace orb system with worker cards; fix TTS voices; add drag; update dispatch |
| `app/static/style-v5.css` | Replace orb CSS block with worker card CSS |
