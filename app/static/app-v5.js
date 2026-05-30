/* ── Subaru Command Center — app-v5.js ─────────────────────────── */

const S = {
  ws: null, agents: {}, agentOrder: [], activeAgent: "ceo",
  backend: "claude", chatLogs: {}, statuses: {},
  workQueue: [], attachments: [], reconnTimer: null, skills: [],
};

const $  = sel => document.querySelector(sel);
const $$ = sel => document.querySelectorAll(sel);
const $id = id => document.getElementById(id);

function escHtml(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

function fmtMd(text) {
  return text
    .replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => `<pre><code>${escHtml(code)}</code></pre>`)
    .replace(/`([^`]+)`/g, (_, c) => `<code>${escHtml(c)}</code>`)
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>');
}

// ── Notifications ──────────────────────────────────────────────────
function pushNotif(text, type = "success") {
  const list = $id("notif-list");
  const item = document.createElement("div");
  item.className = `notif-item ${type}`;
  item.innerHTML = `<span class="notif-dot">●</span><span class="notif-text">${escHtml(text)}</span>`;
  list.prepend(item);
  $id("notif-island").style.display = "block";
  setTimeout(() => { item.remove(); if (!list.children.length) $id("notif-island").style.display = "none"; }, 8000);
}

function toggleNotif() {
  const el = $id("notif-island");
  el.style.display = el.style.display === "none" ? "block" : "none";
}

// ── Arc Reactor ────────────────────────────────────────────────────
function setReactorState(state) {
  document.body.classList.remove("thinking", "error");
  if (state !== "idle") document.body.classList.add(state);
}

function showChatMode() {
  $id("reactor-wrap").classList.add("active");
  $id("chat-main").style.display = "block";
}

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

// ── Backend Pill ────────────────────────────────────────────────────
function updateBackendPill(b) {
  S.backend = b.backend || "claude";
  const labels = { claude: "Claude Sonnet", gemini: "Gemini Flash", tgpt: "tgpt Fallback" };
  const colors = { claude: "var(--green)", gemini: "var(--cyan)", tgpt: "var(--warn)" };
  $id("backend-label").textContent = labels[S.backend] || S.backend;
  $id("backend-dot").style.color   = colors[S.backend] || "var(--muted)";
  $id("backend-pill").style.color  = colors[S.backend] || "var(--muted)";
  if (S.backend !== "claude") pushNotif(`Switched to ${labels[S.backend]}`, S.backend === "tgpt" ? "warn" : "success");
}

// ── Skills Panel ────────────────────────────────────────────────────
async function loadSkills() {
  try {
    const d = await fetch("/api/skills").then(r => r.json());
    S.skills = d.tools || [];
    $id("skills-count").textContent = S.skills.length;
    $id("stat-skills").textContent  = S.skills.length;

    const coreEl    = $id("skills-core");
    const learnedEl = $id("skills-learned");
    coreEl.innerHTML = "";

    S.skills.filter(t => t.zone === "core").forEach(t => {
      const chip = document.createElement("div");
      chip.className = "skill-chip tool";
      chip.textContent = t.name;
      chip.title = t.description;
      coreEl.appendChild(chip);
    });

    const installBtn = learnedEl.querySelector(".install");
    (d.learned || []).forEach(m => {
      if (learnedEl.querySelector(`[data-skill="${m.id}"]`)) return;
      const chip = document.createElement("div");
      chip.className = "skill-chip learned";
      chip.textContent = `${m.name} v${m.active_version}`;
      chip.title = m.description;
      chip.dataset.skill = m.id;
      learnedEl.insertBefore(chip, installBtn);
    });
  } catch(e) { console.error("loadSkills:", e); }
}

function toggleSkillsPanel() {
  const p = $id("skills-panel");
  const showing = p.style.display !== "none";
  p.style.display = showing ? "none" : "block";
  if (!showing) loadSkills();
}

function triggerInstallSkill() {
  const name = prompt("Skill name to install (e.g. 'stripe_payments'):");
  if (!name) return;
  sendMsgText(`Learn and install a new skill called "${name}". Research the API or capability, write the skill module with tests, and register it.`);
  toggleSkillsPanel();
}

// ── Command Palette ─────────────────────────────────────────────────
const PALETTE_CMDS = [
  { icon:"💬", label:"Ask CEO",             action: () => switchAgent("ceo") },
  { icon:"🎨", label:"Open Design Preview", action: () => showIsland("design") },
  { icon:"✏",  label:"Ask Emilia to Design", action: () => {
    const what = prompt("What should Emilia design?");
    if (what) { switchAgent("frontend"); sendMsgText(`Design: ${what}`); showIsland("design"); }
  }},
  { icon:"🌐", label:"Open Browser Panel",  action: () => showIsland("browser") },
  { icon:"🔊", label:"Toggle TTS (voice responses)", action: () => {
    _ttsEnabled = !_ttsEnabled;
    pushNotif(`TTS ${_ttsEnabled ? "on" : "off"}`, _ttsEnabled ? "success" : "warn");
  }},
  { icon:"🔄", label:"Show Routines",        action: toggleRoutinesPanel },
  { icon:"▶",  label:"Run Morning Standup",  action: () => fetch("/api/routines/morning_standup/run", {method:"POST"}).then(()=>pushNotif("Standup triggered")) },
  { icon:"🧠", label:"Show Skills Panel",   action: toggleSkillsPanel },
  { icon:"💾", label:"Export Chat",          action: exportChat },
  { icon:"🔍", label:"Search Memory",        action: () => { const q=prompt("Search memory:"); if(q) sendMsgText(`Search your memory for: ${q}`); closePalette(null); } },
  { icon:"🗑", label:"Clear Chat",           action: () => { if(confirm("Clear this chat?")) clearChat(); } },
];
let paletteIdx = 0;

function togglePalette() {
  const o = $id("palette-overlay");
  if (o.style.display !== "none") { closePalette(null); return; }
  o.style.display = "flex";
  $id("palette-input").value = "";
  paletteIdx = 0;
  renderPaletteResults("");
  requestAnimationFrame(() => $id("palette-input").focus());
}

function closePalette(e) {
  if (e && e.target !== $id("palette-overlay")) return;
  $id("palette-overlay").style.display = "none";
}

function renderPaletteResults(query) {
  const q = query.toLowerCase();
  const list = PALETTE_CMDS.filter(c => !q || c.label.toLowerCase().includes(q));
  $id("palette-results").innerHTML = list.map((c,i) =>
    `<div class="palette-item${i===paletteIdx?" selected":""}" onclick="runPaletteCmd(${PALETTE_CMDS.indexOf(c)})">
      <span class="palette-item-icon">${c.icon}</span>${escHtml(c.label)}
    </div>`
  ).join("");
}

function runPaletteCmd(idx) {
  $id("palette-overlay").style.display = "none";
  PALETTE_CMDS[idx]?.action?.();
}

// ── Thinking Layer ──────────────────────────────────────────────────
function addThinkingStep(text, state = "active") {
  const steps = $id("thinking-steps");
  $id("thinking-layer").style.display = "block";
  const el = document.createElement("div");
  el.className = `thinking-step ${state}`;
  el.innerHTML = `<span class="thinking-step-icon">${state==="done"?"✓":"→"}</span>${escHtml(text)}`;
  steps.appendChild(el);
  if (steps.children.length > 8) steps.removeChild(steps.firstChild);
}

function clearThinking() {
  $id("thinking-steps").innerHTML = "";
  $id("thinking-layer").style.display = "none";
}

// ── Chat ────────────────────────────────────────────────────────────
function renderChat() {
  const thread = $id("chat-thread");
  const logs   = S.chatLogs[S.activeAgent] || [];
  thread.innerHTML = "";
  const agent  = S.agents[S.activeAgent] || {};
  logs.forEach(m => {
    const isUser = m.role === "user";
    const div    = document.createElement("div");
    div.className = `msg ${isUser ? "user" : "agent"}`;
    div.innerHTML = `
      <div class="msg-header">
        <div class="msg-avatar" style="background:${isUser?"var(--bg-elevated)":agent.color||"var(--cyan)"}">${isUser?"ME":escHtml(agent.avatar||"AI")}</div>
        <span>${isUser?"You":escHtml(agent.name||S.activeAgent)}</span>
      </div>
      <div class="msg-body">
        ${(m.images||[]).map(img => `<img class="chat-image-thumb" src="data:${escHtml(img.media_type)};base64,${img.data}" alt="attached image">`).join("")}
        ${fmtMd(m.content||"")}
      </div>`;
    thread.appendChild(div);
  });
  thread.scrollTop = thread.scrollHeight;
  if (logs.length > 0) showChatMode();
}

function appendMsg(agentId, role, content, images) {
  if (!S.chatLogs[agentId]) S.chatLogs[agentId] = [];
  S.chatLogs[agentId].push({ role, content, images: images || [] });
  if (agentId === S.activeAgent) renderChat();
}

// ── Attachments ─────────────────────────────────────────────────────
function initFileInput() {
  $id("file-input").addEventListener("change", async e => {
    const strip = $id("attach-strip");
    for (const file of e.target.files) {
      const reader = new FileReader();
      reader.onload = re => {
        const dataUrl = re.target.result;
        const base64  = dataUrl.split(",")[1];
        S.attachments.push({ name: file.name, type: file.type, dataUrl, base64 });
        if (file.type.startsWith("image/")) {
          strip.innerHTML += `<img class="attach-thumb" src="${dataUrl}" title="${escHtml(file.name)}">`;
        } else {
          strip.innerHTML += `<div class="skill-chip tool">📄 ${escHtml(file.name)}</div>`;
        }
        strip.style.display = "flex";
      };
      reader.readAsDataURL(file);
    }
  });
  document.body.addEventListener("dragover", e => e.preventDefault());
  document.body.addEventListener("drop", e => {
    e.preventDefault();
    const input = $id("file-input");
    input.files = e.dataTransfer.files;
    input.dispatchEvent(new Event("change"));
  });
}

// ── Send ─────────────────────────────────────────────────────────────
function sendMsg() {
  const input = $id("msg-input");
  const text  = input.value.trim();
  if (!text && S.attachments.length === 0) return;
  sendMsgText(text);
  input.value = "";
  input.style.height = "auto";
  S.attachments = [];
  $id("attach-strip").style.display = "none";
  $id("attach-strip").innerHTML = "";
  $id("file-input").value = "";
}

function sendMsgText(text) {
  if (!S.ws || S.ws.readyState !== WebSocket.OPEN) { pushNotif("Not connected","error"); return; }
  const payload = { type: "message", agent: S.activeAgent, text };
  if (S.attachments.length > 0)
    payload.attachments = S.attachments.map(a => ({ media_type: a.type, data: a.base64, name: a.name }));
  S.ws.send(JSON.stringify(payload));
  const imageAttachments = S.attachments.filter(a => a.type.startsWith("image/"));
  appendMsg(S.activeAgent, "user", text, imageAttachments);
  showChatMode();
  setReactorState("thinking");
}

function clearChat() {
  if (S.ws) S.ws.send(JSON.stringify({ type: "clear", agent: S.activeAgent }));
}

function exportChat() {
  const txt = (S.chatLogs[S.activeAgent] || []).map(m => `[${m.role}] ${m.content}`).join("\n\n");
  const a   = document.createElement("a");
  a.href     = URL.createObjectURL(new Blob([txt], {type:"text/plain"}));
  a.download = `subaru-chat-${S.activeAgent}-${Date.now()}.txt`;
  a.click();
}

// ── Floating Islands ─────────────────────────────────────────────────
function showIsland(name) {
  $id(`island-${name}`).style.display = "block";
  if (name === "design") {
    const iframe = $id("design-iframe");
    if (!iframe.src || iframe.src === location.origin + "/") iframe.src = "/static/previews/index.html";
  }
  if (name === "browser") startBrowserAutoRefresh();
}

function hideIsland(name) {
  $id(`island-${name}`).style.display = "none";
  if (name === "browser") stopBrowserAutoRefresh();
}

function initDraggableIslands() {
  $$(".island").forEach(island => {
    const header = island.querySelector(".island-header");
    if (!header) return;
    let ox=0, oy=0, mx=0, my=0;
    header.onmousedown = e => {
      e.preventDefault();
      mx = e.clientX; my = e.clientY;
      document.onmousemove = e2 => {
        ox = mx - e2.clientX; oy = my - e2.clientY;
        mx = e2.clientX;      my = e2.clientY;
        island.style.top  = (island.offsetTop  - oy) + "px";
        island.style.left = (island.offsetLeft - ox) + "px";
      };
      document.onmouseup = () => { document.onmousemove = null; document.onmouseup = null; };
    };
  });
}

// ── Queue Pill ───────────────────────────────────────────────────────
function updateQueuePill() {
  const active = (S.workQueue || []).filter(i => i.status === "running" || i.status === "pending").length;
  $id("queue-pill").style.display = active > 0 ? "inline-flex" : "none";
  $id("queue-count").textContent  = active;
  $id("stat-tasks").textContent   = active;
  $id("stat-agents").textContent  = S.agentOrder.length;
}

// ── WebSocket ─────────────────────────────────────────────────────────
function boot() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  S.ws = new WebSocket(`${proto}//${location.host}/ws`);
  S.ws.onopen  = () => { clearTimeout(S.reconnTimer); pushNotif("Subaru online", "success"); };
  S.ws.onmessage = ({ data }) => { try { dispatch(JSON.parse(data)); } catch(e) { console.error("dispatch error:", e); } };
  S.ws.onclose   = () => { pushNotif("Reconnecting…", "warn"); S.reconnTimer = setTimeout(boot, 3000); };
}

function dispatch(obj) {
  const type    = obj.type;
  const agentId = obj.agent || "ceo";

  switch (type) {
    case "init":
      S.agents     = obj.agents || {};
      S.agentOrder = Object.keys(S.agents);
      S.workQueue  = obj.work_queue || [];
      S.agentOrder.forEach(id => { if (!S.chatLogs[id]) S.chatLogs[id] = []; });
      if (obj.skills) { S.skills = obj.skills; $id("skills-count").textContent = S.skills.length; }
      if (obj.backend) updateBackendPill(obj.backend);
      renderOrbs();
      updateQueuePill();
      break;

    case "thinking":
      setOrbState(agentId, "thinking");
      setReactorState("thinking");
      addThinkingStep(`${S.agents[agentId]?.name || agentId} thinking…`);
      break;

    case "assistant":
      (obj.message?.content || []).forEach(b => { if (b.type === "text" && b.text) appendMsg(agentId, "assistant", b.text); });
      break;

    case "tool_call":
      addThinkingStep(`${obj.label || obj.tool}: ${obj.path || ""}`, "active");
      break;

    case "done":
    case "worker_done": {
      setOrbState(agentId, "idle");
      setReactorState("idle");
      clearThinking();
      if (obj.summary) appendMsg(agentId, "assistant", `✓ ${obj.summary}`);
      const agentLogs = S.chatLogs[agentId] || [];
      const lastMsg   = [...agentLogs].reverse().find(m => m.role === "assistant");
      if (lastMsg) speakResponse(lastMsg.content, agentId);
      break;
    }

    case "backend_switch":
    case "backend_status":
      updateBackendPill(obj);
      break;

    case "skill_installed":
      pushNotif(`Skill installed: ${obj.skill_name || "new"}`, "success");
      loadSkills();
      break;

    case "delegation":
      pushNotif(`Delegated → ${obj.item?.agent}: ${(obj.item?.task||"").slice(0,50)}…`);
      break;

    case "queue_update":
      S.workQueue = obj.work_queue || [];
      updateQueuePill();
      break;

    case "failover":
      pushNotif(obj.message || "Backend switched", "warn");
      break;

    case "error":
      setReactorState("idle");
      clearThinking();
      pushNotif(obj.message || "Error", "error");
      break;

    case "email_sent":
      pushNotif(`Email: ${obj.subject}`, obj.ok ? "success" : "error");
      break;

    case "routine_completed":
      pushNotif(
        `${obj.routine_id}: ${obj.status === "success" ? "✓" : "✗"} ${(obj.output||"").slice(0,50)}`,
        obj.status === "success" ? "success" : "error"
      );
      if ($id("routines-panel") && $id("routines-panel").style.display !== "none") loadRoutines();
      break;

    case "standup":
      appendMsg("ceo", "assistant", `📋 **Morning Briefing**\n\n${obj.content || ""}`);
      pushNotif("Morning standup delivered", "success");
      break;

    case "design_preview_updated": {
      const iframe = $id("design-iframe");
      if (iframe && iframe.src && iframe.src !== location.origin + "/") {
        iframe.src = iframe.src;   // force reload
      }
      pushNotif("Design preview updated ✓", "success");
      break;
    }

    case "cleared":
      S.chatLogs[agentId] = [];
      if (agentId === S.activeAgent) renderChat();
      break;

    case "browser_navigated":
      browserRefreshScreenshot();
      if ($id("browser-url-input") && obj.url) $id("browser-url-input").value = obj.url;
      if ($id("browser-status")) $id("browser-status").textContent = `✓ ${obj.title || obj.url}`;
      break;
  }
}

// ── Routines Panel ──────────────────────────────────────────────────────────
let _routines = [];

async function loadRoutines() {
  try {
    _routines = await fetch("/api/routines").then(r => r.json());
    renderRoutines();
    const pill = $id("routines-pill");
    if (pill) {
      pill.style.display = "inline-flex";
      $id("routines-active-count").textContent = _routines.filter(r => r.enabled).length;
    }
  } catch(e) { console.error("loadRoutines:", e); }
}

function renderRoutines() {
  const list = $id("routines-list");
  if (!list) return;
  list.innerHTML = "";
  if (_routines.length === 0) {
    list.innerHTML = '<div style="color:var(--muted);font-size:12px;text-align:center;padding:20px">No routines yet. Click ➕ New to create one.</div>';
    return;
  }
  _routines.forEach(r => {
    const statusLabel = r.last_status || "never run";
    const statusClass = r.last_status === "success" ? "success" : r.last_status === "error" ? "error" : "pending";
    const lastRun     = r.last_run ? new Date(r.last_run).toLocaleString("en-IN", {timeZone:"Asia/Kolkata", hour12:false}).slice(0,16) : "—";
    const card        = document.createElement("div");
    card.className    = "routine-card";
    card.innerHTML    = `
      <div class="routine-card-header">
        <span class="routine-name">${escHtml(r.name)}</span>
        <span class="routine-status ${statusClass}">${escHtml(statusLabel)}</span>
      </div>
      <div class="routine-meta">
        ${escHtml(r.agent)} · ${escHtml(r.schedule)} · ${escHtml(r.timezone || "IST")} · Last: ${lastRun}
      </div>
      <div class="routine-actions">
        <button class="routine-toggle ${r.enabled ? 'on' : ''}" onclick="toggleRoutine('${escHtml(r.id)}', this)" title="${r.enabled ? 'Enabled' : 'Disabled'}"></button>
        <button class="btn-run" onclick="runRoutineNow('${escHtml(r.id)}')">▶ Run</button>
        <span style="flex:1"></span>
        <button class="cmdbar-btn" onclick="deleteRoutine('${escHtml(r.id)}')" style="font-size:12px" title="Delete">🗑</button>
      </div>`;
    list.appendChild(card);
  });
}

function toggleRoutinesPanel() {
  const p = $id("routines-panel");
  const skills = $id("skills-panel");
  if (skills) skills.style.display = "none";
  const showing = p.style.display !== "none";
  p.style.display = showing ? "none" : "block";
  if (!showing) loadRoutines();
}

async function toggleRoutine(id, btn) {
  const routine = _routines.find(r => r.id === id);
  if (!routine) return;
  const newEnabled = !routine.enabled;
  await fetch(`/api/routines/${id}`, {
    method: "PUT",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ enabled: newEnabled }),
  });
  routine.enabled = newEnabled;
  renderRoutines();
}

async function runRoutineNow(id) {
  pushNotif(`Running routine '${id}'...`);
  const r = await fetch(`/api/routines/${id}/run`, {method:"POST"}).then(r=>r.json());
  if (!r.ok) pushNotif(`Failed: ${r.error}`, "error");
}

async function deleteRoutine(id) {
  if (!confirm(`Delete routine '${id}'?`)) return;
  await fetch(`/api/routines/${id}`, {method:"DELETE"});
  await loadRoutines();
}

function showCreateRoutine() {
  const id       = prompt("Routine ID (letters/numbers/underscore/hyphen):");
  if (!id) return;
  const name     = prompt("Display name:");
  if (!name) return;
  const schedule = prompt("Cron schedule (e.g. '0 9 * * *' for 9 AM daily):", "0 9 * * *");
  if (!schedule) return;
  const routinePrompt = prompt("Agent prompt:");
  if (!routinePrompt) return;
  const agent    = prompt("Agent (ceo/backend/frontend/qa):", "ceo");

  fetch("/api/routines", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ id, name, schedule, prompt: routinePrompt, agent }),
  }).then(r => r.json()).then(d => {
    if (d.ok) { loadRoutines(); pushNotif(`Routine '${name}' created`, "success"); }
    else pushNotif(`Error: ${d.error}`, "error");
  });
}

// ── Browser Island ──────────────────────────────────────────────────────────
let _browserRefreshInterval = null;

async function browserNavigate() {
  const input  = $id("browser-url-input");
  const url    = input ? input.value.trim() : "";
  if (!url) return;

  const status = $id("browser-status");
  if (status) status.textContent = "Navigating…";

  try {
    const r = await fetch("/api/browser/navigate", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ url }),
    }).then(r => r.json());

    if (r.ok) {
      if (status) status.textContent = `✓ ${r.title || url}`;
      browserRefreshScreenshot();
    } else {
      if (status) status.textContent = `✗ ${r.error || "Navigation failed"}`;
    }
  } catch(e) {
    if (status) status.textContent = `✗ ${e.message}`;
  }
}

function browserRefreshScreenshot() {
  const img = $id("browser-screenshot");
  if (!img) return;
  img.src = `/static/previews/browser_screenshot.png?t=${Date.now()}`;
}

function startBrowserAutoRefresh() {
  if (_browserRefreshInterval) return;
  _browserRefreshInterval = setInterval(browserRefreshScreenshot, 2000);
}

function stopBrowserAutoRefresh() {
  if (_browserRefreshInterval) {
    clearInterval(_browserRefreshInterval);
    _browserRefreshInterval = null;
  }
}

// ── Voice Engine ────────────────────────────────────────────────────────────

const AGENT_VOICES = {
  ceo:      { lang: "en-GB", pitch: 0.9, rate: 0.95 },
  frontend: { lang: "en-US", pitch: 1.1, rate: 1.0  },
  backend:  { lang: "en-US", pitch: 0.7, rate: 0.85 },
  qa:       { lang: "en-US", pitch: 1.0, rate: 0.9  },
  devops:   { lang: "en-US", pitch: 0.8, rate: 0.9  },
};

let _recognition  = null;
let _voiceEnabled = false;
let _voiceActive  = false;
let _ttsEnabled   = true;

function initVoiceRecognition() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    pushNotif("Speech recognition not supported in this browser", "warn");
    return false;
  }
  _recognition = new SR();
  _recognition.continuous     = true;
  _recognition.interimResults = true;
  _recognition.lang           = "en-US";

  _recognition.onresult = (event) => {
    const transcript = Array.from(event.results)
      .map(r => r[0].transcript).join("").toLowerCase().trim();

    if (!_voiceActive && transcript.includes("hey subaru")) {
      _voiceActive = true;
      const vb = $id("voice-btn");
      if (vb) vb.style.color = "var(--cyan)";
      pushNotif("🎤 Listening for command…", "success");
      setReactorState("thinking");
    }

    if (_voiceActive && event.results[event.results.length - 1].isFinal) {
      const cmd = transcript.replace(/hey subaru/gi, "").trim();
      if (cmd.length > 2) {
        sendMsgText(cmd);
        _voiceActive = false;
        const vb = $id("voice-btn");
        if (vb) vb.style.color = "";
        setReactorState("idle");
      }
    }
  };

  _recognition.onerror = (e) => {
    if (e.error !== "no-speech") pushNotif(`Voice error: ${e.error}`, "warn");
    _voiceActive = false;
    const vb = $id("voice-btn");
    if (vb) vb.style.color = "";
  };

  _recognition.onend = () => {
    if (_voiceEnabled) {
      try { _recognition.start(); } catch(e) {}
    }
  };

  return true;
}

function toggleVoiceMode() {
  const btn = $id("voice-toggle-btn");
  if (_voiceEnabled) {
    _voiceEnabled = false;
    _voiceActive  = false;
    if (_recognition) { try { _recognition.stop(); } catch(e) {} }
    if (btn) btn.style.color = "";
    pushNotif("Voice off", "warn");
  } else {
    if (!_recognition && !initVoiceRecognition()) return;
    _voiceEnabled = true;
    try { _recognition.start(); } catch(e) {}
    if (btn) btn.style.color = "var(--cyan)";
    pushNotif('🎤 Say "Hey Subaru" to activate', "success");
  }
}

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

// ── Keyboard ─────────────────────────────────────────────────────────
document.addEventListener("keydown", e => {
  if ((e.metaKey || e.ctrlKey) && e.key === "k") { e.preventDefault(); togglePalette(); return; }
  if (e.key === "Escape") { closePalette(null); $id("skills-panel").style.display = "none"; return; }
  if ($id("palette-overlay").style.display !== "none") {
    const visible = PALETTE_CMDS.filter(c => {
      const q = $id("palette-input").value.toLowerCase();
      return !q || c.label.toLowerCase().includes(q);
    });
    if (e.key === "ArrowDown") { paletteIdx = Math.min(paletteIdx+1, visible.length-1); renderPaletteResults($id("palette-input").value); }
    if (e.key === "ArrowUp")   { paletteIdx = Math.max(paletteIdx-1, 0); renderPaletteResults($id("palette-input").value); }
    if (e.key === "Enter")     { const items = $$(".palette-item"); if(items[paletteIdx]) items[paletteIdx].click(); }
  }
});

// ── Init ─────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  const inp = $id("msg-input");
  inp.addEventListener("input",   () => { inp.style.height = "auto"; inp.style.height = Math.min(inp.scrollHeight, 120) + "px"; });
  inp.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMsg(); } });
  $id("palette-input").addEventListener("input", e => { paletteIdx = 0; renderPaletteResults(e.target.value); });
  const urlInput = $id("browser-url-input");
  if (urlInput) urlInput.addEventListener("keydown", e => { if (e.key === "Enter") browserNavigate(); });
  initFileInput();
  initDraggableIslands();
  boot();
});
