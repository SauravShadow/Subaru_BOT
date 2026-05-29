"""Delegation service — parses CEO output and spawns background worker tasks."""
import re

_DELEGATE_RE = re.compile(
    r'\[DELEGATE:(\w+)\]\s*(.*?)(?=\[DELEGATE:|\[EMAIL_USER:|$)', re.DOTALL
)
_EMAIL_RE = re.compile(
    r'\[EMAIL_USER:([^\]]+)\]\s*(.*?)(?=\[DELEGATE:|\[EMAIL_USER:|$)', re.DOTALL
)


def parse_delegations(text: str) -> list[tuple[str, str]]:
    from app.agents.definitions import all_agents
    agents = all_agents()
    return [
        (m.group(1).strip(), m.group(2).strip())
        for m in _DELEGATE_RE.finditer(text)
        if m.group(1).strip() in agents
    ]


def parse_emails(text: str) -> list[tuple[str, str]]:
    return [
        (m.group(1).strip(), m.group(2).strip())
        for m in _EMAIL_RE.finditer(text)
    ]


def clean_response(text: str) -> str:
    return _DELEGATE_RE.sub("", _EMAIL_RE.sub("", text)).strip()
