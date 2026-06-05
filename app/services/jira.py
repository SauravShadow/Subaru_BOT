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
