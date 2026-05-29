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
  { icon:"🌐", label:"Open Browser Panel",  action: () => showIsland("browser") },
  { icon:"📋", label:"Show Routines",        action: () => sendMsgText("Show me all active routines and their last run status") },
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
      <div class="msg-body">${fmtMd(m.content||"")}</div>`;
    thread.appendChild(div);
  });
  thread.scrollTop = thread.scrollHeight;
  if (logs.length > 0) showChatMode();
}

function appendMsg(agentId, role, content) {
  if (!S.chatLogs[agentId]) S.chatLogs[agentId] = [];
  S.chatLogs[agentId].push({ role, content });
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
  appendMsg(S.activeAgent, "user", text + (S.attachments.length ? ` [+${S.attachments.length} file(s)]` : ""));
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
}
function hideIsland(name) { $id(`island-${name}`).style.display = "none"; }

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
    case "worker_done":
      setOrbState(agentId, "idle");
      setReactorState("idle");
      clearThinking();
      if (obj.summary) appendMsg(agentId, "assistant", `✓ ${obj.summary}`);
      break;

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

    case "cleared":
      S.chatLogs[agentId] = [];
      if (agentId === S.activeAgent) renderChat();
      break;
  }
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
  initFileInput();
  initDraggableIslands();
  boot();
});
