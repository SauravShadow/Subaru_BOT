"""EMAIL handler — converts [EMAIL_USER: addr | Subject] body to sent email."""
import re
import logging
from typing import Callable, Awaitable

logger  = logging.getLogger(__name__)
TAG     = "EMAIL_USER"
PATTERN = re.compile(
    r'\[EMAIL_USER:([^\]]+)\]\s*(.*?)(?=\[EMAIL_USER:|\[DELEGATE:|$)',
    re.DOTALL
)

Sender = Callable[[dict], Awaitable[None]]


def _parse_email_args(header: str, body: str) -> tuple[str | None, str, str]:
    header = header.strip()
    body   = body.strip()
    if "|" in header:
        parts     = header.split("|", 1)
        recipient = parts[0].strip()
        subject   = parts[1].strip()
    elif "@" in header and "." in header:
        recipient = header
        subject   = "Notification from Shadow Garden"
    else:
        recipient = None
        subject   = header
    return recipient, subject, body


def parse_emails(text: str) -> list[tuple]:
    """Extract (recipient, subject, body) tuples from [EMAIL_USER:...] tags."""
    results = []
    for m in PATTERN.finditer(text):
        recipient, subject, body = _parse_email_args(m.group(1), m.group(2))
        results.append((recipient, subject, body))
    return results


async def handle(args: str, agent_id: str, send: Sender) -> tuple[str, bool]:
    from app.services import email as email_svc
    if "\x00" in args:
        header, body = args.split("\x00", 1)
    else:
        header, body = args, ""
    recipient, subject, body = _parse_email_args(header, body)
    result = await email_svc.send_mail(f"[Shadow Garden] {subject}", body, to=recipient)
    await send({
        "type": "email_sent", "subject": subject,
        "ok": result.get("ok"), "error": result.get("error", ""),
    })
    return "", False
