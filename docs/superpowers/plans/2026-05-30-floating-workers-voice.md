# Floating Workers + Voice Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the static bottom orb row with draggable floating worker cards showing live task status, and fix the broken/robotic voice system.

**Architecture:** Pure frontend changes across three files — no Python/backend changes needed. The existing WebSocket event stream (`thinking`, `tool_call`, `done`, `state_sync`) already carries all the data the worker cards need. Drag positions persist in `localStorage`. Voice fix uses the `voiceschanged` event to preload premium browser voices.

**Tech Stack:** Vanilla JS (ES2020), CSS custom properties, Web Speech API, localStorage

---

## Context You Must Know

- Working directory: `/home/subaru/projects/virtual-company`
- The app runs at `http://localhost:3030` (proxied by `operations_sidecar.py` in the container)
- Three frontend files: `app/static/index.html`, `app/static/app-v5.js` (~806 lines), `app/static/style-v5.css`
- No JS test suite — verification is done by running the app and observing behaviour
- Python tests live in `tests/` — run `cd /home/subaru/projects/virtual-company && python -m pytest tests/ -q` to confirm nothing broke
- The existing drag pattern (`initDraggableIslands` at `app-v5.js:347`) uses the same `mousedown/mousemove/mouseup` approach we extend here
- Agent IDs are: `ceo`, `backend`, `frontend`, `qa`, `devops`
- Agent colors come from `definitions.py`: `#00d4ff`, `#ff8c42`, `#ff6b9d`, `#a78bfa`, `#34d399`

---

## Task 1: Fix Voice — Wire Button + Human TTS

**Files:**
- Modify: `app/static/index.html:68`
- Modify: `app/static/app-v5.js:682-778`

### Why the mic button is broken
`index.html:68` — the cmdbar mic button has no `onclick`:
```html
<button class="cmdbar-btn" id="voice-btn" title="Voice input">🎤</button>
```
The header pill button (`voice-toggle-btn`) has `onclick="toggleVoiceMode()"` and works. The cmdbar button the user clicks does nothing.

### Why TTS sounds robotic
`app-v5.js:774` — `getVoices()` is called at speak-time. Chrome loads premium voices asynchronously; at speak-time the array is empty so it falls back to the OS robotic default.

- [ ] **Step 1: Wire the cmdbar mic button**

In `app/static/index.html`, find line 68:
```html
<button class="cmdbar-btn" id="voice-btn" title="Voice input">🎤</button>
```
Change to:
```html
<button class="cmdbar-btn" id="voice-btn" title="Voice input (Hey Subaru)" onclick="toggleVoiceMode()">🎤</button>
```

- [ ] **Step 2: Add voice preload cache at module level**

In `app/static/app-v5.js`, find the voice section comment at line ~682:
```javascript
// ── Voice Engine ────────────────────────────────────────────────────────────

const AGENT_VOICES = {
```
Replace with:
```javascript
// ── Voice Engine ────────────────────────────────────────────────────────────

const AGENT_VOICES = {
  ceo:      { lang: "en-GB", pitch: 0.9, rate: 0.95 },
  frontend: { lang: "en-US", pitch: 1.1, rate: 1.0  },
  backend:  { lang: "en-US", pitch: 0.7, rate: 0.85 },
  qa:       { lang: "en-US", pitch: 1.0, rate: 0.9  },
  devops:   { lang: "en-US", pitch: 0.8, rate: 0.9  },
};

let _cachedVoices = [];
if (window.speechSynthesis) {
  const _loadVoices = () => { _cachedVoices = window.speechSynthesis.getVoices(); };
  _loadVoices();
  window.speechSynthesis.addEventListener("voiceschanged", _loadVoices);
}
```

- [ ] **Step 3: Update speakResponse to prefer premium voices**

Find `speakResponse` function (line ~765):
```javascript
function speakResponse(text, agentId) {
  if (!_ttsEnabled || !window.speechSynthesis || !text) return;
  speechSynthesis.cancel();
  const clean = text.replace(/```[\s\S]*?```/g, "code block").slice(0, 500);
  const utter  = new SpeechSynthesisUtterance(clean);
  const profile = AGENT_VOICES[agentId] || AGENT_VOICES.ceo;
  utter.lang    = profile.lang;
  utter.pitch   = profile.pitch;
  utter.rate    = profile.rate;
  const voices  = speechSynthesis.getVoices();
  const match   = voices.find(v => v.lang.startsWith(profile.lang.split("-")[0]));
  if (match) utter.voice = match;
  speechSynthesis.speak(utter);
}
```
Replace with:
```javascript
function speakResponse(text, agentId) {
  if (!_ttsEnabled || !window.speechSynthesis || !text) return;
  speechSynthesis.cancel();
  const clean   = text.replace(/```[\s\S]*?```/g, "code block").slice(0, 500);
  const utter   = new SpeechSynthesisUtterance(clean);
  const profile = AGENT_VOICES[agentId] || AGENT_VOICES.ceo;
  utter.lang    = profile.lang;
  utter.pitch   = profile.pitch;
  utter.rate    = profile.rate;
  const voices  = _cachedVoices.length ? _cachedVoices : speechSynthesis.getVoices();
  const langPrefix = profile.lang.split("-")[0];
  const preferred  = voices.find(v => v.lang.startsWith(langPrefix) && /google|microsoft/i.test(v.name))
                  || voices.find(v => v.lang.startsWith(langPrefix));
  if (preferred) utter.voice = preferred;
  speechSynthesis.speak(utter);
}
```

- [ ] **Step 4: Verify Python tests still pass**

```bash
cd /home/subaru/projects/virtual-company && python -m pytest tests/ -q
```
Expected: all tests pass (no Python code changed, just confirming).

- [ ] **Step 5: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/static/index.html app/static/app-v5.js
git commit -m "fix: wire cmdbar mic button and use premium TTS voices"
```

---

## Task 2: Worker Card CSS

**Files:**
- Modify: `app/static/style-v5.css:58-68`

Replace the entire `/* ── Agent Orbs */` CSS block (lines 58–68) with the worker card styles below. The old orb styles are fully removed.

- [ ] **Step 1: Replace orb CSS block with worker card CSS**

Find in `app/static/style-v5.css`:
```css
/* ── Agent Orbs ────────────────────────────────────────────────── */
.orbs-wrap { position: fixed; bottom: 90px; left: 50%; transform: translateX(-50%); display: flex; gap: 16px; z-index: 20; }
.orb { position: relative; width: 44px; height: 44px; border-radius: 50%; background: var(--bg-card); border: 2px solid var(--border); cursor: pointer; transition: all .25s ease; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 600; color: var(--muted); }
.orb:hover { transform: scale(1.15); }
.orb.active { border-color: var(--agent-color, var(--cyan)); box-shadow: 0 0 16px var(--agent-color, var(--cyan)); color: var(--agent-color, var(--cyan)); }
.orb.thinking { animation: orb-pulse 1s ease-in-out infinite; }
@keyframes orb-pulse { 0%,100% { box-shadow: 0 0 8px var(--agent-color, var(--cyan)); } 50% { box-shadow: 0 0 24px var(--agent-color, var(--cyan)); } }
.orb-tooltip { position: absolute; bottom: calc(100% + 8px); left: 50%; transform: translateX(-50%); white-space: nowrap; background: var(--bg-elevated); border: 1px solid var(--border); border-radius: var(--radius); padding: 8px 12px; font-size: 12px; pointer-events: none; opacity: 0; transition: opacity .15s; z-index: 200; }
.orb:hover .orb-tooltip { opacity: 1; }
.orb-tooltip-name { font-weight: 600; color: var(--text); }
.orb-tooltip-title { color: var(--muted); font-size: 11px; margin-top: 2px; }
```
Replace with:
```css
/* ── Worker Cards ──────────────────────────────────────────────── */
#workers-wrap { position: fixed; inset: 0; pointer-events: none; z-index: 25; }
.worker-card { position: absolute; pointer-events: all; background: var(--bg-card); border: 1.5px solid var(--border); border-radius: 18px; padding: 8px 10px; display: flex; flex-direction: column; gap: 0; user-select: none; transition: border-color .2s, box-shadow .2s; min-width: 110px; max-width: 220px; }
.worker-card.selected { border-color: var(--agent-color, var(--cyan)); box-shadow: 0 0 14px var(--agent-color, var(--cyan)); }
.worker-card.working { border-color: var(--agent-color, var(--cyan)); box-shadow: 0 0 14px var(--agent-color, var(--cyan)); animation: wcard-pulse 1.5s ease-in-out infinite; }
@keyframes wcard-pulse { 0%,100% { box-shadow: 0 0 6px var(--agent-color, var(--cyan)); } 50% { box-shadow: 0 0 22px var(--agent-color, var(--cyan)); } }
.wcard-handle { display: flex; align-items: center; gap: 8px; cursor: grab; padding-bottom: 0; }
.wcard-handle:active { cursor: grabbing; }
.wcard-avatar { width: 28px; height: 28px; border-radius: 50%; background: var(--bg-elevated); border: 1.5px solid var(--agent-color, var(--border)); display: flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 700; color: var(--agent-color, var(--muted)); flex-shrink: 0; }
.wcard-name { font-size: 11px; font-weight: 600; color: var(--text); line-height: 1.3; }
.wcard-role { font-size: 10px; color: var(--muted); line-height: 1.3; }
.wcard-status { margin-top: 6px; padding-top: 5px; border-top: 1px solid var(--border); display: flex; flex-direction: column; gap: 2px; }
.wcard-action { font-size: 11px; color: var(--cyan); font-family: var(--font-code); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 190px; }
.wcard-action.wcard-done { color: var(--green); }
.wcard-timer { font-size: 10px; color: var(--muted); font-family: var(--font-code); }
```

- [ ] **Step 2: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/static/style-v5.css
git commit -m "style: replace orb CSS with floating worker card styles"
```

---

## Task 3: Worker Cards — HTML + JS

**Files:**
- Modify: `app/static/index.html:49`
- Modify: `app/static/app-v5.js:3-7` (state object)
- Modify: `app/static/app-v5.js:52-86` (replace orb section)
- Modify: `app/static/app-v5.js:384-436` (dispatch handlers)
- Modify: `app/static/app-v5.js:795-806` (init)

- [ ] **Step 1: Replace orbs-wrap with workers-wrap in HTML**

In `app/static/index.html`, find:
```html
<!-- ── Agent Orbs ──────────────────────────────────────────────────── -->
<div class="orbs-wrap" id="orbs-wrap"></div>
```
Replace with:
```html
<!-- ── Worker Cards ────────────────────────────────────────────────── -->
<div id="workers-wrap"></div>
```

- [ ] **Step 2: Add workerStatuses to the S state object**

In `app/static/app-v5.js`, find the state object at line 3:
```javascript
const S = {
  ws: null, agents: {}, agentOrder: [], activeAgent: "ceo",
  backend: "claude", chatLogs: {}, statuses: {},
  workQueue: [], attachments: [], reconnTimer: null, skills: [],
};
```
Replace with:
```javascript
const S = {
  ws: null, agents: {}, agentOrder: [], activeAgent: "ceo",
  backend: "claude", chatLogs: {}, statuses: {},
  workQueue: [], attachments: [], reconnTimer: null, skills: [],
  workerStatuses: {},
};
```

- [ ] **Step 3: Replace renderOrbs + setOrbState + switchAgent with worker card functions**

In `app/static/app-v5.js`, find the entire Agent Orbs section (lines 52–86):
```javascript
// ── Agent Orbs ─────────────────────────────────────────────────────
function renderOrbs() {
  const wrap = $id("orbs-wrap");
  wrap.innerHTML = "";
  S.agentOrder.forEach(id => {
    const a = S.agents[id];
    const orb = document.createElement("div");
    orb.className = "orb" + (id === S.activeAgent ? " active" : "");
    orb.id = `orb-${id}`;
    orb.style.setProperty("--agent-color", a.color);
    orb.innerHTML = `${escHtml(a.avatar || id.slice(0,2).toUpperCase())}
      <div class="orb-tooltip">
        <div class="orb-tooltip-name">${escHtml(a.name)}</div>
        <div class="orb-tooltip-title">${escHtml(a.title)}</div>
      </div>`;
    orb.onclick = () => switchAgent(id);
    wrap.appendChild(orb);
  });
}

function setOrbState(agentId, state) {
  const orb = $id(`orb-${agentId}`);
  if (!orb) return;
  orb.classList.remove("thinking", "active");
  if (state === "thinking") orb.classList.add("thinking");
  if (agentId === S.activeAgent || state === "thinking") orb.classList.add("active");
}

function switchAgent(id) {
  S.activeAgent = id;
  const a = S.agents[id];
  $id("cmdbar-badge").textContent = a?.avatar || id.slice(0,3).toUpperCase();
  renderOrbs();
  renderChat();
}
```
Replace with:
```javascript
// ── Worker Cards ───────────────────────────────────────────────────
const WORKER_ORBITAL = {
  ceo:      { left: "46%", top: "12%" },
  backend:  { left: "76%", top: "35%" },
  frontend: { left: "65%", top: "68%" },
  qa:       { left: "28%", top: "68%" },
  devops:   { left: "18%", top: "35%" },
};

function renderWorkerCards() {
  const wrap  = $id("workers-wrap");
  wrap.innerHTML = "";
  const saved = JSON.parse(localStorage.getItem("workerPositions") || "{}");
  S.agentOrder.forEach(id => {
    const a   = S.agents[id];
    const pos = saved[id] || WORKER_ORBITAL[id] || { left: "50%", top: "50%" };
    const card = document.createElement("div");
    card.className = "worker-card" + (id === S.activeAgent ? " selected" : "");
    card.id = `wcard-${id}`;
    card.style.setProperty("--agent-color", a.color);
    card.style.left = pos.left;
    card.style.top  = pos.top;
    card.innerHTML = `
      <div class="wcard-handle" id="wcard-handle-${id}">
        <div class="wcard-avatar">${escHtml(a.avatar || id.slice(0,2).toUpperCase())}</div>
        <div class="wcard-info">
          <div class="wcard-name">${escHtml(a.name)}</div>
          <div class="wcard-role">${escHtml(a.title)}</div>
        </div>
      </div>
      <div class="wcard-status" id="wcard-status-${id}" style="display:none">
        <div class="wcard-action" id="wcard-action-${id}">—</div>
        <div class="wcard-timer"  id="wcard-timer-${id}">0:00</div>
      </div>`;
    initWorkerDrag(id, card);
    wrap.appendChild(card);
  });
}

function initWorkerDrag(agentId, card) {
  const handle = card.querySelector(".wcard-handle");
  handle.addEventListener("mousedown", e => {
    if (e.button !== 0) return;
    e.preventDefault();
    let moved    = false;
    const startX = e.clientX, startY = e.clientY;
    // Convert % positions to px for drag math
    const rect   = card.getBoundingClientRect();
    card.style.left = rect.left + "px";
    card.style.top  = rect.top  + "px";
    const startL = rect.left, startT = rect.top;

    const onMove = e2 => {
      const dx = e2.clientX - startX, dy = e2.clientY - startY;
      if (Math.abs(dx) > 4 || Math.abs(dy) > 4) moved = true;
      if (moved) {
        card.style.left = (startL + dx) + "px";
        card.style.top  = (startT + dy) + "px";
      }
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup",   onUp);
      if (!moved) {
        switchAgent(agentId);
      } else {
        const positions = JSON.parse(localStorage.getItem("workerPositions") || "{}");
        positions[agentId] = { left: card.style.left, top: card.style.top };
        localStorage.setItem("workerPositions", JSON.stringify(positions));
      }
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup",   onUp);
  });
}

function setWorkerState(agentId, state, action = "") {
  const card     = $id(`wcard-${agentId}`);
  const statusEl = $id(`wcard-status-${agentId}`);
  const actionEl = $id(`wcard-action-${agentId}`);
  const timerEl  = $id(`wcard-timer-${agentId}`);
  if (!card) return;

  card.classList.remove("working");

  if (state === "working") {
    card.classList.add("working");
    if (actionEl) actionEl.textContent = action || "Working…";
    if (actionEl) actionEl.className = "wcard-action";
    if (statusEl) statusEl.style.display = "block";
    if (!S.workerStatuses[agentId]) {
      S.workerStatuses[agentId] = { startTime: Date.now() };
      S.workerStatuses[agentId].interval = setInterval(() => {
        const secs = Math.floor((Date.now() - S.workerStatuses[agentId].startTime) / 1000);
        if (timerEl) timerEl.textContent = `${Math.floor(secs/60)}:${String(secs%60).padStart(2,"0")}`;
      }, 1000);
    } else if (action) {
      if (actionEl) actionEl.textContent = action;
    }

  } else if (state === "done") {
    if (S.workerStatuses[agentId]?.interval) clearInterval(S.workerStatuses[agentId].interval);
    delete S.workerStatuses[agentId];
    if (actionEl) { actionEl.textContent = "✓ Done"; actionEl.className = "wcard-action wcard-done"; }
    if (statusEl) statusEl.style.display = "block";
    setTimeout(() => {
      if (statusEl) statusEl.style.display = "none";
      if (actionEl) actionEl.className = "wcard-action";
    }, 1800);

  } else {
    if (S.workerStatuses[agentId]?.interval) clearInterval(S.workerStatuses[agentId].interval);
    delete S.workerStatuses[agentId];
    if (statusEl) statusEl.style.display = "none";
  }
}

function switchAgent(id) {
  S.activeAgent = id;
  const a = S.agents[id];
  $id("cmdbar-badge").textContent = a?.avatar || id.slice(0,3).toUpperCase();
  S.agentOrder.forEach(aid => {
    const card = $id(`wcard-${aid}`);
    if (card) card.classList.toggle("selected", aid === id);
  });
  renderChat();
}
```

- [ ] **Step 4: Update dispatch() — replace orb calls with worker card calls**

In `app/static/app-v5.js`, find these lines inside `dispatch()`:

```javascript
    case "thinking":
      setOrbState(agentId, "thinking");
      setReactorState("thinking");
      addThinkingStep(`${S.agents[agentId]?.name || agentId} thinking…`);
      break;
```
Replace with:
```javascript
    case "thinking":
      setWorkerState(agentId, "working", "Thinking…");
      setReactorState("thinking");
      addThinkingStep(`${S.agents[agentId]?.name || agentId} thinking…`);
      break;
```

Find:
```javascript
    case "tool_call":
      if (obj.tool === "ask_agent") {
        addThinkingStep(`↔ Asking ${obj.path || "agent"}…`, "active");
      } else {
        addThinkingStep(`${obj.label || obj.tool}: ${obj.path || ""}`, "active");
      }
      break;
```
Replace with:
```javascript
    case "tool_call": {
      const toolLabel = obj.tool === "ask_agent"
        ? `↔ ${obj.path || "agent"}`
        : `${obj.label || obj.tool}${obj.path ? ": " + obj.path : ""}`;
      setWorkerState(agentId, "working", toolLabel);
      if (obj.tool === "ask_agent") {
        addThinkingStep(`↔ Asking ${obj.path || "agent"}…`, "active");
      } else {
        addThinkingStep(`${obj.label || obj.tool}: ${obj.path || ""}`, "active");
      }
      break;
    }
```

Find:
```javascript
    case "done":
    case "worker_done": {
      setOrbState(agentId, "idle");
      setReactorState("idle");
```
Replace with:
```javascript
    case "done":
    case "worker_done": {
      setWorkerState(agentId, "done");
      setReactorState("idle");
```

Find `renderOrbs();` inside the `state_sync` case:
```javascript
      renderOrbs();
      updateQueuePill();
```
Replace with:
```javascript
      renderWorkerCards();
      updateQueuePill();
```

- [ ] **Step 5: Verify Python tests still pass**

```bash
cd /home/subaru/projects/virtual-company && python -m pytest tests/ -q
```
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/static/index.html app/static/app-v5.js
git commit -m "feat: floating draggable worker cards with live task status"
```

---

## Task 4: Integration Smoke Test

No automated JS tests exist for the frontend. Verify manually:

- [ ] **Step 1: Check app is running**

```bash
curl -s http://localhost:3030/ | grep -o "<title>[^<]*</title>"
```
Expected output: `<title>Subaru</title>`

If not running, the container may need restarting — that's outside this task's scope; report to user.

- [ ] **Step 2: Verify worker cards appear**

Open browser at `http://localhost:3030`. You should see 5 floating worker cards in orbital positions (top-center, right, bottom-right, bottom-left, left) instead of the old bottom orb row.

- [ ] **Step 3: Verify drag and persistence**

Drag the CEO card to a new position. Refresh the page. The CEO card should appear at the dragged position (saved in `localStorage["workerPositions"]`).

- [ ] **Step 4: Verify voice button**

Click the 🎤 button in the command bar (right side of the text input). It should show a browser microphone permission prompt or a notification "Voice off" / "Say Hey Subaru to activate". Previously this did nothing.

- [ ] **Step 5: Final Python test run**

```bash
cd /home/subaru/projects/virtual-company && python -m pytest tests/ -q
```
Expected: all tests pass (55/55).

- [ ] **Step 6: Final commit**

```bash
cd /home/subaru/projects/virtual-company
git add docs/
git commit -m "docs: add floating workers + voice spec and plan"
```
