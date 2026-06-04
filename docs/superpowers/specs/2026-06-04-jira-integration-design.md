# Jira Integration Design

**Date:** 2026-06-04
**Status:** Approved

## Overview

Add Jira Cloud read/status-update/comment capability to the virtual company bot. The CEO agent can query tickets by person, read ticket details, update statuses, and add comments — all via natural language routed through tool tags. A background context injection keeps the CEO aware of the board state without being asked.

No auto-delegation. No ticket creation. Agents do not autonomously act on tickets.

---

## Credentials & Config

New environment variables added to `.env` and read in `app/config.py`:

```
JIRA_URL=https://sauravsubaru.atlassian.net
JIRA_EMAIL=cid.subaru.ai@gmail.com
JIRA_TOKEN=<api_token>
```

Auth method: HTTP Basic Auth using `email:token` (Atlassian Cloud standard).

---

## Service Module — `app/services/jira.py`

Single file wrapping Atlassian REST API v3. All functions are synchronous.

| Function | Endpoint | Description |
|---|---|---|
| `get_ticket(ticket_id)` | `GET /rest/api/3/issue/{id}` | Returns summary, description, assignee, status, priority |
| `search_tickets(jql)` | `GET /rest/api/3/issue/search?jql=...` | Raw JQL query, returns list of ticket dicts |
| `get_tickets_by_assignee(name)` | (wraps search_tickets) | Sugar: `assignee = "name"` JQL |
| `get_comments(ticket_id)` | `GET /rest/api/3/issue/{id}/comment` | Returns list of comments with author + body |
| `update_status(ticket_id, transition_name)` | `GET /transitions` → `POST /transitions` | Fetches available transitions, applies matching one by name (case-insensitive) |
| `add_comment(ticket_id, body)` | `POST /rest/api/3/issue/{id}/comment` | Posts a new comment |
| `get_context_summary()` | `GET /rest/api/3/issue/search` | Returns short board summary string for CEO context injection |

Error handling: all functions return a plain error string on failure (consistent with existing tool error convention), never raise exceptions into the agent loop.

---

## Tool Tags — `app/agents/tools.py`

Four new tags added to `parse_tool_call()`:

| Tag syntax | Example | Calls |
|---|---|---|
| `[JIRA_GET:<ticket_id>]` | `[JIRA_GET:PROJ-123]` | `get_ticket` + `get_comments` |
| `[JIRA_SEARCH:<jql>]` | `[JIRA_SEARCH:assignee = "Reinhard"]` | `search_tickets` |
| `[JIRA_STATUS:<ticket_id>:<transition>]` | `[JIRA_STATUS:PROJ-123:In Progress]` | `update_status` |
| `[JIRA_COMMENT:<ticket_id>:<body>]` | `[JIRA_COMMENT:PROJ-123:Looks good]` | `add_comment` |

Parsing uses the same `re.search` regex pattern as existing tags. Results are formatted as readable text and injected back into the agent turn as tool output.

---

## CEO Context Injection — `app/agents/definitions.py`

### 1. Persona tool docs

A short Jira section appended to the CEO's system prompt listing the four tags with usage examples, so the CEO can use them naturally when responding to Jira-related questions.

### 2. Live snapshot in `_get_ceo_context()`

`get_context_summary()` is called inside the existing `_get_ceo_context()` function (TTL: 60s). Output appended to the CEO's injected context:

```
JIRA SNAPSHOT:
  Open: 8  |  In Progress: 3  |  Done today: 1
  Use [JIRA_SEARCH:...] to query, [JIRA_GET:PROJ-123] for details
```

If the Jira call fails (network, bad creds), the snapshot section is omitted silently — no crash, no noise.

---

## Data Flow

```
User: "show all tasks for Reinhard"
  → CEO generates: [JIRA_SEARCH:assignee = "Reinhard"]
  → executor.py intercepts via parse_tool_call()
  → calls jira.search_tickets("assignee = \"Reinhard\"")
  → formatted result injected as tool output into next turn
  → CEO reads result and responds naturally
```

---

## Files to Create / Modify

| File | Action |
|---|---|
| `.env` | Add JIRA_URL, JIRA_EMAIL, JIRA_TOKEN |
| `app/config.py` | Read three new env vars |
| `app/services/jira.py` | Create — full Jira service wrapper |
| `app/agents/tools.py` | Add 4 new tool tag parsers + dispatch cases in executor |
| `app/agents/executor.py` | Add dispatch cases for the 4 new tool names |
| `app/agents/definitions.py` | Add Jira tool docs to CEO persona + snapshot injection |

---

## Out of Scope

- Auto-delegation of tickets to agents
- Ticket creation from chat
- Webhook-based real-time updates
- Worker agent (Reinhard, Emilia, etc.) access to Jira — CEO only for now
