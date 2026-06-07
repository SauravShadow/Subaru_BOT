"""Delegation service — parses CEO output and spawns background worker tasks."""
import re

_DELEGATE_RE = re.compile(
    r'^\[DELEGATE:(\w+)\]\s*(.*?)(?=^\[DELEGATE:|^\[EMAIL_USER:|\Z)',
    re.DOTALL | re.MULTILINE
)
_STRAY_DELEGATE_TAG_RE = re.compile(r'\[DELEGATE:\w+\]')
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


def parse_emails(text: str) -> list[tuple]:
    results = []
    for m in _EMAIL_RE.finditer(text):
        header = m.group(1).strip()
        body   = m.group(2).strip()
        recipient = None
        subject   = header
        
        if "|" in header:
            parts = header.split("|", 1)
            recipient = parts[0].strip()
            subject   = parts[1].strip()
        elif "@" in header and "." in header:
            recipient = header
            subject   = "Notification"
            
        results.append((recipient, subject, body))
    return results


def clean_delegations(text: str) -> str:
    """Strip DELEGATE tags only — EMAIL_USER is handled by OutputPipeline."""
    cleaned = _DELEGATE_RE.sub("", text)
    cleaned = _STRAY_DELEGATE_TAG_RE.sub("", cleaned)
    return re.sub(r' {2,}', ' ', cleaned).strip()


def clean_response(text: str) -> str:
    """Legacy alias."""
    return clean_delegations(text)
