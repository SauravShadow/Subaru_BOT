"""
Enhanced email inbox — threaded replies, Message-ID tracking, mark-as-read.
"""
import asyncio
import email as email_lib
import imaplib
import smtplib
import uuid
from email.header import decode_header
from email.mime.text import MIMEText
from email.utils import parseaddr
from typing import Optional

from app import config


def _decode_str(raw) -> str:
    if not raw:
        return ""
    if isinstance(raw, str):
        parts = decode_header(raw)
    else:
        parts = decode_header(raw)
    return "".join(
        p.decode(cs or "utf-8", errors="replace") if isinstance(p, bytes) else p
        for p, cs in parts
    )


async def fetch_new_emails(max_emails: int = 10) -> list:
    """Fetch unread emails, mark them read, return full metadata with Message-ID."""
    if not all([config.IMAP_USER, config.IMAP_PASS]):
        return []

    def _do():
        results = []
        try:
            mail = imaplib.IMAP4_SSL(config.IMAP_HOST, config.IMAP_PORT_NUM)
            mail.login(config.IMAP_USER, config.IMAP_PASS)
            mail.select("INBOX")

            status, ids_raw = mail.search(None, "UNSEEN")
            if status != "OK" or not ids_raw[0]:
                mail.logout()
                return results

            for mid in ids_raw[0].split()[-max_emails:]:
                status2, msg_data = mail.fetch(mid, "(RFC822)")
                if status2 != "OK":
                    continue
                msg = email_lib.message_from_bytes(msg_data[0][1])

                subject    = _decode_str(msg.get("Subject", ""))
                from_raw   = msg.get("From", "")
                from_name, from_email = parseaddr(from_raw)
                from_name  = from_name or from_email

                message_id  = msg.get("Message-ID", "").strip()
                in_reply_to = msg.get("In-Reply-To", "").strip()
                references  = msg.get("References", "").strip()

                body_text = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            payload = part.get_payload(decode=True)
                            if payload:
                                body_text = payload.decode("utf-8", errors="replace")
                                break
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        body_text = payload.decode("utf-8", errors="replace")

                mail.store(mid, "+FLAGS", "\\Seen")

                results.append({
                    "message_id":  message_id,
                    "in_reply_to": in_reply_to,
                    "references":  references,
                    "subject":     subject,
                    "from_email":  from_email,
                    "from_name":   from_name,
                    "body":        body_text[:3000],
                    "date":        msg.get("Date", ""),
                })

            mail.logout()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("fetch_new_emails error: %s", exc)
        return results

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _do)


def _gen_message_id() -> str:
    return f"<{uuid.uuid4()}@shadow.garden>"


async def send_email(to: str, subject: str, body: str) -> dict:
    """Send a fresh email (not threaded). Returns {ok, message_id}."""
    if not all([config.SMTP_USER, config.SMTP_PASS]):
        return {"ok": False, "error": "SMTP not configured"}

    our_message_id = _gen_message_id()

    def _do():
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"]    = subject
        msg["From"]       = config.SMTP_USER
        msg["To"]         = to
        msg["Message-ID"] = our_message_id

        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT_NUM) as s:
            s.starttls()
            s.login(config.SMTP_USER, config.SMTP_PASS)
            s.sendmail(config.SMTP_USER, to, msg.as_string())
        return {"ok": True, "message_id": our_message_id}

    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _do)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "message_id": our_message_id}


async def send_reply(
    to: str,
    subject: str,
    body: str,
    in_reply_to: Optional[str] = None,
    references: Optional[str] = None,
) -> dict:
    """Send a threaded email reply. Returns {ok, message_id}."""
    if not all([config.SMTP_USER, config.SMTP_PASS]):
        return {"ok": False, "error": "SMTP not configured"}

    our_message_id = _gen_message_id()

    def _do():
        reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"]    = reply_subject
        msg["From"]       = config.SMTP_USER
        msg["To"]         = to
        msg["Message-ID"] = our_message_id
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
        refs = (references or "").strip()
        if in_reply_to:
            refs = (refs + " " + in_reply_to).strip()
        if refs:
            msg["References"] = refs

        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT_NUM) as s:
            s.starttls()
            s.login(config.SMTP_USER, config.SMTP_PASS)
            s.sendmail(config.SMTP_USER, to, msg.as_string())
        return {"ok": True, "message_id": our_message_id}

    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _do)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "message_id": our_message_id}
