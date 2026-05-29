# Subaru Command Center — Full System Design

**Project:** Shadow Garden  
**System Name:** Subaru (formerly J.A.R.V.I.S.)  
**Date:** 2026-05-29  
**Status:** Approved for implementation planning  
**Based on:** Analysis of Gemini implementation plan + extended brainstorming session

---

## 0. Source Plan Analysis — What Changed and Why

This design is based on a Gemini-generated implementation plan (`17c64d1d...implementation_plan.md`) with the following corrections and extensions:

| Gemini Plan Issue | This Design's Fix |
|---|---|
| Scheduler race condition — `get_prev()` fires 60× per trigger | Use `get_next()` + per-minute fire key deduplication |
| Playwright context leak — `async_playwright().start()` on every reconnect | Store `_playwright_ctx` and close before recreating |
| Wrong package — `google-generativeai` (deprecated) | Use `google-genai` (current SDK) |
| Routine output silently dropped — `send=lambda d: None` | Store output in routine run log, broadcast summary to WS |
| Phase 8 no safety gate — agents write prod files unilaterally | Zone-based safety model + email approval gate |
| Memory uses keyword matching | SQLite FTS5 (porter + unicode61 tokenizer) |
| J.A.R.V.I.S. branding | Renamed to **Subaru** throughout |
| Claude Opus as default model | Sonnet default; Haiku for routines; Opus only on explicit request |
| Static tools.py — capabilities are hardcoded | **Skill Registry** — modular, versioned, hot-loadable |
| No vision input | Claude vision API for image drag-drop |
| Dashboard-style UI (always-on panels) | Ambient Command Surface — information on demand |

---

## 1. System Identity & Model Policy

### Name
The AI command system is **Subaru**. The CEO agent persona remains "Subaru Natsuki" — same character, the system now carries that identity at every layer. Wake word: "Hey Subaru".

### Model Routing

| Context | Model ID |
|---|---|
| All agents — default | `claude-sonnet-4-6` |
| Routine execution (high-frequency) | `claude-haiku-4-5-20251001` |
| Explicit user request: "use Opus / deep think / best thinking" | `claude-opus-4-7` |
| Stuck task after 3 QA retries | `claude-opus-4-7` (one escalation pass, logged) |
| Claude quota hit → Gemini mid-tier | `gemini-2.0-flash` via `google-genai` SDK |
| Gemini error → free fallback | `tgpt` pollinations / sky |

Model selection lives in `app/agents/backend_state.py`. The model used per-turn is emitted in every `backend_status` WebSocket event so the UI header pill always reflects reality.

---

## 2. Frontend — Ambient Command Surface

### Design Philosophy
**Information is earned, not displayed.** Subaru is an interface, not a dashboard. The default state shows almost nothing. Complexity unfolds only when needed.

### 2.1 Three UI States

**State 1 — Idle (no active task)**
```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│                    ◉  SUBARU                                │
│                ╱           ╲                                │
│             ╱   arc reactor  ╲   green pulse = healthy      │
│            │    status ring   │   cyan pulse = thinking     │
│             ╲               ╱   red pulse = error          │
│                ╲           ╱                                │
│                                                             │
│        ○  ○  ○  ○  ○     ← agent orbs (dim = idle)         │
│       CEO  BE  FE  QA  DO                                   │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Ask Subaru anything...             🎤  📎  ⌘K  ▶  │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

**State 2 — Active (agent responding)**
```
┌─────────────────────────────────────────────────────────────┐
│  SUBARU │ ⚡ Claude Sonnet │ 🟢 12 Skills │ 📬 2 │ 🔔     │
├─────────────────────────────────────────────────────────────┤
│  [CEO ●]  Working on trading dashboard...                   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ ✓ Planning    — decomposed into 4 subtasks           │   │
│  │ → Executing  — Backend writing FastAPI routes        │   │  ← Thinking Layer
│  │ ⏳ Verifying  — waiting for QA gate                  │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  [Chat thread renders here — images, code cards, iframes]  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Reply or attach...                     🎤  📎  ▶  │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

**State 3 — Focus (Escape key)**
Collapses everything except the active chat thread and input bar. No header, no orbs, no pills. One more Escape restores.

### 2.2 Agent Orbs

Five small glowing orbs replace the sidebar dock. Each orb:
- **Dim grey** = idle
- **Pulsing in agent color** = active/thinking
- **Hover** → expands card: name, title, current task, active backend
- **Click** → switches active conversation to that agent

No permanent sidebar. Visual weight drops to near zero when all agents idle.

### 2.3 Command Palette (Ctrl+K / Cmd+K)

Global fuzzy-searchable overlay, replaces most navigation. Slides in over everything:

```
┌──────────────────────────────────────┐
│  ⌘  Search or ask...                 │
├──────────────────────────────────────┤
│  💬 Ask CEO: build me a landing page │
│  ─────────────────────────────────── │
│  📋 Show Routines                    │
│  ▶  Run Morning Standup              │
│  ➕ Create New Routine               │
│  🌐 Open Browser Panel               │
│  🎨 Open Design Workspace            │
│  🧠 Show Skills Panel                │
│  💾 Export Chat History              │
│  🔍 Search Memory                    │
└──────────────────────────────────────┘
```

Tabs (Routines, Browser, Design) become **modes invoked by the palette**, not always-visible navigation chrome.

### 2.4 Skills Panel

Invoked via `⌘K → "skills"` or clicking the `🟢 N Skills` header pill. Shows Subaru's full capability inventory in real time:

```
┌───────────────────── SUBARU SKILLS ──────────────────────────┐
│                                                              │
│  ⚡ INTELLIGENCE LAYER                                       │
│  ● Claude Sonnet  [Active]      ● Gemini 2.0 Flash [Ready]  │
│  ● tgpt Fallback  [Standby]     ● Claude Opus  [On demand]  │
│                                                              │
│  🛠 CORE TOOLS              🧠 LEARNED SKILLS               │
│  ✅ Code Execution           ✅ Stripe Payments  v2          │
│  ✅ File R/W                 ✅ Trading Signals  v1          │
│  ✅ Web Browsing             ✅ Weather API      v1          │
│  ✅ Email In/Out             ➕ [Install New Skill]          │
│  ✅ Team Delegation                                          │
│  ✅ Playwright Browser       📊 TODAY                        │
│  ✅ Claude Vision Input      14 routines run                 │
│  ✅ Voice STT/TTS            3 agents active                 │
│  ✅ Long-Term Memory         2 emails sent                   │
│  ✅ Routines Engine          0 self-heals                    │
│  ✅ Design Preview                                           │
│  ✅ Self-Healing                                             │
└──────────────────────────────────────────────────────────────┘
```

### 2.5 Image-Native Chat

- **Drag any image** onto the chat → attaches as a Claude vision input block → CEO sees and reasons natively
- **File drop**: PDF, CSV, ZIP → CEO auto-classifies and routes to right agent
- **Agent-generated HTML/CSS** renders inline as a sandboxed `<iframe>` card inside the chat bubble — no tab switch needed
- **SVG/chart output** from agents renders as visual cards directly in the message thread
- **Screenshot diff**: paste two images and ask "what changed?" → CEO uses vision to diff them

### 2.6 Floating Islands (PiP Panels)

Three detachable mini-panels that float over the main surface:

| Island | Default Position | Content |
|---|---|---|
| **Browser** | Top-right | Live Playwright screenshot, auto-refreshes every 2s when active |
| **Design Preview** | Bottom-right corner | Live iframe of Emilia's latest HTML output |
| **Notification Stream** | Bottom-right edge | Routine completions, email arrivals, agent events, self-heals |

Each island is draggable, collapsible to a chip, and persistent across sessions.

### 2.7 Thinking Transparency Layer

When an agent is processing, a collapsible panel shows the execution timeline:

```
🔵 Planning    ✓  Decomposed into 4 subtasks (12ms)
🔵 Executing   →  [backend] Writing /app/api/trading.py
               →  [frontend] Building chart components  ← parallel
🟡 QA Gate     ⏳ Beatrice reviewing backend output
⬜ Deploying   —  pending
```

Tool calls appear as they happen. Agent-to-agent messages show as `↔ CEO ↔ Backend`. For Opus turns, a badge reads "Opus activated — stuck task escalation".

### 2.8 Design System

```css
/* Color palette */
--bg-base:       hsl(220, 20%, 6%);
--bg-card:       hsl(220, 18%, 10%);
--bg-elevated:   hsl(220, 16%, 14%);
--accent-cyan:   hsl(185, 100%, 50%);   /* primary */
--accent-purple: hsl(270, 80%, 65%);    /* secondary */
--accent-gold:   hsl(42,  100%, 60%);   /* CEO / Subaru identity */
--accent-green:  hsl(140, 70%, 50%);    /* success / healthy */
--accent-red:    hsl(0,   80%, 60%);    /* alert */
--text-primary:  hsl(210, 30%, 90%);
--text-muted:    hsl(210, 15%, 55%);
--border:        hsl(220, 20%, 18%);
--glow-cyan:     0 0 20px hsla(185,100%,50%,.25);
```

```
Typography:
  Brand / Headings: Orbitron (sci-fi geometric)
  UI / Body:        Inter
  Code:             JetBrains Mono
```

---

## 3. Backend / Brain

### 3.1 AI Router (3-Tier)

```
Request
  │
  ▼
backend_state.should_use_claude()?
  │ YES → run_claude_agent()  [claude-sonnet-4-6 default]
  │         ↓ quota/rate error
  │       mark_claude_exhausted()
  │         ↓
  │       run_gemini_agent()  [gemini-2.0-flash, google-genai SDK]
  │         ↓ error
  │       run_tgpt_agent()    [pollinations / sky]
  │
  └ NO  → run_gemini_agent() or run_tgpt_agent() based on gemini_ok flag
```

`backend_state.py` extended to track three backends: `"claude"` | `"gemini"` | `"tgpt"`. Each transition emits a `backend_switch` WebSocket event. The header pill reflects the active backend in real time.

The `run_gemini_agent()` function uses the `google-genai` SDK (not the deprecated `google-generativeai`):

```python
import google.genai as genai

async def run_gemini_agent(agent_id, prompt, send):
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    response = await asyncio.to_thread(
        client.models.generate_content,
        model="gemini-2.0-flash",
        contents=_build_gemini_prompt(agent_id, prompt),
    )
    text = response.text
    await send({"type": "assistant", "agent": agent_id,
                "message": {"content": [{"type": "text", "text": text}]}})
    return text
```

### 3.2 Claude Vision Input

When a user message contains image attachments, `executor.py` builds a multimodal content block and routes directly through the Anthropic SDK (bypassing the CLI) for that turn:

```python
async def run_claude_api_vision(agent_id, text, images, send):
    # images: list of {"media_type": "image/png", "data": "<base64>"}
    content = [
        {"type": "image", "source": {"type": "base64",
         "media_type": img["media_type"], "data": img["data"]}}
        for img in images
    ] + [{"type": "text", "text": text}]

    client = anthropic.AsyncAnthropic()
    async with client.messages.stream(
        model=config.DEFAULT_MODEL,
        max_tokens=4096,
        system=defs.agent_persona(agent_id),
        messages=[{"role": "user", "content": content}],
    ) as stream:
        async for chunk in stream.text_stream:
            await send({"type": "assistant", "agent": agent_id,
                        "message": {"content": [{"type": "text", "text": chunk}]}})
    return await stream.get_final_text()
```

### 3.3 Multi-Agent Collaboration

Agents can send structured messages to each other mid-task using `[ASK:ceo]` / `[REPLY:backend]` tags parsed by `executor.py`. CEO responses are injected back as tool results into the worker's loop. The Thinking Layer shows these as live `↔` exchanges.

Worker syntax:
```
[ASK:ceo] Should I use PostgreSQL or SQLite for this project?
```

CEO sees the question, replies, and the worker continues with the answer injected as context. If CEO is currently busy with another task, the `[ASK:]` message queues in `nexus_scratchpad.md` and is picked up on CEO's next available turn. Maximum wait: 2 minutes before the worker proceeds with a "no reply — using best judgement" fallback.

### 3.4 Shared Agent Scratchpad

`/app/nexus_scratchpad.md` — a shared working memory file all agents can read/write. Use cases:
- Backend leaves notes for Emilia: "Auth uses JWT, token in header X-Auth-Token"
- CEO records decisions: "Chose SQLite — single-user, no concurrency requirement"
- QA flags known issues: "Route /api/hire has no rate limiting — low priority"

CEO pre-injects the last 20 lines of the scratchpad into every system prompt.

### 3.5 Context Pre-Injection

Before every agent call, the system automatically appends to the system prompt:

```python
def build_context_block(agent_id: str, user_query: str) -> str:
    memories  = memory.get_relevant_memories(agent_id, user_query, limit=5)
    queue     = [i for i in state.work_queue if i["status"] != "completed"][-3:]
    scratch   = read_scratchpad_tail(lines=20)
    now_ist   = datetime.now(IST).strftime("%A %d %B %Y, %H:%M IST")

    return f"""
LIVE CONTEXT [{now_ist}]:
Active tasks: {json.dumps(queue, indent=2)}
Recent memories:
{chr(10).join(f'  - {m}' for m in memories)}
Scratchpad:
{scratch}
"""
```

### 3.6 Long-Term Memory (SQLite FTS5)

Schema in `nexus_memory.db`:

```sql
CREATE TABLE memories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id    TEXT NOT NULL,
    mem_type    TEXT NOT NULL DEFAULT 'conversation',
    content     TEXT NOT NULL,
    importance  REAL NOT NULL DEFAULT 0.5,
    created_at  TEXT NOT NULL,
    last_hit_at TEXT
);

CREATE VIRTUAL TABLE memories_fts USING fts5(
    content,
    agent_id UNINDEXED,
    tokenize='porter unicode61'
);

CREATE TABLE user_preferences (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);
```

`get_relevant_memories(agent_id, query, limit=5)` runs a ranked FTS5 query weighted by importance:

```sql
SELECT m.content
FROM memories_fts f
JOIN memories m ON m.id = f.rowid
WHERE memories_fts MATCH ?
  AND m.agent_id IN (?, 'shared')
ORDER BY rank * m.importance
LIMIT ?
```

A nightly consolidation routine decays `importance` by 0.05 for memories not hit in 7 days, keeping the DB lean without manual pruning.

---

## 4. Self-Learning & Scaling Architecture

### 4.1 Skill Registry

Skills are independent Python modules, not hardcoded functions. The registry separates *what Subaru knows* from *how Subaru runs*.

**Directory layout:**
```
/app/skills/
  registry.json              ← live manifest index
  loader.py                  ← SkillLoader, hot-reload watcher
  core/                      ← immutable, never auto-modified
    bash_tools.py
    file_tools.py
    email_tools.py
    web_tools.py
  learned/                   ← agent-installed, versioned
    <skill_id>/
      manifest.json
      v<N>/
        skill.py             ← exports: TOOLS list + handler functions
        test_skill.py        ← pytest tests, must pass before register
```

**`manifest.json` schema:**
```json
{
  "id": "stripe_payments",
  "name": "Stripe Payments",
  "active_version": "2",
  "description": "Create charges, subscriptions, refunds via Stripe API",
  "tools": ["create_payment", "refund_charge", "list_subscriptions"],
  "requires_packages": ["stripe>=7.0.0"],
  "available_to": ["ceo", "backend"],
  "safety_zone": "medium",
  "author": "backend",
  "created_at": "2026-05-29T14:00:00",
  "rollback_to": "1"
}
```

### 4.2 SkillLoader

`app/skills/loader.py` — the runtime that makes skills hot-loadable:

```python
class SkillLoader:
    def __init__(self, skills_dir: Path):
        self._dir   = skills_dir
        self._tools = {}          # tool_name -> callable
        self._watch = None        # asyncio file watcher task

    def load_all(self):
        """Load core + all active learned skills at startup."""
        self._load_core()
        for manifest_path in self._dir.glob("learned/*/manifest.json"):
            self._load_skill(manifest_path)

    def _load_skill(self, manifest_path: Path):
        manifest = json.loads(manifest_path.read_text())
        version  = manifest["active_version"]
        skill_py = manifest_path.parent / f"v{version}" / "skill.py"
        spec     = importlib.util.spec_from_file_location(manifest["id"], skill_py)
        mod      = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for tool in mod.TOOLS:
            self._tools[tool["name"]] = getattr(mod, tool["name"])

    def get_tool(self, name: str):
        return self._tools.get(name)

    def list_tools(self, agent_id: str) -> list[dict]:
        """Return all tools available to a given agent."""
        ...

    async def register_skill(self, manifest: dict, skill_code: str, test_code: str) -> dict:
        """Write files, run tests, register if passing. Called by agents."""
        ...

    def rollback(self, skill_id: str) -> bool:
        """Set active_version to rollback_to in manifest."""
        ...
```

A `watchfiles` async watcher monitors `registry.json`. When an agent updates it, `SkillLoader.reload()` runs without restarting uvicorn. The Skills Panel reflects the change within 2 seconds.

### 4.3 Skill Installation Flow

```
User: "Learn to use the Stripe API"
  │
  ▼
CEO: decomposes → delegates to Backend
  │
  ▼
Backend:
  1. [BASH: curl https://docs.stripe.com/api | head -200]  ← read docs
  2. [WRITE: /app/skills/learned/stripe_payments/v1/skill.py]
  3. [WRITE: /app/skills/learned/stripe_payments/v1/test_skill.py]
  4. [WRITE: /app/skills/learned/stripe_payments/manifest.json]
  5. [BASH: pytest /app/skills/learned/stripe_payments/v1/ -q]
  │
  ├── PASS → POST /api/skills/register  (updates registry.json, hot-reloads)
  │          Skills Panel: "✅ Stripe Payments v1 [Installed]"
  │
  └── FAIL → Backend self-debugs (max 3 retries)
             Still failing → CEO emails sauravsubaru@gmail.com with failure log
```

New API endpoints required:
```
POST /api/skills/register      → registers a new learned skill
GET  /api/skills               → list all skills + versions
POST /api/skills/{id}/rollback → revert to previous version
DELETE /api/skills/{id}        → remove a learned skill
```

### 4.4 Zone-Based Safety Model

```
┌──────────────────────────────────────────────────────────────┐
│  IMMUTABLE CORE                                              │
│  skills/core/*, main.py, skills/loader.py                    │
│  → Cannot be modified by any agent, ever                     │
├──────────────────────────────────────────────────────────────┤
│  PROTECTED ZONE                                (email gate)  │
│  executor.py, definitions.py, router.py,                     │
│  websocket.py, requirements.txt, Dockerfile                  │
│  → Agent proposes diff → emails sauravsubaru@gmail.com       │
│  → Awaits reply-approval before writing                      │
├──────────────────────────────────────────────────────────────┤
│  LEARNING ZONE                                 (test gate)   │
│  skills/learned/*, nexus_routines.json,                      │
│  nexus_scratchpad.md, nexus_memory.db                        │
│  → Agent writes freely; pytest must pass first               │
├──────────────────────────────────────────────────────────────┤
│  SURFACE ZONE                                  (auto)        │
│  static/*.html, static/*.css, static/*.js                    │
│  → Auto-applied; visual-only; trivially reversible           │
└──────────────────────────────────────────────────────────────┘
```

When an agent calls `write_source_file` on a Protected Zone path:
1. `executor.py` computes a unified diff
2. Emails the diff to sauravsubaru@gmail.com: subject `[Subaru] Approval needed: modify executor.py`
3. Pauses execution (stores pending state in `nexus_scratchpad.md`)
4. `email_poller.py` watches for a reply containing "APPROVE" or "DENY"
5. On APPROVE → writes file → resumes
6. On DENY → CEO reports back, logs the blocked attempt

### 4.5 Difficult Task Architecture

**Task Decomposition Engine**

CEO uses a structured decomposition prompt for complex requests. Output is a typed dependency graph stored in the work queue:

```python
{
  "task_group": "build_trading_dashboard",
  "subtasks": [
    {"id": "t1", "agent": "backend",  "task": "Build P&L FastAPI routes", "depends_on": []},
    {"id": "t2", "agent": "frontend", "task": "Build chart UI for t1 API", "depends_on": ["t1"]},
    {"id": "t3", "agent": "backend",  "task": "Add email alert on >2% drawdown", "depends_on": ["t1"]},
    {"id": "t4", "agent": "qa",       "task": "Security review t1+t2+t3", "depends_on": ["t2","t3"]}
  ]
}
```

Independent subtasks dispatch immediately. Dependents auto-dispatch when dependencies complete. The Thinking Layer visualizes the graph live.

**Iterative QA Gate**

Every agent output touching code routes through a fast Beatrice (Haiku) review:

```
Agent output
    ↓
Beatrice review (Haiku — cheap/fast)
    ├── APPROVED → deploy / continue
    └── REVISE   → agent retries with feedback (max 3)
                       ↓ still failing after 3
                   CEO escalates → Opus single pass
                   Still failing → email sauravsubaru@gmail.com
```

**Opus Escalation**

Triggered by: explicit user request ("use your best thinking") OR 3-retry QA failure. Logged in Skills Panel as "Opus activated — reason: [stuck task / user request]". Single turn only — drops back to Sonnet after.

### 4.6 Scaling Model

**Skills scale without touching existing code.**
Each new skill is an isolated module. The loader discovers and hot-loads it. Rollback to any version is a single manifest field change. Skill dependency chains are resolved topologically on install.

**Agents scale horizontally.**
CEO can hire specialist agents from persona templates in `skills/learned/agents/`. Each hired agent automatically inherits all skills marked `available_to: ["all"]`. Agents are stateless (prompt + memory injection) so spawning costs nothing.

**Memory scales with importance decay.**
FTS5 handles millions of rows. A nightly routine decays importance of unhit memories and consolidates near-duplicates. `get_relevant_memories()` ranks by `FTS5 score × importance` — frequently-used memories stay prominent, stale ones fade automatically.

**Routine scaling.**
Routines can declare dependencies on other routines. The scheduler builds a DAG and runs independent routines concurrently. A routine can spawn sub-routines with scoped prompts.

---

## 5. Feature Phases — Option B Execution Order

Infrastructure first, then features that depend on it.

| # | Phase | Key Deliverable | Depends On | New vs Gemini |
|---|---|---|---|---|
| 1 | Ambient HUD + Orbs + Skills Panel | New minimal UI shell | — | New design |
| 2 | AI Router (Sonnet→Gemini→tgpt) | 3-tier fallback + backend pill | — | Fixed (google-genai) |
| 3 | Skill Registry + SkillLoader | Hot-loadable skills, `/api/skills` | 1 | **New** |
| 4 | Long-Term Memory (FTS5) | `nexus_memory.db`, context injection | — | Fixed (FTS5) |
| 5 | Routines Engine | Cron scheduler (race condition fixed) | 4 | Fixed |
| 6 | Claude Design Panel | Floating island, agent iframe output | 1, 3 | Refined |
| 7 | Playwright Browser | Floating island, browser API | 1, 3 | Fixed (context leak) |
| 8 | Voice (Hey Subaru) | Wake word, STT, TTS, canvas visualizer | 1 | Renamed |
| 9 | Morning Standup | Email briefing routine | 5 | Unchanged |
| 10 | Claude Vision Input | Image drag-drop → multimodal API | 2 | **New** |
| 11 | Command Palette | ⌘K global navigation | 1 | **New** |
| 12 | Multi-Agent Collaboration | `[ASK:agent]` inter-agent messaging | 4, 5 | **New** |
| 13 | Self-Healing Phoenix | Zone-gated self-modification, email approval | 3, 4 | Fixed (safety model) |

---

## 6. Complete File Change Map

### New Files
| File | Purpose |
|---|---|
| `app/skills/loader.py` | SkillLoader — hot-loadable skill registry |
| `app/skills/registry.json` | Live skill manifest index |
| `app/skills/core/bash_tools.py` | Extracted core tool: bash |
| `app/skills/core/file_tools.py` | Extracted core tool: read/write/edit |
| `app/skills/core/email_tools.py` | Extracted core tool: email |
| `app/skills/core/web_tools.py` | Extracted core tool: web fetch |
| `app/services/scheduler.py` | Fixed cron scheduler (race-condition-safe) |
| `app/services/standup.py` | Morning briefing compiler |
| `app/services/browser.py` | Playwright browser + design preview writer |
| `app/services/memory.py` | SQLite FTS5 long-term memory |
| `nexus_routines.json` | Routine definitions store |
| `nexus_memory.db` | SQLite FTS5 memory database |
| `app/static/previews/` | Design preview + browser screenshot output dir |

### Modified Files
| File | Key Changes |
|---|---|
| `app/agents/backend_state.py` | 3-tier state: claude / gemini / tgpt |
| `app/agents/executor.py` | Vision path, Gemini runner, skill tool dispatch, zone guard |
| `app/agents/definitions.py` | Subaru identity, Haiku for routines, Opus escalation flag |
| `app/agents/tools.py` | Delegates to SkillLoader instead of hardcoded handlers |
| `app/api/router.py` | `/api/skills` CRUD, `/api/routines` CRUD, browser/design endpoints |
| `app/api/websocket.py` | `backend_switch`, `skill_installed`, `thinking_step` events |
| `app/main.py` | Start scheduler + skill watcher on startup |
| `app/config.py` | `GEMINI_API_KEY`, `DEFAULT_MODEL`, `HAIKU_MODEL`, `OPUS_MODEL` |
| `app/static/index.html` | Ambient surface, orbs, command palette shell, floating islands |
| `app/static/style-v5.css` | Full design system rebuild per Section 2.8 |
| `app/static/app-v5.js` | Ambient UI, ⌘K palette, orb logic, vision upload, thinking layer |
| `requirements.txt` | `google-genai`, `playwright`, `croniter`, `watchfiles` |
| `Dockerfile` | `playwright install chromium --with-deps` |

---

## 7. Verification Plan

| Phase | How to Verify |
|---|---|
| 1 — HUD | Open browser: arc reactor visible, orbs dim, command palette opens on ⌘K |
| 2 — Router | Exhaust Claude quota → header pill switches to Gemini in real time |
| 3 — Skills | POST `/api/skills/register` with a test skill → appears in Skills Panel within 2s |
| 4 — Memory | Chat 5 messages, restart app, ask CEO to recall → FTS5 returns relevant memory |
| 5 — Routines | Manually trigger `morning_standup` via `/api/routines/morning_standup/run` |
| 6 — Design | Ask Emilia to design a card → iframe appears as floating island |
| 7 — Browser | POST `/api/browser/navigate {url: "https://google.com"}` → screenshot in PiP |
| 8 — Voice | Say "Hey Subaru what are the active tasks" in Chrome → STT + TTS response |
| 9 — Standup | Email received at sauravsubaru@gmail.com within 10s of manual trigger |
| 10 — Vision | Drag a screenshot into chat → CEO describes what it sees |
| 11 — Palette | ⌘K → type "routines" → filtered actions appear, click runs them |
| 12 — Multi-agent | Ask CEO to build something complex → Backend uses `[ASK:ceo]` mid-task |
| 13 — Self-heal | Ask Backend to "improve executor.py error handling" → approval email received |

---

## 8. Open Decisions (Resolved)

| Question | Decision |
|---|---|
| System name | **Subaru** |
| Default model | **Claude Sonnet** (Haiku for routines, Opus on request/escalation only) |
| Memory retrieval | **SQLite FTS5** (porter + unicode61) |
| Playwright | **Include** — core feature, Docker rebuild accepted |
| Self-healing gate | **Email approval** for Protected Zone; auto for Learning/Surface zones |
| Gemini access | **Real API** via `google-genai` SDK (key configured in `.env`) |
| Skills architecture | **Skill Registry** with hot-reload — capabilities are modular and versioned |
