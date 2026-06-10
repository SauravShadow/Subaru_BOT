# Jira Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Jira Cloud read/status-update/comment capability to the virtual company bot via four new tool tags, backed by a service module, with a live board snapshot injected into the CEO's context.

**Architecture:** A sync service module (`app/services/jira.py`) wraps the Atlassian REST API v3 using `httpx`. Four new tool tags are parsed in `tools.py` and dispatched in `executor.py`. The CEO persona gets tool docs and a live Jira snapshot injected every 60s alongside the existing system self-awareness context.

**Tech Stack:** Python, httpx (already in requirements.txt), Atlassian REST API v3, pytest with unittest.mock

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `.env` | Modify | Add JIRA_URL, JIRA_EMAIL, JIRA_TOKEN |
| `app/config.py` | Modify | Read the three new env vars |
| `app/services/jira.py` | Create | All Jira API calls: get, search, update status, add comment, context summary |
| `app/agents/tools.py` | Modify | Add 4 new tool tag parsers before `return None, None` |
| `app/agents/executor.py` | Modify | Add icon/label map entries + 4 elif dispatch branches + Jira snapshot in `_get_ceo_context` |
| `app/agents/definitions.py` | Modify | Add Jira tool docs to `_ceo_persona()` |
| `tests/test_jira_service.py` | Create | Unit tests for jira.py with mocked httpx |
| `tests/test_jira_tool_parser.py` | Create | Parser tests for the 4 new tool tags |

---

## Task 1: Credentials & Config

**Files:**
- Modify: `.env`
- Modify: `app/config.py`
- Create: `tests/test_jira_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_jira_config.py
import os
from unittest.mock import patch


def test_jira_config_reads_env_vars():
    with patch.dict(os.environ, {
        "JIRA_URL":   "https://test.atlassian.net",
        "JIRA_EMAIL": "test@example.com",
        "JIRA_TOKEN": "secret-token",
    }):
        import importlib
        import app.config as cfg
        importlib.reload(cfg)
        assert cfg.JIRA_URL   == "https://test.atlassian.net"
        assert cfg.JIRA_EMAIL == "test@example.com"
        assert cfg.JIRA_TOKEN == "secret-token"


def test_jira_config_defaults_to_empty():
    clean_env = {k: v for k, v in os.environ.items()
                 if k not in ("JIRA_URL", "JIRA_EMAIL", "JIRA_TOKEN")}
    with patch.dict(os.environ, clean_env, clear=True):
        import importlib
        import app.config as cfg
        importlib.reload(cfg)
        assert cfg.JIRA_URL   == ""
        assert cfg.JIRA_EMAIL == ""
        assert cfg.JIRA_TOKEN == ""
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/subaru/projects/virtual-company
pytest tests/test_jira_config.py -v
```
Expected: `AttributeError: module 'app.config' has no attribute 'JIRA_URL'`

- [ ] **Step 3: Add env vars to `.env`**

Append these three lines to `.env`:
```
JIRA_URL=https://sauravsubaru.atlassian.net
JIRA_EMAIL=cid.subaru.ai@gmail.com
JIRA_TOKEN=ATATT3xFfGF0vhkuCUrq_Ha3QwlJ8AA-TJelWV4Vq-nADNuf7bUKnfmewYkyobCF6SlP9DCQqYRPV5uqt9iqNnUGNZCNry6I4dDX3EMF2G6wx1_unhqSwEgUfFeOrNYiUxVJkV-8iXDL4QQ9xmNosvQw-j38gfet3rVMUhFqS-u9TyhMt3R8VxQ=D0D1BD47
```

- [ ] **Step 4: Add config vars to `app/config.py`**

After the `GEMINI_API_KEY` line (around line 14), add:
```python
# Jira Cloud
JIRA_URL   = os.environ.get("JIRA_URL",   "")
JIRA_EMAIL = os.environ.get("JIRA_EMAIL", "")
JIRA_TOKEN = os.environ.get("JIRA_TOKEN", "")
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/test_jira_config.py -v
```
Expected: `2 passed`

- [ ] **Step 6: Commit**

```bash
git add .env app/config.py tests/test_jira_config.py
git commit -m "feat: add Jira config env vars"
```

---

## Task 2: Jira Service Module

**Files:**
- Create: `app/services/jira.py`
- Create: `tests/test_jira_service.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_jira_service.py
from unittest.mock import MagicMock, patch


def _mock_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


# ── get_ticket ─────────────────────────────────────────────────────────────────

def test_get_ticket_returns_formatted_string():
    payload = {
        "fields": {
            "summary":     "Fix login bug",
            "status":      {"name": "In Progress"},
            "priority":    {"name": "High"},
            "assignee":    {"displayName": "Reinhard van Astrea"},
            "description": {"type": "doc", "version": 1, "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "Login breaks on mobile"}]}
            ]},
            "comment":     {"comments": []},
        }
    }
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = _mock_response(payload)

    with patch("httpx.Client", return_value=mock_client):
        from app.services.jira import get_ticket
        result = get_ticket("PROJ-1")

    assert "Fix login bug" in result
    assert "In Progress" in result
    assert "Reinhard van Astrea" in result
    assert "Login breaks on mobile" in result


def test_get_ticket_handles_error():
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.side_effect = Exception("connection refused")

    with patch("httpx.Client", return_value=mock_client):
        from app.services.jira import get_ticket
        result = get_ticket("PROJ-1")

    assert result.startswith("[jira_get error:")


# ── search_tickets ─────────────────────────────────────────────────────────────

def test_search_tickets_returns_list():
    payload = {
        "issues": [
            {
                "key": "PROJ-1",
                "fields": {
                    "summary":  "Task one",
                    "status":   {"name": "To Do"},
                    "assignee": {"displayName": "Emilia"},
                    "priority": {"name": "Medium"},
                }
            }
        ]
    }
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = _mock_response(payload)

    with patch("httpx.Client", return_value=mock_client):
        from app.services.jira import search_tickets
        result = search_tickets('assignee = "Emilia"')

    assert "PROJ-1" in result
    assert "Task one" in result
    assert "Emilia" in result


def test_search_tickets_empty_returns_message():
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = _mock_response({"issues": []})

    with patch("httpx.Client", return_value=mock_client):
        from app.services.jira import search_tickets
        result = search_tickets("project = EMPTY")

    assert result == "No tickets found."


# ── update_status ──────────────────────────────────────────────────────────────

def test_update_status_applies_matching_transition():
    transitions_payload = {
        "transitions": [
            {"id": "11", "name": "To Do"},
            {"id": "21", "name": "In Progress"},
            {"id": "31", "name": "Done"},
        ]
    }
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value  = _mock_response(transitions_payload)
    mock_client.post.return_value = _mock_response({}, status_code=204)

    with patch("httpx.Client", return_value=mock_client):
        from app.services.jira import update_status
        result = update_status("PROJ-1", "In Progress")

    assert "In Progress" in result
    assert "PROJ-1" in result
    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args
    assert call_kwargs[1]["json"]["transition"]["id"] == "21"


def test_update_status_unknown_transition_lists_available():
    transitions_payload = {
        "transitions": [{"id": "11", "name": "To Do"}, {"id": "21", "name": "Done"}]
    }
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = _mock_response(transitions_payload)

    with patch("httpx.Client", return_value=mock_client):
        from app.services.jira import update_status
        result = update_status("PROJ-1", "Nonexistent")

    assert "[jira_status error:" in result
    assert "To Do" in result
    assert "Done" in result


# ── add_comment ────────────────────────────────────────────────────────────────

def test_add_comment_returns_confirmation():
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = _mock_response({"id": "10001"}, status_code=201)

    with patch("httpx.Client", return_value=mock_client):
        from app.services.jira import add_comment
        result = add_comment("PROJ-1", "Looks good, merging")

    assert "PROJ-1" in result
    assert "Comment added" in result


def test_add_comment_sends_adf_body():
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = _mock_response({"id": "10001"}, status_code=201)

    with patch("httpx.Client", return_value=mock_client):
        from app.services.jira import add_comment
        add_comment("PROJ-1", "Hello world")

    body = mock_client.post.call_args[1]["json"]["body"]
    assert body["type"] == "doc"
    assert body["content"][0]["content"][0]["text"] == "Hello world"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_jira_service.py -v
```
Expected: `ModuleNotFoundError: No module named 'app.services.jira'`

- [ ] **Step 3: Create `app/services/jira.py`**

```python
"""Jira Cloud REST API v3 wrapper."""
import httpx
from app import config


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=config.JIRA_URL,
        auth=(config.JIRA_EMAIL, config.JIRA_TOKEN),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        timeout=10.0,
    )


def _adf_to_text(doc) -> str:
    """Flatten Atlassian Document Format node to plain text."""
    if doc is None:
        return ""
    if isinstance(doc, str):
        return doc
    if isinstance(doc, dict):
        if doc.get("type") == "text":
            return doc.get("text", "")
        return " ".join(_adf_to_text(c) for c in doc.get("content", []))
    if isinstance(doc, list):
        return " ".join(_adf_to_text(c) for c in doc)
    return str(doc)


def get_ticket(ticket_id: str) -> str:
    try:
        with _client() as c:
            r = c.get(f"/rest/api/3/issue/{ticket_id}")
            r.raise_for_status()
            d = r.json()
            fields   = d["fields"]
            assignee = (fields.get("assignee") or {}).get("displayName", "Unassigned")
            comments = fields.get("comment", {}).get("comments", [])
            comment_lines = ""
            if comments:
                lines = [
                    f"  [{cm['author']['displayName']}]: {_adf_to_text(cm['body'])}"
                    for cm in comments[-5:]
                ]
                comment_lines = "\nComments:\n" + "\n".join(lines)
            return (
                f"Ticket: {ticket_id}\n"
                f"Summary: {fields.get('summary', '')}\n"
                f"Status: {fields['status']['name']}\n"
                f"Priority: {(fields.get('priority') or {}).get('name', 'None')}\n"
                f"Assignee: {assignee}\n"
                f"Description: {_adf_to_text(fields.get('description'))}"
                + comment_lines
            )
    except Exception as exc:
        return f"[jira_get error: {exc}]"


def search_tickets(jql: str) -> str:
    try:
        with _client() as c:
            r = c.get(
                "/rest/api/3/issue/search",
                params={"jql": jql, "maxResults": 20,
                        "fields": "summary,status,assignee,priority"},
            )
            r.raise_for_status()
            issues = r.json().get("issues", [])
        if not issues:
            return "No tickets found."
        lines = []
        for issue in issues:
            f        = issue["fields"]
            assignee = (f.get("assignee") or {}).get("displayName", "Unassigned")
            lines.append(
                f"{issue['key']}: {f.get('summary', '')} "
                f"| {f['status']['name']} | {assignee}"
            )
        return "\n".join(lines)
    except Exception as exc:
        return f"[jira_search error: {exc}]"


def get_tickets_by_assignee(name: str) -> str:
    return search_tickets(
        f'assignee = "{name}" AND resolution = Unresolved ORDER BY updated DESC'
    )


def get_comments(ticket_id: str) -> str:
    try:
        with _client() as c:
            r = c.get(f"/rest/api/3/issue/{ticket_id}/comment")
            r.raise_for_status()
            comments = r.json().get("comments", [])
        if not comments:
            return "No comments."
        lines = [
            f"[{cm['author']['displayName']} @ {cm['created'][:10]}]: "
            f"{_adf_to_text(cm['body'])}"
            for cm in comments
        ]
        return "\n".join(lines)
    except Exception as exc:
        return f"[jira_comment_read error: {exc}]"


def update_status(ticket_id: str, transition_name: str) -> str:
    try:
        with _client() as c:
            tr = c.get(f"/rest/api/3/issue/{ticket_id}/transitions")
            tr.raise_for_status()
            transitions = tr.json().get("transitions", [])
            match = next(
                (t for t in transitions if t["name"].lower() == transition_name.lower()),
                None,
            )
            if not match:
                available = ", ".join(t["name"] for t in transitions)
                return (
                    f"[jira_status error: transition '{transition_name}' not found. "
                    f"Available: {available}]"
                )
            r = c.post(
                f"/rest/api/3/issue/{ticket_id}/transitions",
                json={"transition": {"id": match["id"]}},
            )
            r.raise_for_status()
        return f"Ticket {ticket_id} status updated to '{transition_name}'."
    except Exception as exc:
        return f"[jira_status error: {exc}]"


def add_comment(ticket_id: str, body: str) -> str:
    try:
        with _client() as c:
            r = c.post(
                f"/rest/api/3/issue/{ticket_id}/comment",
                json={"body": {
                    "type":    "doc",
                    "version": 1,
                    "content": [{"type": "paragraph", "content": [
                        {"type": "text", "text": body}
                    ]}],
                }},
            )
            r.raise_for_status()
        return f"Comment added to {ticket_id}."
    except Exception as exc:
        return f"[jira_comment error: {exc}]"


def get_context_summary() -> str:
    try:
        with _client() as c:
            r1 = c.get(
                "/rest/api/3/issue/search",
                params={"jql": "resolution = Unresolved", "maxResults": 0, "fields": "status"},
            )
            r1.raise_for_status()
            total = r1.json().get("total", 0)

            r2 = c.get(
                "/rest/api/3/issue/search",
                params={"jql": 'status = "In Progress"', "maxResults": 0, "fields": "status"},
            )
            r2.raise_for_status()
            in_progress = r2.json().get("total", 0)

        return (
            f"JIRA SNAPSHOT:\n"
            f"  Open: {total}  |  In Progress: {in_progress}\n"
            f"  Use [JIRA_SEARCH:jql] to query, [JIRA_GET:TICKET-123] for details"
        )
    except Exception:
        return ""
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_jira_service.py -v
```
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add app/services/jira.py tests/test_jira_service.py
git commit -m "feat: add Jira service module"
```

---

## Task 3: Tool Tag Parsers

**Files:**
- Modify: `app/agents/tools.py` (before `return None, None` at line 258)
- Create: `tests/test_jira_tool_parser.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_jira_tool_parser.py


def test_parse_jira_get():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("let me check [JIRA_GET:PROJ-123]")
    assert tool == "jira_get"
    assert args["ticket_id"] == "PROJ-123"


def test_parse_jira_get_whitespace_stripped():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("[JIRA_GET:  PROJ-99  ]")
    assert tool == "jira_get"
    assert args["ticket_id"] == "PROJ-99"


def test_parse_jira_search_simple_jql():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call('[JIRA_SEARCH:assignee = "Reinhard"]')
    assert tool == "jira_search"
    assert args["jql"] == 'assignee = "Reinhard"'


def test_parse_jira_search_complex_jql():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("[JIRA_SEARCH:project = NEXUS AND status = 'In Progress']")
    assert tool == "jira_search"
    assert "NEXUS" in args["jql"]
    assert "In Progress" in args["jql"]


def test_parse_jira_status():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("[JIRA_STATUS:PROJ-123:In Progress]")
    assert tool == "jira_status"
    assert args["ticket_id"]  == "PROJ-123"
    assert args["transition"] == "In Progress"


def test_parse_jira_status_done():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("[JIRA_STATUS:NEXUS-7:Done]")
    assert tool == "jira_status"
    assert args["ticket_id"]  == "NEXUS-7"
    assert args["transition"] == "Done"


def test_parse_jira_comment():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("[JIRA_COMMENT:PROJ-123:Looks good, merging now]")
    assert tool == "jira_comment"
    assert args["ticket_id"] == "PROJ-123"
    assert args["body"]      == "Looks good, merging now"


def test_parse_jira_comment_multiword_body():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("[JIRA_COMMENT:NEXUS-5:This is a longer comment with details]")
    assert tool == "jira_comment"
    assert args["body"] == "This is a longer comment with details"


def test_unrelated_text_returns_none():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("Just a normal message with no tool call")
    assert tool is None
    assert args is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_jira_tool_parser.py -v
```
Expected: `8 failed` — `assert tool == "jira_get"` etc. all fail, tool is None

- [ ] **Step 3: Add parsers to `app/agents/tools.py`**

Find the line `return None, None` at the end of `parse_tool_call` (line ~258). Insert this block immediately before it:

```python
    m = re.search(r'\[JIRA_GET:\s*([^\]]+)\]', text)
    if m:
        return "jira_get", {"ticket_id": m.group(1).strip()}

    m = re.search(r'\[JIRA_SEARCH:\s*(.*?)\]', text, re.DOTALL)
    if m:
        return "jira_search", {"jql": m.group(1).strip()}

    m = re.search(r'\[JIRA_STATUS:\s*([^:\]]+):\s*([^\]]+)\]', text)
    if m:
        return "jira_status", {"ticket_id": m.group(1).strip(), "transition": m.group(2).strip()}

    m = re.search(r'\[JIRA_COMMENT:\s*([^:\]]+):\s*(.*?)\]', text, re.DOTALL)
    if m:
        return "jira_comment", {"ticket_id": m.group(1).strip(), "body": m.group(2).strip()}

```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_jira_tool_parser.py -v
```
Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
git add app/agents/tools.py tests/test_jira_tool_parser.py
git commit -m "feat: add Jira tool tag parsers"
```

---

## Task 4: Executor Dispatch

**Files:**
- Modify: `app/agents/executor.py`

- [ ] **Step 1: Add icon and label map entries**

In `_execute_tool`, find `icon_map` (around line 748). Add these entries:

```python
        "jira_get":     "🎫",
        "jira_search":  "🔎",
        "jira_status":  "🔄",
        "jira_comment": "💬",
```

In `label_map` (around line 768), add:

```python
        "jira_get":     "Fetching Jira Ticket",
        "jira_search":  "Searching Jira",
        "jira_status":  "Updating Jira Status",
        "jira_comment": "Adding Jira Comment",
```

- [ ] **Step 2: Add dispatch elif branches**

Find the last `elif tool_type == ...` block before the final `else` or end of the try block (around line 990). Add these four branches after it:

```python
        elif tool_type == "jira_get":
            from app.services import jira as jira_svc
            result = jira_svc.get_ticket(tool_args["ticket_id"])
        elif tool_type == "jira_search":
            from app.services import jira as jira_svc
            result = jira_svc.search_tickets(tool_args["jql"])
        elif tool_type == "jira_status":
            from app.services import jira as jira_svc
            result = jira_svc.update_status(tool_args["ticket_id"], tool_args["transition"])
        elif tool_type == "jira_comment":
            from app.services import jira as jira_svc
            result = jira_svc.add_comment(tool_args["ticket_id"], tool_args["body"])
```

- [ ] **Step 3: Verify the app still imports cleanly**

```bash
cd /home/subaru/projects/virtual-company
python3 -c "from app.agents.executor import _execute_tool; print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Run full test suite to catch regressions**

```bash
pytest tests/ -v --ignore=tests/test_browser_playwright.py -x -q 2>&1 | tail -20
```
Expected: no new failures

- [ ] **Step 5: Commit**

```bash
git add app/agents/executor.py
git commit -m "feat: wire Jira tool dispatch in executor"
```

---

## Task 5: CEO Persona & Context Injection

**Files:**
- Modify: `app/agents/definitions.py`
- Modify: `app/agents/executor.py`

- [ ] **Step 1: Add Jira tool docs to CEO persona in `app/agents/definitions.py`**

Find the `WEB TOOLS` section near the end of `_ceo_persona()` (around line 69). Add a new section immediately after the WEB TOOLS block (before the closing `"""`):

```python

JIRA TOOLS (read tickets, update status, add comments):
  [JIRA_GET:PROJ-123]                  — fetch ticket details + last 5 comments
  [JIRA_SEARCH:assignee = "Name"]      — search by JQL (assignee, project, status, etc.)
  [JIRA_STATUS:PROJ-123:In Progress]   — update status (use exact transition name from board)
  [JIRA_COMMENT:PROJ-123:your message] — add a comment to a ticket

  Examples:
    "show all Reinhard's tasks"  → [JIRA_SEARCH:assignee = "Reinhard van Astrea" AND resolution = Unresolved]
    "mark NEXUS-5 as done"       → [JIRA_STATUS:NEXUS-5:Done]
    "add comment to NEXUS-3"     → [JIRA_COMMENT:NEXUS-3:Reviewed and approved]
```

- [ ] **Step 2: Inject Jira snapshot into `_get_ceo_context()` in `app/agents/executor.py`**

Find `_get_ceo_context()` (lines 48–88). Replace the final `ctx = (...)` block with this:

```python
    # Jira snapshot
    try:
        from app.services import jira as jira_svc
        jira_snapshot = jira_svc.get_context_summary()
    except Exception:
        jira_snapshot = ""

    ctx = (
        f"\nSYSTEM SELF-AWARENESS:\n"
        f"Modifiable app files:\n{file_list}\n\n"
        f"Recent self-improvements:\n{changelog_str}\n"
    )
    if jira_snapshot:
        ctx += f"\n{jira_snapshot}\n"
    _ceo_context_cache = (now, ctx)
    return ctx
```

- [ ] **Step 3: Verify the app still imports cleanly**

```bash
python3 -c "from app.agents.definitions import _ceo_persona; print(_ceo_persona()[:200])"
```
Expected: prints the start of the CEO persona without errors

- [ ] **Step 4: Run full test suite**

```bash
pytest tests/ -v --ignore=tests/test_browser_playwright.py -x -q 2>&1 | tail -20
```
Expected: no new failures

- [ ] **Step 5: Commit**

```bash
git add app/agents/definitions.py app/agents/executor.py
git commit -m "feat: inject Jira context and tool docs into CEO persona"
```

---

## Task 6: End-to-End Smoke Test

- [ ] **Step 1: Verify Jira credentials work against the live API**

```bash
cd /home/subaru/projects/virtual-company
python3 -c "
from dotenv import load_dotenv; load_dotenv()
from app.services.jira import get_context_summary
print(get_context_summary())
"
```
Expected: prints a `JIRA SNAPSHOT:` block with real counts (or `""` if no tickets exist yet)

- [ ] **Step 2: Verify a JQL search works**

```bash
python3 -c "
from dotenv import load_dotenv; load_dotenv()
from app.services.jira import search_tickets
print(search_tickets('order by created DESC'))
"
```
Expected: either a list of tickets or `No tickets found.` — no error

- [ ] **Step 3: Run full test suite one final time**

```bash
pytest tests/ --ignore=tests/test_browser_playwright.py -q 2>&1 | tail -10
```
Expected: all previously passing tests still pass

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: Jira integration complete — read, search, status update, comments"
```
