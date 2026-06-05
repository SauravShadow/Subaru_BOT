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
