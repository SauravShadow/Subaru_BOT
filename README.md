# NEXUS — Shadow Garden Virtual Company

AI multi-agent virtual company. CEO (Subaru Natsuki) receives tasks via WebSocket or email, plans using Claude, and delegates to specialist worker agents (backend, frontend, qa, devops, browser) via LangGraph fan-out. Workers execute agentic loops with real tools (Bash, file I/O, Playwright), then return results through an output pipeline that handles TTS, email, and browser automation tags.

---

## Architecture

```
React + R3F (nexus-ui)
    |
    | WebSocket /ws?model=claude
    v
FastAPI (app/main.py)
    |
    |-- /ws → ws_endpoint (app/api/websocket.py)
    |         |
    |         |-- target == "ceo" → nexus_graph.astream_events()
    |         |                     |
    |         |                     |-- ceo_node → parse [DELEGATE:agent] tags
    |         |                     |-- fan-out → worker subgraphs (parallel)
    |         |                     |       worker_node → run_agent() → output_node
    |         |                     |-- ceo_review_node → route_after_review
    |         |
    |         `-- target == worker → run_agent() direct + pipeline.process()
    |
    |-- REST /api/* → router.py
    |-- /ws/browser-relay → browser-svc WebSocket bridge
    `-- /static/* → compiled React app (nexus-ui build)
```

**LangGraph graph** (`app/graph/nexus_graph.py`): `NexusState` flows through
`ceo_node → [fan-out to worker subgraphs] → ceo_review_node → END|loop`.

**Agents** (`app/agents/`): defined in `definitions.py`; executed via
`runner.py` which chooses Claude CLI / Gemini API / tgpt per task type and quota.

**Output pipeline** (`app/output/pipeline.py`): scans every LLM response for
`[TAG: ...]` patterns and dispatches to handlers (SPEAK → Bark TTS, EMAIL_USER →
SMTP, BROWSER_* → browser-svc, GENERATE_IMAGE, SING).

**Background services**: email poller (IMAP every 30s dispatches to email_graph),
cron scheduler (croniter loop every 30s fires routines from nexus_routines.json).

---

## Port Registry

| Host port | Container port | Service |
|-----------|---------------|---------|
| 3031      | 3030          | virtual-company (FastAPI) |
| 9001      | 9001          | bark-svc (TTS sidecar) |
| 9002      | 9002          | browser-svc (Playwright sidecar, localhost-only) |

The SRE sidecar (operations_sidecar.py) runs on host port 3030 — separate from
the container. Worker agents use `http://host.docker.internal:3030/api/...` to
reach it for service lifecycle and Cloudflare DNS operations.

---

## Run / Restart

```bash
# Start all services (detached)
cd /mnt/HC_Volume_105874680/virtual-company
docker compose up -d

# Tail logs
docker compose logs -f virtual-company

# Restart after Python changes (uvicorn --reload handles /app hot-reload automatically)
# Only rebuild when requirements.txt or Dockerfile changes:
docker compose build virtual-company && docker compose up -d virtual-company

# Verify alive
curl -s http://127.0.0.1:3031/api/capabilities | python3 -m json.tool
```

The app code is volume-mounted from `/home/subaru/projects/virtual-company` →
`/app`. uvicorn runs with `--reload` so Python changes take effect in ~3s with
no container restart.

---

## Key Directories

| Path | Purpose |
|------|---------|
| `app/graph/` | LangGraph state, nodes, worker subgraphs |
| `app/agents/` | Agent definitions (personas), runner dispatch, tools |
| `app/output/` | Output pipeline: tag parser, handler registry, handlers/ |
| `app/services/` | bark_client, browser, email, email_poller, memory, scheduler, self_heal, standup |
| `app/api/` | REST router (router.py) + WebSocket handler (websocket.py) |
| `app/skills/` | Dynamically loaded skill plugins (tool extensions) |
| `app/state/` | In-memory conversation histories, projects, changelog |
| `nexus-ui/` | React + Three.js frontend (Vite; builds to app/static/) |
| `browser-svc/` | Playwright automation sidecar (separate Docker service) |
| `bark-lite/` | Bark TTS sidecar (separate Docker service) |

---

## Runtime Data Files (workspace root)

| File | Contents |
|------|---------|
| `nexus_memory.db` | SQLite FTS5 agent memory (app/services/memory.py) |
| `nexus_routines.json` | Cron routine definitions (scheduler) |
| `nexus_routine_logs.json` | Routine execution history |
| `nexus_pending_approvals.json` | Self-heal approval queue |
| `nexus_changelog.json` | Agent self-improvement log |
| `PORT_REGISTRY.json` | SRE sidecar port/subdomain registry |
| `service_registry.json` | SRE sidecar managed services |

---

## Adding a New Agent

1. Add an entry to `AGENT_DEFS` in `app/agents/definitions.py` with fields:
   `name`, `title`, `color`, `avatar`, `description`, `persona` (callable).
2. Add the agent id to `_KNOWN_AGENTS` in `app/graph/nexus_graph.py` so the
   graph builds a worker subgraph for it.
3. CEO persona in `definitions.py` must list the new agent in its team roster
   with the `[DELEGATE:id]` syntax so the CEO knows to use it.

See `app/agents/README.md` for runner dispatch details.

---

## Environment Variables

All read once at import in `app/config.py`. Key variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `CLAUDE_BIN` | `claude` | Path to Claude CLI binary |
| `GEMINI_API_KEY` | — | Enables Gemini fallback |
| `BARK_SVC_URL` | `http://bark-svc:9001` | TTS sidecar |
| `BROWSER_SVC_URL` | `http://browser-svc:9002` | Playwright sidecar |
| `SMTP_USER` / `SMTP_PASS` | — | Outbound email |
| `IMAP_USER` / `IMAP_PASS` | — | Email polling |
| `USER_EMAIL` | `sauravsubaru@gmail.com` | Default email recipient |
| `WORK_DIR` | `/workspace` | Agent working directory |
