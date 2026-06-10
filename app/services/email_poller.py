# app/services/email_poller.py
"""
Email poller — thin IMAP poll loop dispatching emails to email_graph.
~100 LOC replacing the 773-LOC 7-state machine.
"""
import asyncio
import logging
import re
from typing import Optional

from app import config
from app.services import email_inbox as inbox

logger = logging.getLogger(__name__)

_AUTOMATED_SENDERS = frozenset(["noreply", "no-reply", "mailer-daemon", "postmaster"])
_AUTOMATED_SUBJECTS = re.compile(
    r'(out of office|automatic reply|auto-reply|delivery status|undelivered mail)',
    re.IGNORECASE,
)


def _is_trusted(email_addr: str) -> bool:
    trusted = {config.USER_EMAIL, config.IMAP_USER, config.SMTP_USER}
    return email_addr.strip().lower() in {e.lower() for e in trusted if e}


def _is_automated_email(email: dict) -> bool:
    sender = email.get("from_email", "").lower()
    subject = email.get("subject", "").lower()
    if any(s in sender for s in _AUTOMATED_SENDERS):
        return True
    if _AUTOMATED_SUBJECTS.search(subject):
        return True
    return False


def _extract_reply_body(body: str) -> str:
    lines = body.splitlines()
    reply_lines = []
    for line in lines:
        if line.startswith(">") or (line.startswith("On ") and "wrote:" in line):
            break
        reply_lines.append(line)
    return "\n".join(reply_lines).strip()


async def _run_ceo_headless(prompt: str, task_id: str = "") -> str:
    """Run CEO agent without WebSocket, return full text response."""
    from app.agents.runner import run_claude_agent

    accumulated = []

    async def collect(data: dict) -> None:
        if data.get("type") == "assistant":
            content = data.get("message", {}).get("content", "")
            if content:
                accumulated.append(content)

    try:
        result = await run_claude_agent("ceo", prompt, collect)
        return result or "".join(accumulated)
    except Exception as exc:
        logger.warning("_run_ceo_headless error: %s", exc)
        return f"Error: {exc}"


async def poll_once(email_graph) -> None:
    """Fetch new emails and dispatch each to email_graph."""
    try:
        emails = await inbox.fetch_new_emails(max_emails=10)
    except Exception as exc:
        logger.warning("inbox fetch error: %s", exc)
        return

    for email in emails:
        if _is_automated_email(email):
            continue
        thread_id = f"email_{email['message_id']}"
        try:
            cfg = {"configurable": {"thread_id": thread_id}}
            graph_state = await email_graph.aget_state(cfg)
            if graph_state.next:
                reply_body = _extract_reply_body(email.get("body", ""))
                await email_graph.ainvoke({"user_reply": reply_body}, cfg)
            else:
                await email_graph.ainvoke(
                    {
                        "email": email,
                        "is_owner": _is_trusted(email.get("from_email", "")),
                        "sent_message_ids": [],
                    },
                    cfg,
                )
        except Exception as exc:
            logger.warning("email dispatch error for %s: %s", thread_id, exc)


async def start(email_graph) -> None:
    """Polling loop — runs indefinitely."""
    logger.info("email poller started")
    while True:
        await poll_once(email_graph)
        await asyncio.sleep(30)
