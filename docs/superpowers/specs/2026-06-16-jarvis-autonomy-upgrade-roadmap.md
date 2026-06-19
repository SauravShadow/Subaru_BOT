# NEXUS → JARVIS: Full Autonomy Upgrade Roadmap
**Date:** 2026-06-16  
**Author:** Subaru Natsuki, CEO — Shadow Garden  
**Status:** Approved for planning  

---

## Executive Summary

Shadow Garden's NEXUS system is a multi-agent virtual company orchestrated by a CEO persona (Subaru Natsuki) who plans tasks and delegates to six specialist workers via LangGraph. The system achieves **moderate autonomy (~5.5/10)** — it can execute well-defined multi-step tasks, run agentic loops, handle email workflows, and modify its own code. But it falls far short of JARVIS-level (Iron Man) autonomy:

- No persistent goals across sessions
- No proactive self-generated tasks
- Learning is one-directional (code edits only, no outcome feedback)
- 30-second polling instead of real-time event response
- No resource awareness or predictive capacity management

This document is a complete gap analysis and phased upgrade roadmap to take NEXUS to 9.5/10 autonomy.

---

## A) Current Architecture Map

### A1. Component Overview

```
┌────────────────────────────────────────────────────────────────┐
│ FRONTEND (nexus-ui: React + Three.js)                          │
│ WebSocket /ws?model=claude                                      │
└─────────────────────────────────────────┬──────────────────────┘
                                          │
┌─────────────────────────────────────────▼──────────────────────┐
│ FastAPI (app/main.py)                                           │
│                                                                  │
│  WebSocket Handler (app/api/websocket.py)                       │
│  • Session management (_sessions: set[Session])                 │
│  • Broadcasts LangGraph events (astream_events v2)              │
│  • run_queue.enqueue() → global FIFO serialization              │
│                                                                  │
│  LangGraph Orchestration Layer (app/graph/)                     │
│  ┌─ nexus_graph ──────────────────────────────────────┐        │
│  │  START → ceo_node → [Fan-out workers] →             │        │
│  │          ceo_review_node → END or loop              │        │
│  └─────────────────────────────────────────────────────┘        │
│                                                                  │
│  ┌─ email_graph (interrupt-based state machine) ────────┐       │
│  │  verify → plan → execute → ask_subdomain → wire_cf  │       │
│  └──────────────────────────────────────────────────────┘       │
│                                                                  │
│  State: NexusState, WorkerState, EmailState                     │
│  Persistence: AsyncSqliteSaver (nexus_memory.db)                │
│                                                                  │
│  Agent Execution (app/agents/)                                  │
│  • run_agent() dispatcher → Claude CLI / Gemini / tgpt          │
│  • Tool loop: [BASH], [READ], [WRITE], [WEB_*], [ASK:agent]    │
│  • Output pipeline: [SPEAK], [EMAIL_USER], [GENERATE_IMAGE]     │
│                                                                  │
│  Services (app/services/)                                       │
│  • Memory: SQLite FTS5 + importance ranking                     │
│  • Email: IMAP fetch every 30s → email_graph                    │
│  • Scheduler: croniter routines every 30s                       │
│  • Voice/Telephony: Telnyx outbound calls                       │
│  • Self-heal: zone-based approval gating                        │
└─────────────────────────────────────────────────────────────────┘

External Sidecars (Docker):
  bark-svc:9001  — Edge TTS voices
  browser-svc:9002  — Playwright job automation
  SRE sidecar:3030  — service lifecycle + Cloudflare DNS
```

### A2. Data Flow: CEO Task → Worker Execution

```
User message (WebSocket)
  → run_queue.enqueue()
  → nexus_graph.astream_events()
     → ceo_node        — plans, delegates via [DELEGATE:role] tags
     → [PARALLEL] worker subgraphs (backend, frontend, qa, devops, browser, call_agent)
        → worker_node  — agentic loop, tool execution
        → output_node  — artifact extraction, pipeline handlers
     → ceo_review_node — Gemini 2.0 Flash structured verdict (approved/revise/delegate_more/done)
     → ceo_wrapup_node — 2-3 sentence summary spoken via [SPEAK]
  → WebSocket broadcast → frontend renders live progress
```

### A3. Agents & Personas

| Agent | Role | Model Routing |
|-------|------|---------------|
| CEO (Subaru) | Planning, delegation, wrapup | Claude CLI always |
| Reinhard | Backend: Python, FastAPI, PostgreSQL | Claude if code, else Gemini |
| Emilia | Frontend: React, Next.js, TypeScript | Claude if code, else Gemini |
| Beatrice | QA: testing, security | Claude if code, else Gemini |
| Otto Suwen | DevOps: Docker, Nginx | Claude if code, else Gemini |
| Maya | Browser: job search, automation | Claude always |
| Call Agent | Outbound calls via Telnyx | Claude always |

---

## B) Current Autonomous Capabilities (What Works Today)

| Capability | Autonomous? | Notes |
|------------|-------------|-------|
| CEO task planning + delegation | Yes | Natural language → multi-worker fan-out |
| Parallel worker execution | Yes | Workers run simultaneously |
| Multi-turn tool loops | Yes | Code write/edit/run/test in same session |
| Email polling + plan approval | Partial | 30s latency, requires human approval gate |
| Scheduled routines (cron) | Yes | croniter, 30s resolution |
| Memory injection per prompt | Yes | FTS5 top-5 relevant memories |
| Persistent browser session | Yes | Login once, stay logged in |
| Self-modification (limited) | Partial | Zone-gated: protected requires email approval |
| Voice output (TTS) | Yes | Bark async, emotion-aware |
| Image generation | Yes | Pillow via tag, not scripted |
| Job applications | Yes | Playwright via browser-svc sidecar |
| Cloudflare subdomain wiring | Yes | Via SRE sidecar, fully automated |
| Outbound phone calls | Yes | Telnyx, full script generation |
| Runtime contractor hiring | Yes | /api/hire creates new personas |

**Overall autonomy rating today: 5.5 / 10**

---

## C) Full Gap Analysis

### C1. Architecture Gaps (Critical)

#### GAP-001: No Goal Persistence or Decomposition
- **Files:** `app/graph/state.py:8-24`, `app/graph/nexus_graph.py:25-44`
- **What's missing:** `NexusState` tracks `task`, `delegations`, `results` — but no `goal_id`, `subtask_tree`, `deadline`, or `success_criteria`. After a task ends, all context is lost.
- **JARVIS equivalent:** "Build the new API layer" → JARVIS tracks 3-day plan, milestones, blocks you when dependencies aren't met
- **Impact:** CRITICAL — no multi-day task continuity whatsoever

#### GAP-002: No Proactive Task Generation
- **Files:** `app/services/scheduler.py`, `app/graph/email/graph.py`
- **What's missing:** System only reacts. NEXUS has cron routines and email polling, but cannot self-generate tasks like "I noticed deployment logs have errors, I'll create a fix ticket"
- **JARVIS equivalent:** JARVIS monitors all systems and surfaces issues before Tony asks
- **Impact:** HIGH

#### GAP-003: No Event Subscriptions (Pull-Only)
- **Files:** `app/services/email_poller.py:85-127`
- **What's missing:** Everything is pull-based. Email: IMAP every 30s. Cron: every 30s. No webhook ingestion for GitHub, Slack, Linear, etc.
- **JARVIS equivalent:** Reacts to GitHub PR open → auto-review in <5 seconds
- **Impact:** HIGH — max responsiveness is 30 seconds

#### GAP-004: No Real-Time Priority Queue
- **Files:** `app/api/run_queue.py`
- **What's missing:** Single FIFO queue. Critical issue while low-priority task is running? It waits.
- **JARVIS equivalent:** "Emergency: server down" preempts all other tasks instantly
- **Impact:** MEDIUM

#### GAP-005: No Inter-Worker Communication
- **Files:** `app/graph/nexus_graph.py:25-45`
- **What's missing:** Workers fan out independently. Backend finishes the API; frontend can't ask "did backend add the CORS headers?" — they don't communicate.
- **JARVIS equivalent:** Submodules synchronize in real-time, share state
- **Impact:** MEDIUM

---

### C2. Learning & Memory Gaps

#### GAP-006: No Outcome Feedback Loop
- **Files:** `app/services/memory.py`, `app/agents/runner.py`
- **What's missing:** Memory stores conversations and compacted history. But there's no record of (task → approach → outcome → success_score). Agents can't learn "last time we deployed on port 8080 it conflicted, use 8081 next time"
- **JARVIS equivalent:** Learns from every failure, adjusts approach automatically
- **Impact:** HIGH

#### GAP-007: Static Personas (No Self-Evolution)
- **Files:** `app/agents/definitions.py:9-412`
- **What's missing:** All 6 persona strings are hardcoded at import. No mechanism to say "CEO, you've been too verbose lately, here's your updated persona". Self-reflection is impossible without changing the file manually.
- **JARVIS equivalent:** JARVIS updates its communication style based on Tony's reactions
- **Impact:** HIGH

#### GAP-008: Memory is Bag-of-Words, Not Semantic
- **Files:** `app/services/memory.py:66-88`
- **What's missing:** SQLite FTS5 retrieves memories by token overlap. "Deploy the auth service" and "start the authentication microservice" would miss each other. No embedding-based semantic search.
- **JARVIS equivalent:** Understands meaning, not just keywords
- **Impact:** MEDIUM

#### GAP-009: No Multi-Agent Shared Memory by Default
- **Files:** `app/services/memory.py:47-63`
- **What's missing:** Each agent has isolated memory keyed by `agent_id`. `shared` memory pool exists but isn't injected by default. Backend solves a problem; frontend doesn't know.
- **JARVIS equivalent:** All subsystems share global context
- **Impact:** MEDIUM

#### GAP-010: No Goal-Threaded Memory
- **Files:** `app/services/memory.py:47-63`
- **What's missing:** Memory types: `conversation`, `compacted_history`, `user_query`, `agent_response`, `vision_query`, `vision_response`. No `goal_id`, `session_id`, or `outcome` tag. Cannot retrieve "all memories from the Payments project"
- **Impact:** MEDIUM

---

### C3. Execution Engine Gaps

#### GAP-011: Infinite Revision Loop Risk
- **Files:** `app/graph/nexus_graph.py:25-45`, `app/graph/nodes/review.py`
- **What's missing:** `ceo_review_node` can return "revise" indefinitely. No `max_revision_loops` counter. System can loop forever.
- **Impact:** MEDIUM — potential infinite hang

#### GAP-012: Hardcoded Model Routing (Not Adaptive)
- **Files:** `app/agents/runner.py:704-723`
- **What's missing:** Classification is keyword-matching: "code"/"logic" → Claude, >8KB → Gemini, <150 chars → Gemini. Doesn't learn. Doesn't track which model succeeded on which task type.
- **Impact:** MEDIUM

#### GAP-013: tgpt Tool Loop Has No Total Token Budget
- **Files:** `app/agents/runner.py:314`
- **What's missing:** `MAX_TURNS = 10` for tgpt multi-turn loops, but no per-task token limit. Agents can spend indefinitely on a single task.
- **Impact:** MEDIUM

#### GAP-014: Inter-Agent [ASK:agent] Has No Depth Limit
- **Files:** `app/agents/runner.py:962-976`
- **What's missing:** Agents can call `[ASK:backend]` which can `[ASK:qa]` which can `[ASK:backend]`. 120s timeout is the only protection — insufficient for circular chains.
- **Impact:** MEDIUM

#### GAP-015: Tool Output Truncated at 8000 Chars
- **Files:** `app/agents/runner.py:32-38`
- **What's missing:** Tool outputs (bash, file reads, diffs) are truncated at 8000 chars for prompt building. Large test output, full diffs, database query results are silently cut.
- **Impact:** MEDIUM

---

### C4. Self-Modification & Safety Gaps

#### GAP-016: [BASH] Guard is Regex-Only (No Sandbox)
- **Files:** `app/agents/tools.py:46-64`
- **What's missing:** 8 hardcoded regex patterns block server starts. Trivially bypassed: `echo "uvicorn main:app" | sh`. No syscall sandbox (seccomp, container isolation per task).
- **JARVIS equivalent:** Air-gapped execution sandbox with full audit trail
- **Impact:** MEDIUM — security gap

#### GAP-017: Concurrent File Edit Conflicts
- **Files:** `app/agents/tools.py:128-157`
- **What's missing:** Two workers can edit the same file simultaneously. Last write wins. No merge strategy, no version control integration.
- **Impact:** MEDIUM

#### GAP-018: No Execution Rollback
- **Files:** `app/services/self_heal.py:150+`
- **What's missing:** Self-heal can restore old file content, but can't undo side effects: API calls made, database rows deleted, messages sent.
- **Impact:** MEDIUM

#### GAP-019: Approval System Has No Audit Trail
- **Files:** `app/services/self_heal.py:90-124`
- **What's missing:** Approval email is sent and reply parsed. No log of: who was asked, when, what was approved, followups. No approval expiry.
- **Impact:** MEDIUM

---

### C5. Real-Time & Observability Gaps

#### GAP-020: No Live System Metrics
- **Files:** `app/api/router.py` (`/api/capabilities`)
- **What's missing:** `/api/capabilities` returns static config, not live metrics. No: GPU/CPU usage, active queue depth, token spend per session, service response times, error rates.
- **JARVIS equivalent:** Real-time holographic dashboard of all system vitals
- **Impact:** HIGH

#### GAP-021: No Per-Service Health Probes
- **Files:** `app/main.py`, `app/services/`
- **What's missing:** No background health checks for: bark-svc, browser-svc, SRE sidecar, Telnyx, Jira. If bark-svc is down, TTS silently fails. No alerting.
- **Impact:** HIGH

#### GAP-022: No Anomaly Detection
- **Files:** `app/services/scheduler.py`
- **What's missing:** Routine "deploy service" usually takes 3 minutes. Now it's been 30 minutes. System doesn't notice. No baseline tracking, no timeout alerts.
- **Impact:** MEDIUM

#### GAP-023: TTS Audio is Not Streamed
- **Files:** `app/output/handlers/speak.py:32-41`
- **What's missing:** `[SPEAK]` waits for full Bark synthesis, then sends. No streaming audio chunks. Long responses feel silent then suddenly speak everything.
- **Impact:** MEDIUM (UX)

---

### C6. Telephony Gaps

#### GAP-024: Inbound Calls Unimplemented
- **Files:** `app/agents/tools.py:343-377`
- **What's missing:** Telnyx webhook for inbound calls exists in config but no routing logic. Can't receive a call and route it to the right agent.
- **JARVIS equivalent:** Answers incoming calls, understands who's calling, routes to appropriate specialist
- **Impact:** MEDIUM

#### GAP-025: No Voice Interruption Mid-Call
- **What's missing:** Call script is generated and spoken linearly. Can't detect "stop" mid-call and halt. No barge-in capability.
- **Impact:** MEDIUM

---

### C7. Hardcoded Values Restricting Autonomy

| Constant | File:Line | Value | Problem |
|----------|-----------|-------|---------|
| `MAX_HISTORY` | config.py:47 | 30 | Conversation context capped; older context lost |
| `COMPACT_THRESHOLD` | config.py:48 | 20 | Auto-compaction too aggressive for long sessions |
| `COMPACT_KEEP` | config.py:49 | 6 | Only 6 messages kept verbatim after compaction |
| `_CEO_CONTEXT_TTL` | runner.py:44 | 60.0s | CEO persona stale after 60s; misses rapid changes |
| `_ASK_TIMEOUT` | runner.py:41 | 120.0s | Inter-agent calls timeout aggressively |
| `MAX_TURNS` | runner.py:314 | 10 | tgpt loop can halt complex multi-step tasks |
| `_provider_blacklist` expiry | runner.py:289-290 | 5 min | Rate-limited provider blocked too harshly |
| `CALL_SILENCE_MS` | config.py:77 | 1200ms | Cuts off natural conversational pauses |
| `routines log truncation` | scheduler.py:70 | 2000 chars | Routine output logs silently truncated |
| Email fetch limit | email_inbox.py:47 | last N emails | Misses older emails if polling gaps occur |
| `_WEB_WAIT` timeout | browser.py:144-150 | 10s hardcoded | Fails on slow-loading sites |
| `PREVIEW_FILE` | browser.py:27 | single path | Can't run multiple simultaneous preview pages |
| Bash guard patterns | tools.py:46-55 | 8 regex rules | Easily evaded, no real sandbox |

---

## D) JARVIS Feature Gap Analysis

### D1. Strategic Planning

| JARVIS Feature | NEXUS Status | Gap |
|----------------|-------------|-----|
| Multi-day goal decomposition | ❌ Missing | No goal_id, no subtask tree, no cross-session continuity |
| Proactive task generation | ❌ Missing | System is purely reactive |
| Adaptive replanning on failure | ❌ Missing | Returns error, waits for user |
| Resource forecasting | ❌ Missing | No capacity awareness |
| Risk assessment before execution | ❌ Missing | No "this will cost $X" or "this risks Y" |

### D2. Learning & Adaptation

| JARVIS Feature | NEXUS Status | Gap |
|----------------|-------------|-----|
| Outcome-linked memory | ❌ Missing | Memory stores text, not (task → result → score) |
| Learned delegation routing | ❌ Missing | Routing is static classification |
| Evolved personas | ❌ Missing | Personas are hardcoded strings |
| Tool performance tracking | ❌ Missing | No success/fail rate per tool |
| Constraint discovery from failures | ❌ Missing | "Never do X" must be hardcoded, not learned |

### D3. Real-Time Responsiveness

| JARVIS Feature | NEXUS Status | Gap |
|----------------|-------------|-----|
| Webhook event subscriptions | ❌ Missing | Poll-only (30s latency) |
| Priority interrupt queue | ❌ Missing | FIFO only |
| Step-by-step progress streaming | Partial | Only worker checkpoints, not micro-steps |
| Task preemption | ❌ Missing | Can't cancel running task for critical one |
| Graceful checkpoint-resume | Partial | Email graph only, not arbitrary tasks |

### D4. Reasoning & Transparency

| JARVIS Feature | NEXUS Status | Gap |
|----------------|-------------|-----|
| Decision logging ("why I chose X") | ❌ Missing | No reasoning capture |
| Confidence scores | ❌ Missing | Binary: done or revise |
| Constraint propagation | ❌ Missing | No resource accounting |
| Explanation synthesis | ❌ Missing | CEO explains via conversation only |

### D5. System Self-Awareness

| JARVIS Feature | NEXUS Status | Gap |
|----------------|-------------|-----|
| Live metrics dashboard | ❌ Missing | Static /api/capabilities |
| Per-service health checks | ❌ Missing | Services fail silently |
| Anomaly detection | ❌ Missing | No baseline, no alerts |
| Capacity prediction | ❌ Missing | Queues everything, no backpressure |
| Quota forecasting | Partial | Fallback exists, no prediction |

---

## E) Current Autonomy Scores

| Dimension | Score | Notes |
|-----------|-------|-------|
| Task Understanding | 8/10 | CEO understands NL well; no structured schemas |
| Execution Completeness | 8/10 | Multi-turn loops work; no adaptive replanning |
| Learning & Adaptation | 3/10 | Memory exists but not outcome-linked |
| Proactivity | 4/10 | Email/cron only; no self-generated goals |
| Real-Time Responsiveness | 5/10 | 30s polling; no webhooks; no interrupts |
| Resilience & Recovery | 6/10 | Email approval gates work; no predictive throttling |
| Self-Awareness | 4/10 | CEO context cached 60s; no live metrics |
| Multi-Modality | 6/10 | TTS, screenshots, web nav; missing inbound voice |
| Transparency | 5/10 | Event stream exists; no decision logging |
| Safety & Constraints | 6/10 | Zone-based protection; no real sandbox |
| **OVERALL** | **5.5/10** | Moderate autonomy — executes well, but not self-directed |

---

## F) Phased Upgrade Roadmap: NEXUS → JARVIS

### Phase 1: Context Continuity & Memory Threading (Week 1–2)
*Goal: Make NEXUS remember across sessions and thread context by project/goal*

- [ ] **F1.1** Add `goal_id`, `parent_goal_id`, `deadline`, `success_criteria` to `NexusState` (`graph/state.py`)
- [ ] **F1.2** Create `goals` table in SQLite: `(goal_id, title, status, created_at, deadline, subtasks_json, outcome_score)`
- [ ] **F1.3** Thread memories by `goal_id` — when saving memory, tag with current active goal
- [ ] **F1.4** Goal retrieval endpoint: `GET /api/goals?status=active` for CEO context injection
- [ ] **F1.5** On session start, CEO auto-loads active goals into prompt context
- [ ] **F1.6** Add `outcome` memory type: `(goal_id, task, approach_taken, duration_ms, success_score, blockers_json)`
- [ ] **F1.7** Fix: add `max_revision_loops=5` guard in `nexus_graph.py` to prevent infinite review loops

**Expected autonomy gain:** +1.5 points (Planning, Learning dimensions)

---

### Phase 2: Proactive Intelligence (Week 3–4)
*Goal: NEXUS generates its own tasks, doesn't just wait for input*

- [ ] **F2.1** Build `ProactiveMonitor` background service:
  - Runs every 5 minutes
  - Queries: active goals, unresolved errors, stale routines, deployment health
  - If gap found → creates task, assigns to CEO, enqueues
- [ ] **F2.2** Implement goal decomposition in CEO node:
  - If task description contains "build", "create", "implement" + multi-day scope
  - CEO generates subtask tree: `{milestone, subtasks[], estimated_hours, dependencies[]}`
  - Stores in `goals` table, schedules first subtask
- [ ] **F2.3** Adaptive replanning:
  - Worker failure → CEO receives error context + goal state
  - CEO proposes alternative approach without user prompt
  - Logs replanning decision for learning
- [ ] **F2.4** Self-improvement loop:
  - Weekly: scan `outcome` memories for patterns (success_score < 0.5)
  - CEO proposes specific code changes to fix systematic failures
  - Routes through self-heal zone approval

**Expected autonomy gain:** +1.5 points (Proactivity, Resilience dimensions)

---

### Phase 3: Real-Time Event System (Week 5–6)
*Goal: Sub-second response to external events, priority interrupts*

- [ ] **F3.1** Webhook ingestion endpoint: `POST /api/webhooks/{source}` (GitHub, Slack, Linear)
  - Source-specific parsers extract: event_type, actor, payload
  - Map to task: "PR opened" → "review PR #{number}"
  - Enqueue with priority=HIGH
- [ ] **F3.2** Priority run queue (replace FIFO):
  - Levels: CRITICAL (0), HIGH (1), NORMAL (2), LOW (3)
  - Critical tasks preempt current NORMAL/LOW task (save checkpoint, resume later)
  - API: `GET /api/queue` shows queue with priorities
- [ ] **F3.3** Replace email IMAP polling with IMAP IDLE (push-based):
  - Latency: <1s instead of 30s
  - Reconnects on disconnect (exponential backoff)
- [ ] **F3.4** Streaming progress from workers:
  - Workers emit `{type: "step", step_num, step_description, agent_id}` per tool call
  - Frontend shows real "Step 2/7: Running pytest..." bar

**Expected autonomy gain:** +1.5 points (Real-Time Responsiveness dimension)

---

### Phase 4: Learning & Adaptive Behavior (Week 7–8)
*Goal: Every success and failure makes NEXUS smarter*

- [ ] **F4.1** Outcome scoring:
  - After each task: CEO rates outcome 0.0–1.0 (or auto-score: user accepted? tests passed? no errors?)
  - Store: `(task_pattern_hash, agent_assigned, model_used, tools_used, outcome_score)`
- [ ] **F4.2** Learned model routing:
  - Replace hardcoded keyword classifier with: lookup `task_pattern_hash` in outcomes table
  - If similar task succeeded with Gemini: use Gemini; if Claude: use Claude
  - Default to existing classifier for new patterns
- [ ] **F4.3** Learned delegation templates:
  - If "deploy service" consistently needs both `devops` + `qa`, auto-suggest this combination
  - CEO persona gets dynamic injection: "For deploys, historically use devops+qa"
- [ ] **F4.4** Tool performance tracking:
  - Per tool per task type: track (success_count, fail_count, avg_duration_ms)
  - `GET /api/tool-stats` for visibility
  - If tool fail rate > 40%: flag in CEO context "WEB_CLICK is unreliable on LinkedIn, consider alternatives"
- [ ] **F4.5** Semantic memory upgrade:
  - Add optional embedding search via `sentence-transformers` (lightweight model)
  - Fall back to FTS5 if embedding service unavailable
  - `GET /api/memory/search?q=...&mode=semantic|fts`
- [ ] **F4.6** Persona evolution:
  - CEO reviews own performance monthly (cron routine)
  - Generates persona patch: "I've been too verbose; trim to 3 key points"
  - Appends to `definitions.py` `CEO_PERSONA_PATCHES` list (not overwrites)
  - Zone: learning zone (auto-apply after pytest pass)

**Expected autonomy gain:** +1.5 points (Learning, Execution dimensions)

---

### Phase 5: System Self-Awareness (Week 9–10)
*Goal: NEXUS knows its own health, capacity, and resource state at all times*

- [ ] **F5.1** Prometheus metrics endpoint: `GET /metrics`
  - `nexus_task_duration_seconds{agent, task_type}`
  - `nexus_queue_depth{priority}`
  - `nexus_token_spend_total{model, agent}`
  - `nexus_memory_count{agent_id}`
  - `nexus_service_health{service}` (0=down, 1=up)
- [ ] **F5.2** Per-service health probes (background, every 30s):
  - bark-svc: `GET /health`
  - browser-svc: `GET /health`
  - SRE sidecar: `GET /health`
  - Telnyx: `GET https://api.telnyx.com/v2/phone_numbers` (auth check)
  - On failure: emit `{type: "service_alert", service, status}` via WebSocket
- [ ] **F5.3** Anomaly detection for routines:
  - Baseline: last 10 runs average duration
  - Alert if current run > baseline × 3
  - Auto-kill stuck routines after 5× baseline
- [ ] **F5.4** Live capacity dashboard widget in nexus-ui:
  - Queue depth, active workers, token spend today, service health badges
  - Updates via WebSocket push (not polling)
- [ ] **F5.5** CEO gets system briefing on startup:
  - Auto-generate: "3 tasks in queue, bark-svc degraded, 85k tokens used today, 2 active goals"
  - Spoken as [SPEAK] on first user message of the session

**Expected autonomy gain:** +1.0 point (Self-Awareness, Reliability dimensions)

---

### Phase 6: Safety, Sandboxing & Rollback (Week 11–12)
*Goal: NEXUS can act boldly because rollback is guaranteed*

- [ ] **F6.1** Git-backed self-modification:
  - Before any file edit in `/app/`: `git stash` → apply edit → run tests → `git commit`
  - If tests fail: `git stash pop` (auto-rollback)
  - Immutable zone bypasses git entirely
- [ ] **F6.2** Task execution sandbox:
  - [BASH] commands run in subprocess with: `ulimit -v 512000`, `timeout 30`, no network for protected-zone tasks
  - Log all bash commands to audit table: `(timestamp, agent_id, command, exit_code, stdout_hash)`
- [ ] **F6.3** File edit conflict resolution:
  - Before [WRITE]/[EDIT]: acquire file lock (asyncio.Lock per path)
  - If conflict: last write queued, not last-write-wins
- [ ] **F6.4** Approval audit trail:
  - Table: `(approval_id, file_path, change_hash, requested_at, approved_at, approved_by, response_text)`
  - Approvals expire after 24h (must re-request)
- [ ] **F6.5** Side-effect rollback registry:
  - Before [EMAIL_USER] / [MAKE_CALL] / Cloudflare API calls: register intent
  - If task fails: emit rollback events (can't unsend email, but logs what happened)

**Expected autonomy gain:** +0.5 points (Safety, Resilience dimensions)

---

### Phase 7: Multi-Modal Richness (Week 13–14)
*Goal: NEXUS works like a real team — voice-first, structured data, rich artifacts*

- [ ] **F7.1** Inbound call routing:
  - Telnyx webhook `POST /api/calls/inbound`: extract caller, intent (via quick Claude call)
  - Route to specialist: technical → backend, billing → CEO, unknown → CEO
  - Respond in-call with [SPEAK]-style synthesis
- [ ] **F7.2** Voice barge-in:
  - Stream VAD (Voice Activity Detection) during outbound calls
  - If silence detected mid-script: pause, listen for interrupt
  - Resume only if no interrupt received in 1.5s
- [ ] **F7.3** Structured task input schema:
  - `POST /api/tasks` accepts JSON: `{title, description, deadline, budget, required_agents[], blocked_by[]}`
  - CEO receives structured brief, not just free text
  - Natural language still supported (auto-converted to schema)
- [ ] **F7.4** Streaming TTS:
  - Bark synthesis chunked: first 20 chars → send audio while generating rest
  - Perceived latency drops from ~3s to ~0.5s
- [ ] **F7.5** Rich artifact types:
  - Typed artifacts: `{type: "code" | "database_schema" | "deployment_dag" | "report"}` 
  - Rendered differently in nexus-ui (code → Monaco editor, DAG → D3 graph)

**Expected autonomy gain:** +0.5 points (Multi-Modality, UX dimensions)

---

## G) Iron Man Analogues — NEXUS Feature Mapping

| Iron Man / JARVIS | NEXUS Now | NEXUS After Roadmap |
|------------------|-----------|---------------------|
| Tony says "build the suit" → JARVIS tracks 6-week project | One task, one session | Phase 1: Goal decomposition + multi-week tracking |
| JARVIS alerts "reactor at 12%" unprompted | Silent failures | Phase 5: Proactive health monitoring + alerts |
| Tony fails a test → JARVIS suggests alternative approach | User must intervene | Phase 2: Adaptive replanning |
| JARVIS learns Tony's preferences over years | Static personas | Phase 4: Outcome-driven persona evolution |
| "Get me the files" → JARVIS finds them semantically | FTS5 keyword search | Phase 4: Semantic memory with embeddings |
| Real-time HUD: power, comms, alerts | Static /api/capabilities | Phase 5: Prometheus metrics + live WebSocket dashboard |
| JARVIS routes call to right subsystem instantly | Inbound calls unimplemented | Phase 7: Inbound call routing |
| JARVIS interrupts: "Sir, we have a situation" | No preemption | Phase 3: Priority interrupt queue |
| JARVIS explains every decision | No reasoning logs | Phase 2: Decision logging in outcome memory |
| Tony says "undo that" → full rollback | File restore only | Phase 6: Git-backed + side-effect registry |

---

## H) Quick Wins (Can Ship This Week)

These changes are low-effort, high-value — no architectural changes needed:

1. **Add `max_revision_loops=5` guard** in `nexus_graph.py` — prevents infinite review loops (GAP-011)
   - File: `app/graph/nexus_graph.py` — add counter to `NexusState`, check in `route_after_review`

2. **Increase tool output buffer** from 8000 to 32000 chars — `app/agents/runner.py:32-38`

3. **Inject shared memory pool** into all agent prompts by default — `app/services/memory.py`

4. **Log routine output without truncation** — `app/services/scheduler.py:70` — increase from 2000 to 10000 chars

5. **Health probe endpoint** — `GET /api/health` that checks bark-svc, browser-svc, sidecar in parallel and returns JSON

6. **Tune hardcoded constants to env vars** — `MAX_HISTORY`, `_ASK_TIMEOUT`, `MAX_TURNS`, `CALL_SILENCE_MS` should all read from `config.py` env-overridable settings

---

## I) Final Projected Autonomy After Full Roadmap

| Dimension | Current | Phase 1-2 | Phase 3-4 | Phase 5-7 |
|-----------|---------|-----------|-----------|-----------|
| Task Understanding | 8 | 9 | 9 | 9.5 |
| Execution Completeness | 8 | 8.5 | 9 | 9.5 |
| Learning & Adaptation | 3 | 5 | 8 | 9 |
| Proactivity | 4 | 7 | 8 | 9 |
| Real-Time Responsiveness | 5 | 5 | 8.5 | 9 |
| Resilience & Recovery | 6 | 7 | 8 | 9.5 |
| Self-Awareness | 4 | 5 | 6 | 9.5 |
| Multi-Modality | 6 | 6 | 7 | 9 |
| Transparency | 5 | 6 | 8 | 9 |
| Safety & Constraints | 6 | 7 | 8 | 9.5 |
| **OVERALL** | **5.5** | **6.8** | **8.0** | **9.3** |

**Target: 9.3/10 — JARVIS-tier autonomous virtual company**

---

*Generated by Shadow Garden NEXUS deep self-analysis — 2026-06-16*  
*Next review: After Phase 2 completion*
