# app/agents/ — Agent Definitions and Runner

Defines who the agents are and how they execute tasks. Two concerns:
- `definitions.py`: static persona registry (names, prompts, metadata).
- `runner.py`: execution engine (Claude CLI / Gemini API / tgpt dispatch, tool loop).

---

## Agent Definitions (`definitions.py`)

### AGENT_DEFS structure

```python
AGENT_DEFS: dict = {
    "agent_id": {
        "name":        str,   # Human name, e.g. "Subaru Natsuki"
        "title":       str,   # Role title, e.g. "Chief Executive Officer"
        "color":       str,   # Hex color for UI node, e.g. "#00d4ff"
        "avatar":      str,   # 2-char initials, e.g. "SN"
        "description": str,   # One-line summary shown in UI hover
        "persona":     callable,  # () -> str — returns system prompt
        # Optional:
        "gemini_safe_tags": list[str],  # Tags allowed when running on Gemini
    }
}
```

`persona` is always a callable (function or lambda returning a string) so that
config values (WORK_DIR, USER_EMAIL) are resolved at call time, not import time.

### Built-in agents

| ID | Name | Persona factory |
|----|------|----------------|
| `ceo` | Subaru Natsuki | `_ceo_persona()` — inline function |
| `backend` | Reinhard van Astrea | `_worker_persona(...)` |
| `frontend` | Emilia | `_worker_persona(...)` |
| `qa` | Beatrice | `_worker_persona(...)` |
| `devops` | Otto Suwen | `_worker_persona(...)` |
| `browser` | Maya | `_worker_persona(...)` with `gemini_safe_tags` |

`custom_agents: dict` holds runtime-hired contractors (via `POST /api/hire`).

### Key functions

```python
all_agents() -> dict          # AGENT_DEFS merged with custom_agents
get_agent(agent_id) -> dict   # Lookup with fallback to "ceo"
agent_persona(agent_id) -> str  # Calls agent["persona"]() if callable
public_agent_info(agent_id, agent) -> dict  # Strips persona for JSON
```

---

## Runner Dispatch (`runner.py`)

### Entry point: `run_agent()`

```python
async def run_agent(
    agent_id: str,
    prompt: str,
    send: Sender,       # async (dict) -> None — WebSocket broadcast callback
    model: str = "claude",
) -> str:
```

**Routing logic** (priority order):

1. **Explicit override**: `model == "chatgpt"` → `run_tgpt_agent()` (provider "sky").
   `model == "gemini"` → `run_gemini_agent()`.

2. **Task classification** (`_classify_model(prompt)`):
   - `len > 8000 chars` → gemini (large context window)
   - `len < 150 chars` → gemini (cheap, fast)
   - Code/logic signals (function, class, def, pytest, sql, json...) → claude
   - Default → claude

3. **Quota/availability fallback**:
   - ideal == gemini: try gemini → claude → tgpt
   - ideal == claude: try claude → gemini → tgpt

Backend state tracked in `backend_state.py`:
- `should_use_claude()` — false if quota exhausted (2h cooldown)
- `gemini_available()` — false if Gemini API returned an error
- Quota exhaustion: `run_claude_agent()` detects exit code != 0 + error text
  → auto-promotes to `run_gemini_agent()` and emits `backend_switch` WS event.

### Claude runner: `run_claude_agent()`

Invokes Claude CLI as subprocess:
```
claude -p <prompt> --output-format stream-json --verbose --model claude-sonnet-4-6 --allowedTools Bash,Read,Write,Edit,...
```
Reads streaming JSON from stdout. Only tool-call events are forwarded to `send()`
during execution; intermediate assistant text is accumulated. Final `full_resp`
is the complete assistant text across all tool turns.

Falls back to `run_gemini_agent()` on quota error.

Saves `(prompt, response[:500])` to memory via `mem_svc.save_memory()` after each run.

### Gemini runner: `run_gemini_agent()`

Single-turn via `google.genai.Client`. Prompt is built by `_build_gemini_prompt()`
which strips tgpt tool syntax from the persona and adds a `tool_note` warning
agents not to emit `[BASH:]` etc. (not executed by Gemini). Falls back to
`run_tgpt_agent()` on any error.

For `browser` agent: `gemini_safe_tags` are listed explicitly as allowed — these
are passed through to `browser-svc` handler, not executed as Claude tools.

### tgpt runner: `run_tgpt_agent()`

Multi-turn agentic loop (up to 10 turns). Calls `tgpt` binary with providers
`["sky", "pollinations", "isou"]`. Provider failover with 5-minute blacklist
on rate limit. Tool calls parsed from text output by `parse_tool_call()` in
`tools.py`, then dispatched via `_execute_tool()`.

### Vision runner: `run_claude_vision()`

Multimodal — tries Anthropic SDK first (ANTHROPIC_API_KEY), then Gemini 3.5 Flash.
Called from router when image data is uploaded. Not used in the LangGraph path.

---

## Tool Execution (`_execute_tool()`)

The tgpt loop parses structured tool tags from LLM output and dispatches:

| Tag | Handler |
|-----|---------|
| `[BASH: cmd]` | `local_bash(cmd)` |
| `[READ: path]` | `local_read(path)` |
| `[WRITE: path]` | `local_write(path, content)` |
| `[EDIT: path]` | `local_edit(path, target, replacement)` |
| `[READ_INBOX]` | `email_svc.read_emails()` |
| `[WRITE_PREVIEW:]` | `browser.write_preview(html)` |
| `[WEB_NAVIGATE: url]` | `browser.navigate(url)` + `browser_navigated` WS event |
| `[WEB_CLICK: sel]` | `browser.click_element(sel)` |
| `[WEB_TYPE: sel:val]` | `browser.type_text(sel, val)` (resolves `$CRED_*` from env) |
| `[WEB_WAIT: sel]` | `browser.wait_for_element(sel)` |
| `[WEB_GET_TEXT]` | `browser.get_page_text()` |
| `[WEB_EXTRACT: sel]` | `browser.extract_text(sel)` |
| `[ASK: agent_id]` | Recursive `run_agent()` with 120s timeout |
| `[READ_SOURCE: path]` | `local_read(path)` |
| `[WRITE_SOURCE: path]` | `self_heal.classify_path()` → write or approval gate |
| `[RUN_TESTS]` | `pytest /app/tests/ -q --tb=short` |
| `[GENERATE_IMAGE: desc]` | `generate_image(prompt)` → inline image WS event |
| `[JIRA_*]` | `jira_svc.*` |
| `[BROWSER_APPLY/DISCOVER/COMPANY/PROFILE_MATCH]` | `browser_svc.call_browser_svc()` |
| unknown | `skill_loader.get_tool(tool_type)` if registered |

Note: Claude CLI agents use native tools (Bash, Read, Write, etc.) — not these
tag-based tools. `_execute_tool` is only called in the tgpt multi-turn loop.

---

## Context Injection

Every agent prompt receives injected context (via `_build_context_block()`):
- Current IST timestamp
- Up to 5 relevant memories from SQLite FTS5 (`mem_svc.get_relevant_memories()`)

CEO additionally gets `_get_ceo_context()` (cached 60s):
- First 25 modifiable Python files in `/app/`
- Last 3 changelog entries
- Jira context summary (if configured)

Auto-compact fires before each prompt build when history exceeds
`config.COMPACT_THRESHOLD` (default 20): archives old messages to memory,
keeps `config.COMPACT_KEEP` (default 6) most recent.

---

## Adding a New Agent

1. In `definitions.py`, add to `AGENT_DEFS`:
   ```python
   "myagent": {
       "name":    "Agent Name",
       "title":   "Role Title",
       "color":   "#rrggbb",
       "avatar":  "XX",
       "description": "One-line summary",
       "persona": _worker_persona("Agent Name", "Role", "tech stack", "extra instructions"),
   }
   ```
2. In `nexus_graph.py`, add `"myagent"` to `_KNOWN_AGENTS`.
3. In CEO's `_ceo_persona()`, add to the team roster section.
4. `all_agents()` picks it up automatically; runner dispatches to it via standard path.

No runner changes needed — `run_agent()` resolves the persona from `definitions.py`.

---

## Direct Chat vs LangGraph Path

| Path | Trigger | Pipeline called by |
|------|---------|--------------------|
| LangGraph | `msg.agent == "ceo"` in WebSocket | `ceo_node` (CEO), `output_node` (workers) |
| Direct | `msg.agent == "<worker_id>"` in WebSocket | `ws_endpoint._run_direct()` |

In the direct path: `_run_direct()` calls `run_agent()` then `pipeline.process()` on the result.
No CEO delegation, no `ceo_wrapup_node`, no graph state.
