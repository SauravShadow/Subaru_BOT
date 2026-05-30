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
      renderWorkerCards();
      updateQueuePill();
      break;

    case "thinking":
      setWorkerState(agentId, "working", "Thinking…");
      setReactorState("thinking");
      addThinkingStep(`${S.agents[agentId]?.name || agentId} thinking…`);
      break;

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
