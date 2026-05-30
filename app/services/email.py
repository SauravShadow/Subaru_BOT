"""Email service — SMTP send + IMAP read."""
import asyncio
import imaplib
import email as email_lib
import json
import smtplib
from email.header import decode_header
from email.mime.text import MIMEText

from app import config


async def send_mail(subject: str, body: str, to: str = None) -> dict:
    if not all([config.SMTP_USER, config.SMTP_PASS]):
        return {"ok": False, "error": "SMTP not configured"}

    recipient = to if to else config.USER_EMAIL
    if not recipient:
        return {"ok": False, "error": "No recipient email specified"}

    def _do():
        msg            = MIMEText(body)
        msg["Subject"] = subject
        msg["From"]    = config.SMTP_USER
        msg["To"]      = recipient
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT_NUM) as s:
            s.starttls()
            s.login(config.SMTP_USER, config.SMTP_PASS)
            s.sendmail(config.SMTP_USER, recipient, msg.as_string())

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _do)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def read_emails(
    max_emails: int = 10,
    folder: str = "INBOX",
    unread_only: bool = True,
) -> dict:
    if not all([config.IMAP_USER, config.IMAP_PASS]):
        return {"ok": False, "error": "IMAP not configured"}

    def _do():
        result: dict = {"ok": True, "emails": []}
        try:
            mail = imaplib.IMAP4_SSL(config.IMAP_HOST, config.IMAP_PORT_NUM)
            mail.login(config.IMAP_USER, config.IMAP_PASS)
            mail.select(folder)

            criteria = "UNSEEN" if unread_only else "ALL"
            status, ids_raw = mail.search(None, criteria)
            if status != "OK" or not ids_raw[0]:
                mail.logout()
                return result

            for mid in ids_raw[0].split()[-max_emails:]:
                status2, msg_data = mail.fetch(mid, "(RFC822)")
                if status2 != "OK":
                    continue
                msg = email_lib.message_from_bytes(msg_data[0][1])

                # Decode subject
                raw_subj = msg.get("Subject", "")
                subject  = "".join(
                    p.decode(cs or "utf-8", errors="replace") if isinstance(p, bytes) else p
                    for p, cs in decode_header(raw_subj)
                )

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

                result["emails"].append({
                    "subject": subject,
                    "from":    msg.get("From", ""),
                    "date":    msg.get("Date", ""),
                    "body":    body_text[:2000],
                })
            mail.logout()
        except Exception as exc:
            result["ok"]    = False
            result["error"] = str(exc)
        return result

    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _do)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
