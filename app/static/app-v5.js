/* ── Subaru Command Center — app-v5.js ─────────────────────────── */

const S = {
  ws: null, agents: {}, agentOrder: [], activeAgent: "ceo",
  backend: "claude", chatLogs: {}, statuses: {},
  workQueue: [], attachments: [], reconnTimer: null, skills: [],
  workerStatuses: {},
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
  if (!wrap) return;
  Object.values(S.workerStatuses).forEach(ws => { if (ws?.interval) clearInterval(ws.interval); });
  S.workerStatuses = {};
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

  if (state !== "working") {
    card.classList.remove("working");
  } else if (!card.classList.contains("working")) {
    card.classList.add("working");
  }

  if (state === "working") {
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
      const s = $id(`wcard-status-${agentId}`);
      const a = $id(`wcard-action-${agentId}`);
      if (s) s.style.display = "none";
      if (a) a.className = "wcard-action";
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
  { icon:"🗜", label:"Compact Conversations",  action: () => {
    fetch("/api/compact", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"})
      .then(r => r.json())
      .then(d => pushNotif(
        d.count > 0
          ? `Compacted ${d.compacted.join(", ")} — old context saved to memory`
          : "Nothing to compact yet",
        d.count > 0 ? "success" : "warn"
      ));
  }},
  { icon:"🗜", label:"Compact This Agent",    action: () => {
    fetch("/api/compact", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({agent: S.activeAgent})})
      .then(r => r.json())
      .then(d => pushNotif(
        d.count > 0
          ? `${S.activeAgent} compacted — old context saved to memory`
          : `${S.activeAgent} history is short, nothing to compact`,
        d.count > 0 ? "success" : "warn"
      ));
  }},
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
  // Fire filler audio immediately while LLM + Bark generate the real response
  if (_ttsEnabled) {
    fetch("/api/filler?context=" + encodeURIComponent(text))
      .then(r => r.json())
      .then(({ audio }) => { if (audio) AudioQueue.push(audio, "filler"); })
      .catch(() => {});
  }
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
  if (name === "board") startBoardStatusPolling();
}

function hideIsland(name) {
  $id(`island-${name}`).style.display = "none";
  if (name === "browser") stopBrowserAutoRefresh();
  if (name === "board") stopBoardStatusPolling();
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
      renderWorkerCards();
      updateQueuePill();
      break;

    case "thinking":
      setWorkerState(agentId, "working", "Thinking…");
      setReactorState("thinking");
      addThinkingStep(`${S.agents[agentId]?.name || agentId} thinking…`);
      break;

    case "audio": {
      if (_ttsEnabled) AudioQueue.push(obj.data, obj.mode || "speak");
      break;
    }

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

    case "done":
    case "worker_done": {
      setWorkerState(agentId, "done");
      setReactorState("idle");
      clearThinking();
      if (obj.summary) appendMsg(agentId, "assistant", `✓ ${obj.summary}`);
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

    case "browser_frame":
      handleBrowserFrame(obj);
      break;

    case "apply_result":
      logApplyResult(obj);
      break;

    case "browser_blocked":
      pushNotif(`🧑‍💻 Slot ${obj.slot_id} needs you — ${obj.description || obj.blocker_type}`, "warn");
      appendMsg("maya", "assistant",
        `⚠️ I'm stuck on slot ${obj.slot_id} — ${obj.description}\n\n` +
        `Open the Browser Board, click **Take over**, resolve it, then click **Resume** so I can continue from where I left off.`
      );
      break;

    case "approval_requested":
      pushNotif(
        `🔐 Approval needed: ${obj.file_path || "file"} (ID: ${obj.approval_id})`,
        "warn"
      );
      appendMsg(obj.agent || "ceo", "assistant",
        `⚠️ I need your approval to modify \`${obj.file_path}\`.\n\n` +
        `**Approval ID:** \`${obj.approval_id}\`\n\n` +
        `Reply: \`APPROVE ${obj.approval_id}\` or \`DENY ${obj.approval_id}\`\n\n` +
        `Or use the API:\n\`POST /api/approvals/${obj.approval_id}/apply\``
      );
      break;

    case "approval_applied":
      pushNotif(`✅ Applied: ${obj.message || obj.approval_id}`, "success");
      appendMsg("ceo", "assistant", `✅ Change applied: ${obj.message}`);
      break;

    case "approval_denied":
      pushNotif(`✗ Denied: ${obj.message || obj.approval_id}`, "warn");
      break;

    case "source_file_modified":
      pushNotif(`🔧 ${obj.agent}: modified ${obj.path} (${obj.zone})`, "success");
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
    this._playing = true;
    const { base64, mode } = this._queue.shift();
    const blob = b64ToBlob(base64, "audio/wav");
    const url  = URL.createObjectURL(blob);
    const el   = new Audio(url);
    if (mode === "sing") showSingingIndicator(true);
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
};

// ── Voice Engine ────────────────────────────────────────────────────────────

const AGENT_VOICES = {
  ceo:      { lang: "en-GB", pitch: 0.90, rate: 0.95 },
  frontend: { lang: "en-US", pitch: 1.10, rate: 1.00 },
  backend:  { lang: "en-US", pitch: 0.70, rate: 0.85 },
  qa:       { lang: "en-US", pitch: 1.00, rate: 0.90 },
  devops:   { lang: "en-US", pitch: 0.80, rate: 0.90 },
};

let _cachedVoices = [];
if (window.speechSynthesis) {
  const _loadVoices = () => { _cachedVoices = window.speechSynthesis.getVoices(); };
  _loadVoices();
  window.speechSynthesis.addEventListener("voiceschanged", _loadVoices);
}

let _recognition  = null;
let _voiceEnabled = false;
let _voiceActive  = false;
let _ttsEnabled   = true;

function _syncVoiceUI() {
  const cyan  = "var(--cyan)";
  const green = "var(--green)";
  const off   = "";
  // Header pill reflects always-on mode; cmdbar btn reflects active listening
  const hdr = $id("voice-toggle-btn");
  const cmd = $id("voice-btn");
  if (hdr) hdr.style.color = _voiceActive ? cyan : _voiceEnabled ? green : off;
  if (cmd) cmd.style.color = _voiceActive ? cyan : off;
}

function initVoiceRecognition() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    pushNotif("Speech recognition not supported in this browser", "warn");
    return false;
  }
  _recognition = new SR();
  _recognition.continuous     = true;
  _recognition.interimResults = false; // final results only — more reliable on Linux Chrome
  _recognition.lang           = "en-US";

  _recognition.onresult = (event) => {
    // Only use the latest result from this session (not accumulated history)
    const result     = event.results[event.results.length - 1];
    const transcript = result[0].transcript.toLowerCase().trim();

    if (!_voiceActive && transcript.includes("hey subaru")) {
      _voiceActive = true;
      _syncVoiceUI();
      pushNotif("🎤 Listening for command…", "success");
      setReactorState("thinking");
      return;
    }

    if (_voiceActive && result.isFinal) {
      const cmd = transcript.replace(/hey subaru/gi, "").trim();
      if (cmd.length > 1) {
        sendMsgText(cmd);
        _voiceActive = false;
        _syncVoiceUI();
        setReactorState("idle");
      }
    }
  };

  _recognition.onerror = (e) => {
    if (e.error === "not-allowed") {
      pushNotif("Microphone access denied — allow mic permission in Chrome", "error");
      _voiceEnabled = false;
    } else if (e.error !== "no-speech") {
      pushNotif(`Voice error: ${e.error}`, "warn");
    }
    _voiceActive = false;
    _syncVoiceUI();
  };

  _recognition.onend = () => {
    if (_voiceEnabled) {
      try { _recognition.start(); } catch(e) {}
    }
  };

  return true;
}

// Header pill: toggle always-on wake-word mode
function toggleVoiceMode() {
  if (_voiceEnabled) {
    _voiceEnabled = false;
    _voiceActive  = false;
    if (_recognition) { try { _recognition.stop(); } catch(e) {} }
    _syncVoiceUI();
    pushNotif("Voice off", "warn");
  } else {
    if (!_recognition && !initVoiceRecognition()) return;
    _voiceEnabled = true;
    try { _recognition.start(); } catch(e) {}
    _syncVoiceUI();
    pushNotif('🎤 Always-on: say "Hey Subaru [command]"', "success");
  }
}

// Cmdbar button: push-to-talk (no wake word needed)
function handleVoiceBtnClick() {
  if (_voiceActive) {
    // Cancel current recording
    _voiceActive = false;
    _syncVoiceUI();
    setReactorState("idle");
    return;
  }
  // Ensure recognition is running
  if (!_recognition && !initVoiceRecognition()) return;
  if (!_voiceEnabled) {
    _voiceEnabled = true;
    try { _recognition.start(); } catch(e) {}
  }
  // Skip wake word — go straight to listening
  _voiceActive = true;
  _syncVoiceUI();
  setReactorState("thinking");
  pushNotif("🎤 Speak now…", "success");
}

// Detect emotional tone from response text for expressive TTS
function detectEmotion(text) {
  const t = text.toLowerCase();
  if (/\b(error|fail|sorry|can't|cannot|unable|problem|broke|wrong|unfortunate)\b/.test(t))
    return { pitchMod: -0.12, rateMod: -0.10 }; // concerned — slower, lower
  if (/[!]|✓|\b(done|success|complet|great|amazing|excellent|perfect|awesome|wonderful)\b/.test(t))
    return { pitchMod:  0.15, rateMod:  0.08 }; // excited — higher, faster
  if (/\b(hmm|let me|consider|perhaps|maybe|might|thinking|wonder|interesting)\b/.test(t))
    return { pitchMod:  0.05, rateMod: -0.07 }; // thoughtful — slightly higher, slower
  if (/\b(warning|careful|caution|critical|urgent|important|note)\b/.test(t))
    return { pitchMod: -0.05, rateMod: -0.05 }; // cautious — slightly lower, slower
  return { pitchMod: 0, rateMod: 0 };
}

function summarizeForSpeech(text) {
  // Strip all markdown formatting
  const plain = text
    .replace(/```[\s\S]*?```/g, "")          // fenced code blocks
    .replace(/`[^`]+`/g, "")                 // inline code
    .replace(/#{1,6}\s+/g, "")              // headings
    .replace(/\*\*([^*]+)\*\*/g, "$1")      // bold
    .replace(/\*([^*]+)\*/g, "$1")          // italic
    .replace(/^\s*[-*+•]\s+/gm, "")         // bullet points
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1") // links → just label
    .replace(/\n+/g, " ")                   // newlines to spaces
    .replace(/\s{2,}/g, " ")               // collapse whitespace
    .trim();

  if (plain.length <= 130) return plain;

  // Take first 2 sentences
  const sentences = plain.match(/[^.!?]+[.!?]+/g) || [];
  if (sentences.length >= 1) {
    const summary = sentences.slice(0, 2).join(" ").trim();
    return summary.length <= 160 ? summary : summary.slice(0, 157) + "…";
  }
  return plain.slice(0, 130) + "…";
}

function speakResponse(text, agentId) {
  if (!_ttsEnabled || !window.speechSynthesis || !text) return;
  speechSynthesis.cancel();

  // Pause recognition while TTS plays — Chrome can't run both simultaneously
  if (_voiceEnabled && _recognition) {
    try { _recognition.stop(); } catch(e) {}
  }

  const spoken  = summarizeForSpeech(text);
  const utter   = new SpeechSynthesisUtterance(spoken);
  const profile = AGENT_VOICES[agentId] || AGENT_VOICES.ceo;
  const emotion = detectEmotion(spoken);
  utter.lang    = profile.lang;
  utter.pitch   = Math.max(0.1, Math.min(2,  profile.pitch + emotion.pitchMod));
  utter.rate    = Math.max(0.5, Math.min(2,  profile.rate  + emotion.rateMod));
  const voices  = _cachedVoices.length ? _cachedVoices : speechSynthesis.getVoices();
  const langPfx = profile.lang.split("-")[0];
  const voice   = voices.find(v => v.lang.startsWith(langPfx) && /google|microsoft/i.test(v.name))
               || voices.find(v => v.lang.startsWith(langPfx));
  if (voice) utter.voice = voice;

  // Restart recognition once TTS finishes so voice stays active
  utter.onend = () => {
    if (_voiceEnabled && _recognition) {
      try { _recognition.start(); } catch(e) {}
    }
  };

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

// ── Browser Board ─────────────────────────────────────────────────────────────
const _SLOT_LABELS = ["Slot 0", "Slot 1", "Slot 2", "Slot 3"];
const _boardTiles = {};

function selectBoardSlot(slotId) {
  const select = document.getElementById("board-slot-select");
  if (select) select.value = slotId;
  
  // Highlight the selected tile
  for (let i = 0; i < 4; i++) {
    const tile = document.getElementById(`bframe-${i}`)?.parentElement;
    if (tile) {
      if (i === slotId) {
        tile.style.border = "2px solid #00ff88";
        tile.style.boxShadow = "0 0 10px rgba(0, 255, 136, 0.3)";
      } else {
        tile.style.border = "1px solid var(--border)";
        tile.style.boxShadow = "none";
      }
    }
  }
}

function getSelectedBoardSlot() {
  const select = document.getElementById("board-slot-select");
  return select ? parseInt(select.value) : 0;
}

async function boardNavigate() {
  const slotId = getSelectedBoardSlot();
  const input = document.getElementById("board-url-input");
  const url = input ? input.value.trim() : "";
  if (!url) return;
  
  await fetch(`/api/browser-svc/slots/${slotId}/navigate`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ url }),
  });
}

async function boardBack() {
  const slotId = getSelectedBoardSlot();
  await fetch(`/api/browser-svc/slots/${slotId}/back`, {
    method: "POST",
  });
}

async function boardReload() {
  const slotId = getSelectedBoardSlot();
  await fetch(`/api/browser-svc/slots/${slotId}/reload`, {
    method: "POST",
  });
}

async function boardType() {
  const slotId = getSelectedBoardSlot();
  const input = document.getElementById("board-type-input");
  const text = input ? input.value : "";
  if (!text) return;
  
  await fetch(`/api/browser-svc/slots/${slotId}/type`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ text }),
  });
  if (input) input.value = "";
}

async function boardPressEnter() {
  const slotId = getSelectedBoardSlot();
  await fetch(`/api/browser-svc/slots/${slotId}/key`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ key: "Enter" }),
  });
}

function initBrowserBoard() {
  const grid = document.getElementById("browser-board-grid");
  if (!grid || Object.keys(_boardTiles).length > 0) return;
  grid.style.cssText =
    "display:grid;grid-template-columns:repeat(2,1fr);gap:6px;padding:8px;height:calc(100% - 72px);box-sizing:border-box";

  for (let i = 0; i < 4; i++) {
    const tile = document.createElement("div");
    tile.style.cssText =
      "position:relative;background:#0d1117;border:1px solid var(--border);border-radius:6px;overflow:hidden;cursor:pointer";
    tile.innerHTML =
      `<img id="bframe-${i}" src="" style="width:100%;height:100%;object-fit:fill;display:none">` +
      `<div id="bidle-${i}" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:4px">` +
        `<span style="color:var(--muted);font-size:11px">${_SLOT_LABELS[i]}</span>` +
        `<span style="color:var(--border);font-size:9px">idle</span>` +
      `</div>` +
      `<div id="bchip-${i}" style="position:absolute;top:4px;left:4px;padding:1px 6px;border-radius:3px;font-size:8px;font-weight:700;background:rgba(255,255,255,0.08);color:var(--muted)">idle</div>` +
      `<div id="bstatus-${i}" style="position:absolute;bottom:0;left:0;right:0;padding:3px 6px;background:rgba(0,0,0,0.75);font-size:9px;color:#00d4ff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:none"></div>` +
      `<div id="bbadge-${i}" style="position:absolute;top:4px;right:4px;padding:1px 5px;border-radius:3px;font-size:8px;font-weight:700;background:rgba(0,255,128,0.15);color:#0f0;display:none">LIVE</div>` +
      `<button id="bresume-${i}" style="position:absolute;bottom:4px;left:4px;padding:2px 8px;font-size:8px;font-weight:700;border-radius:3px;border:1px solid #ff66cc;background:rgba(255,102,204,0.12);color:#ff66cc;cursor:pointer;z-index:2;display:none">Resume</button>` +
      `<button id="btakeover-${i}" style="position:absolute;bottom:4px;right:4px;padding:2px 8px;font-size:8px;font-weight:700;border-radius:3px;border:1px solid #00d4ff;background:rgba(0,212,255,0.12);color:#00d4ff;cursor:pointer;z-index:2">Take over</button>`;

    tile.addEventListener("click", e => {
      selectBoardSlot(i);
      const img = document.getElementById(`bframe-${i}`);
      if (img && img.style.display !== "none" && e.target === img) {
        const rect = img.getBoundingClientRect();
        const clickX = e.clientX - rect.left;
        const clickY = e.clientY - rect.top;
        const pctX = clickX / rect.width;
        const pctY = clickY / rect.height;
        const x = Math.round(pctX * 1280);
        const y = Math.round(pctY * 900);

        fetch(`/api/browser-svc/slots/${i}/click`, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({ x, y }),
        });
      }
    });

    const takeoverBtn = tile.querySelector(`#btakeover-${i}`);
    if (takeoverBtn) {
      takeoverBtn.addEventListener("click", e => {
        e.stopPropagation();
        selectBoardSlot(i);
        fetch(`/api/browser-svc/slots/${i}/ensure-interactive`, { method: "POST" });
      });
    }

    const resumeBtn = tile.querySelector(`#bresume-${i}`);
    if (resumeBtn) {
      resumeBtn.addEventListener("click", e => {
        e.stopPropagation();
        fetch(`/api/browser-svc/slots/${i}/resume`, { method: "POST" });
      });
    }

    grid.appendChild(tile);
    _boardTiles[i] = {
      img: document.getElementById(`bframe-${i}`),
      idle: document.getElementById(`bidle-${i}`),
      status: document.getElementById(`bstatus-${i}`),
      badge: document.getElementById(`bbadge-${i}`),
      chip: document.getElementById(`bchip-${i}`),
      resumeBtn: document.getElementById(`bresume-${i}`),
      lastFrameAt: null,
    };
  }

  // Setup inputs Enter listeners
  const boardUrlInput = document.getElementById("board-url-input");
  if (boardUrlInput) {
    boardUrlInput.addEventListener("keydown", e => { if (e.key === "Enter") boardNavigate(); });
  }
  const boardTypeInput = document.getElementById("board-type-input");
  if (boardTypeInput) {
    boardTypeInput.addEventListener("keydown", e => { if (e.key === "Enter") boardType(); });
  }

  // Log tile spans both columns of the 2×2 grid so 4 browser tiles + 1 log
  // tile leave no awkward empty cell (was a clean 2×3 with 5 browser tiles;
  // a plain 3-column grid with 4 would leave a gap).
  const logTile = document.createElement("div");
  logTile.style.cssText =
    "background:#0d1117;border:1px solid var(--border);border-radius:6px;padding:8px;overflow-y:auto;grid-column:1 / -1";
  logTile.innerHTML =
    `<div style="font-size:10px;color:#00ff88;margin-bottom:4px;font-weight:600">Apply Log</div>` +
    `<div id="board-log" style="font-size:9px;color:var(--muted);display:flex;flex-direction:column;gap:3px"></div>`;
  grid.appendChild(logTile);

  // Default-select Slot 0 — it's a real browser slot now, not Overleaf/CV
  setTimeout(() => selectBoardSlot(0), 100);
}

function handleBrowserFrame(obj) {
  const boardEl = document.getElementById("island-board");
  if (!boardEl) return;
  initBrowserBoard();
  const slot = obj.slot != null ? obj.slot : 0;
  const tile = _boardTiles[slot];
  if (!tile) return;
  if (obj.frame) {
    tile.img.src = "data:image/jpeg;base64," + obj.frame;
    tile.img.style.display = "block";
    tile.idle.style.display = "none";
    tile.badge.style.display = "block";
    tile.lastFrameAt = Date.now();
  }
  const label = (obj.action ? obj.action + (obj.url ? "  —  " + obj.url : "") : obj.url) || "";
  if (label) {
    tile.status.textContent = label;
    tile.status.style.display = "block";
  }
}

function _formatFrameAge(ms) {
  if (ms == null) return "no frames yet";
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s ago`;
  return `${Math.round(s / 60)}m ago`;
}

// Combines browser-svc's polled slot state with frame-arrival recency into one
// chip: "busy" + a frame within the last 5s reads as "streaming"; "busy" with
// no recent frame reads as "connecting" — the stalled-stream signal the spec
// wants visible even when the JPEG stream itself goes silent. An "awaiting
// input" branch belongs here once Phase 4 (spec Section 3) defines the
// escalation signal that would set it.
function _computeSlotChip(backendState, lastFrameAt, blockedReason) {
  const ageMs = lastFrameAt != null ? Date.now() - lastFrameAt : null;
  if (blockedReason) {
    const short = blockedReason.length > 36 ? blockedReason.slice(0, 36) + "…" : blockedReason;
    return { text: `awaiting input · ${short}`, color: "#ff66cc" };
  }
  if (backendState === "error") return { text: "error", color: "#ff4444" };
  if (backendState === "idle")  return { text: "idle",  color: "var(--muted)" };
  if (ageMs == null || ageMs > 5000) {
    return { text: `connecting · ${_formatFrameAge(ageMs)}`, color: "#ffaa00" };
  }
  return { text: `streaming · ${_formatFrameAge(ageMs)}`, color: "#00ff88" };
}

let _boardStatusInterval = null;

async function pollBoardSlotStatuses() {
  let slots;
  try {
    const r = await fetch("/api/browser-svc/slots");
    if (!r.ok) return;
    slots = await r.json();
  } catch (e) {
    return; // browser-svc unreachable this tick — chips simply hold their last value
  }
  for (const s of slots) {
    const tile = _boardTiles[s.slot_id];
    if (!tile || !tile.chip) continue;
    const label = _computeSlotChip(s.state, tile.lastFrameAt, s.blocked_reason);
    tile.chip.textContent = label.text;
    tile.chip.style.color = label.color;
    if (tile.resumeBtn) {
      tile.resumeBtn.style.display = s.blocked_reason ? "block" : "none";
    }
  }
}

function startBoardStatusPolling() {
  if (_boardStatusInterval) return;
  pollBoardSlotStatuses();
  _boardStatusInterval = setInterval(pollBoardSlotStatuses, 3000);
}

function stopBoardStatusPolling() {
  if (_boardStatusInterval) {
    clearInterval(_boardStatusInterval);
    _boardStatusInterval = null;
  }
}

function logApplyResult(obj) {
  const log = document.getElementById("board-log");
  if (!log) return;
  const icon = obj.status === "applied" ? "✓" : obj.status === "captcha" ? "⚠" : "✕";
  const color = obj.status === "applied" ? "#0f0" : obj.status === "captcha" ? "#fa0" : "#f55";
  const entry = document.createElement("div");
  entry.style.color = color;
  entry.textContent = `${icon} ${obj.company || "?"} — ${obj.role || "?"}: ${obj.status}`;
  log.insertBefore(entry, log.firstChild);
  if (log.children.length > 30) log.removeChild(log.lastChild);
}

// ── Profile Modal ─────────────────────────────────────────────────────────────
let _profileData = {};
const _BROWSER_SVC = "/api/browser-svc";

async function toggleProfileModal() {
  const modal = document.getElementById("profile-modal");
  if (modal.style.display !== "none") { closeProfileModal(); return; }
  try {
    const r = await fetch(`${_BROWSER_SVC}/profile`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    _profileData = await r.json();
    renderProfileForm(_profileData);
    modal.style.display = "flex";
  } catch (e) {
    alert("browser-svc unreachable — is Docker running?");
  }
}

function closeProfileModal() {
  document.getElementById("profile-modal").style.display = "none";
}

function renderProfileForm(data) {
  const simple = ["name", "email", "phone", "linkedin", "notice_period", "location_preference"];
  const labels = {
    name: "Full Name", email: "Email", phone: "Phone",
    linkedin: "LinkedIn URL", notice_period: "Notice Period", location_preference: "Location",
  };
  const fields = document.getElementById("profile-form-fields");
  fields.innerHTML =
    simple.map(k =>
      `<div style="margin-bottom:10px">` +
        `<label style="font-size:11px;color:var(--muted);display:block;margin-bottom:3px">${labels[k]}</label>` +
        `<input id="pf-${k}" value="${(data[k] || "").replace(/"/g, "&quot;")}"` +
          ` style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:6px 8px;border-radius:4px;font-size:13px;box-sizing:border-box">` +
      `</div>`
    ).join("") +
    `<div style="margin-bottom:10px">` +
      `<label style="font-size:11px;color:var(--muted);display:block;margin-bottom:3px">Experience (years)</label>` +
      `<input id="pf-experience_years" type="number" value="${data.experience_years || 0}"` +
        ` style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:6px 8px;border-radius:4px;font-size:13px;box-sizing:border-box">` +
    `</div>` +
    `<div style="margin-bottom:10px">` +
      `<label style="font-size:11px;color:var(--muted);display:block;margin-bottom:3px">Target Roles (comma-separated)</label>` +
      `<input id="pf-target_roles" value="${(data.target_roles || []).join(", ")}"` +
        ` style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:6px 8px;border-radius:4px;font-size:13px;box-sizing:border-box">` +
    `</div>` +
    `<div style="margin-bottom:10px">` +
      `<label style="font-size:11px;color:var(--muted);display:block;margin-bottom:3px">Target Companies (comma-separated)</label>` +
      `<input id="pf-target_companies" value="${(data.target_companies || []).join(", ")}"` +
        ` style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:6px 8px;border-radius:4px;font-size:13px;box-sizing:border-box">` +
    `</div>` +
    `<div>` +
      `<label style="font-size:11px;color:var(--muted);display:block;margin-bottom:3px">Skills (comma-separated)</label>` +
      `<input id="pf-skills" value="${(data.skills || []).join(", ")}"` +
        ` style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:6px 8px;border-radius:4px;font-size:13px;box-sizing:border-box">` +
    `</div>`;
}

async function saveProfile() {
  const simple = ["name", "email", "phone", "linkedin", "notice_period", "location_preference"];
  const payload = {};
  for (const k of simple) {
    const el = document.getElementById(`pf-${k}`);
    if (el) payload[k] = el.value;
  }
  const expEl = document.getElementById("pf-experience_years");
  if (expEl) payload.experience_years = parseInt(expEl.value) || 0;
  const toList = id => {
    const el = document.getElementById(id);
    return el ? el.value.split(",").map(s => s.trim()).filter(Boolean) : [];
  };
  payload.target_roles = toList("pf-target_roles");
  payload.target_companies = toList("pf-target_companies");
  payload.skills = toList("pf-skills");
  try {
    const r = await fetch(`${_BROWSER_SVC}/profile`, {
      method: "PATCH",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    if (r.ok) { closeProfileModal(); }
    else { alert("Failed to save profile — check browser-svc logs"); }
  } catch (e) {
    alert("browser-svc unreachable");
  }
}
