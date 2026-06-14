# app/graph/ — LangGraph Orchestration

The LangGraph layer that coordinates CEO planning and parallel worker execution.
Two compiled graphs live here: `nexus_graph` (main WebSocket-driven orchestration)
and `email/graph` (email processing state machine).

---

## Compiled Graph: nexus_graph

**File**: `app/graph/nexus_graph.py` — `build_nexus_graph(checkpointer)`

```
START
  |
  v
ceo_node          ← runs run_claude_agent("ceo", task), parses [DELEGATE:x] tags,
  |                  calls pipeline.process() for output tags (SPEAK, EMAIL_USER, etc.)
  |
  | route_after_ceo()
  |   → END if no delegations
  |   → Send(agent_id, WorkerState) for each delegation (parallel fan-out)
  |
  v
[backend] [frontend] [qa] [devops] [browser]   ← compiled worker subgraphs (parallel)
  |
  v
ceo_review_node   ← reviews collected worker_results
  |
  | route_after_review()
  |   → ceo_node   if verdict == "revise" | "delegate_more"
  |   → END        if verdict == "approved" | "done"
```

**Known agents** (hard-coded in `_KNOWN_AGENTS`):
`["backend", "frontend", "qa", "devops", "browser"]`

Worker subgraphs are built lazily and cached in `_worker_subgraphs` dict.

---

## State Schema

### NexusState (top-level graph, `app/graph/state.py`)

| Field | Type | Description |
|-------|------|-------------|
| `task` | str | User's original task text |
| `source` | Literal["browser", "api"] | How the task arrived |
| `session_id` | str | WebSocket thread id (uuid) |
| `model` | str | "claude" \| "gemini" \| "chatgpt" |
| `ceo_response` | str | Raw text from ceo_node LLM call |
| `delegations` | list[dict] | Parsed from CEO: [{"agent": str, "task": str}] |
| `artifacts` | dict | Shared artifacts passed to workers |
| `worker_results` | Annotated[list[dict], operator.add] | Reducer: accumulates all worker outputs |
| `ceo_verdict` | Literal["approved", "revise", "delegate_more", "done"] | Review outcome |
| `revision_notes` | str | CEO feedback when verdict == "revise" |
| `worker_progress` | dict | {agent_id: {"step": int, "checkpoints": list[str]}} |

### WorkerState (worker subgraphs)

| Field | Type | Description |
|-------|------|-------------|
| `task` | str | Task text sent by CEO |
| `agent_id` | str | Which worker this subgraph serves |
| `model` | str | Inherited from NexusState |
| `artifacts` | dict | Shared artifacts from CEO |
| `messages` | Annotated[list, add_messages] | LangChain message accumulator |
| `result` | str | Raw text output from run_agent() |
| `new_artifacts` | dict | Artifacts extracted from result ([ARTIFACT: name \| path]) |

---

## Worker Subgraph

**File**: `app/graph/workers/base.py` — `make_worker_graph(agent_id)`

```
START → worker_node → output_node → END
```

- **worker_node** (`_make_worker_node(agent_id)`): calls `run_agent(agent_id, task, send, model)`.
  Returns `{"result": str, "new_artifacts": dict}`.
- **output_node** (`app/graph/nodes/output.py`): calls `pipeline.process(result, agent_id, send)`.
  Extracts `[ARTIFACT: name | path]` and `[DONE: summary]` tags.
  Returns `{"new_artifacts": dict, "result": str}`.

Each compiled worker subgraph is stored in `_worker_subgraphs[agent_id]` and
added to the top-level graph as a named node using the agent_id as the node name.

---

## CEO Node

**File**: `app/graph/nodes/ceo.py` — `ceo_node(state, config)`

1. Builds task string (appends revision_notes if present).
2. Calls `run_claude_agent("ceo", task, send)` — always Claude, never routed.
3. Calls `pipeline.process(response, "ceo", send)` — handles SPEAK, EMAIL_USER, etc.
4. Parses `[DELEGATE:agent_id] task text` blocks via `_DELEGATE_RE`.
5. Returns `{"ceo_response": str, "delegations": list[dict]}`.

Delegation parsing: regex `^\[DELEGATE:(\w+)\]\s*(.*?)` (DOTALL|MULTILINE).
Only agents in `all_agents()` are accepted; unknown agent ids are silently dropped.

---

## CEO Review Node

**File**: `app/graph/nodes/review.py` — `ceo_review_node(state, config)`

Runs a second Claude call to review the combined worker results.
Sets `ceo_verdict` to one of: `"approved"`, `"revise"`, `"delegate_more"`, `"done"`.
If `"revise"`, sets `revision_notes` and the graph loops back to `ceo_node`.

---

## Checkpointer

**File**: `app/graph/checkpointer.py`

Async SQLite checkpointer (`AsyncSqliteSaver`). Initialized in lifespan
(`app/main.py`), stored in `app.state`. Same checkpointer instance is shared by
both `nexus_graph` and `email_graph`. Closed in lifespan teardown.

---

## Broadcast Channel

**File**: `app/graph/broadcast.py`

Thin async pub/sub: `register(thread_id, send_fn)` / `unregister(thread_id)` /
`send(thread_id, data)`. Used by nodes to emit WebSocket events without importing
from `app.api`. `websocket.py` registers its `broadcast_event` callback before
starting `graph.astream_events()`.

---

## Email Graph

**File**: `app/graph/email/graph.py` — `build_email_graph(checkpointer)`

Separate state machine for inbound email handling (`EmailState`). Receives
emails from `email_poller.py`. Not documented here — see `app/graph/email/`.

---

## Adding a New Graph Node or Worker

**New worker agent**:
1. Add agent id to `_KNOWN_AGENTS` in `nexus_graph.py`.
2. `_get_worker_subgraph(agent_id)` auto-builds the subgraph from `make_worker_graph`.
3. The graph wires `agent_id → ceo_review_node` automatically.
4. Add the agent definition in `app/agents/definitions.py` (see app/agents/README.md).

**New top-level node** (e.g. a parallel research step before CEO):
1. Write the node function in `app/graph/nodes/yournode.py`.
2. In `build_nexus_graph()`:
   - `graph.add_node("your_node", your_node_fn)`
   - `graph.add_edge("your_node", "ceo_node")` (or use conditional edges)
   - Wire `START → "your_node"` instead of `START → "ceo_node"`.
3. Update `NexusState` if the node needs new fields.
