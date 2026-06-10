"""
Email Command Channel — background poller and state machine.

States:
  verifying          — identity challenge sent to unknown sender
  planning           — CEO drafting plan (in flight)
  awaiting_approval  — plan sent, waiting for user go-ahead
  executing          — CEO/team executing the task
  awaiting_subdomain — (external users only) work done, asking for desired subdomain
  reporting          — report sent, waiting for feedback
  done               — complete
  rejected           — failed verification or user cancelled
"""
import asyncio
import logging
import re
from datetime import datetime
from typing import Optional

from app import config
from app.services import email_inbox as inbox
from app.state import manager as state

logger = logging.getLogger(__name__)

TRUSTED_EMAIL     = (config.USER_EMAIL or "").lower()
OWNER_EMAIL       = TRUSTED_EMAIL
VERIFICATION_WORD = "subaru"
APPROVAL_WORDS    = {
    "yes", "proceed", "go ahead", "go", "approved", "ok", "okay",
    "start", "do it", "execute", "sure", "fine", "yep", "yup",
    "alright", "confirm", "looks good", "sounds good",
}
POLL_INTERVAL = 5  # seconds


def _now() -> str:
    return datetime.utcnow().isoformat()


def _is_trusted(email_addr: str) -> bool:
    return email_addr.lower() == TRUSTED_EMAIL


# ── Automated-email detection ─────────────────────────────────────────────────

# Sender address patterns that are always automated (never real humans)
_NOREPLY_PATTERNS = (
    "noreply", "no-reply", "do-not-reply", "donotreply",
    "mailer-daemon", "postmaster", "bounce", "notifications@",
    "alert@", "alerts@", "support@jira", "notify@",
)

# Sender domains whose emails we should never process
_AUTOMATED_DOMAINS = {
    "atlassian.com", "atlassian.net", "jira.com",
    "github.com", "gitlab.com", "gitlab-org.gitlab.io",
    "slack.com", "trello.com", "confluence.atlassian.com",
    "accounts.google.com", "security.google.com", "no-reply.accounts.google.com",
    "workspace-noreply.google.com", "googlecloud.com",
    "amazonses.com", "sendgrid.net", "mailchimpapp.com",
    "hubspot.com", "zendesk.com", "servicenow.com",
    "linkedin.com", "twitter.com", "x.com", "facebook.com",
    "paypal.com", "stripe.com", "digitalocean.com",
    "microsoft.com", "azure.com", "azure-notifications.com",
    "notifications.dropbox.com", "figma.com",
}

# Subject patterns that indicate automated / notification emails
_AUTOMATED_SUBJECT_PATTERNS = (
    "[jira]", "[confluence]", "[github]", "[gitlab]", "[trello]",
    "activity on", "new comment on", "mentioned you in",
    "your google account", "sign-in attempt", "security alert",
    "new sign-in", "your password", "verify your email",
    "email confirmation", "account confirmation", "confirm your",
    "invoice from", "payment receipt", "order confirmation",
    "unsubscribe", "you have been added", "has been assigned",
    "build failed", "build succeeded", "pipeline",
    "access request", "access granted",
)


def _is_automated_email(email: dict) -> bool:
    """Return True for automated/system emails that should never be replied to."""
    from_addr = (email.get("from_email") or "").lower()
    subject   = (email.get("subject")    or "").lower()

    # Standard RFC headers that mark automated mail
    if email.get("auto_submitted") and email["auto_submitted"] not in ("", "no"):
        return True
    if email.get("precedence") in ("bulk", "list", "junk"):
        return True
    if email.get("list_id"):          # mailing list
        return True
    if "all" in email.get("x_auto_response_suppress", ""):
        return True

    # noreply-style address patterns
    if any(p in from_addr for p in _NOREPLY_PATTERNS):
        return True

    # Automated sender domain
    domain = from_addr.split("@")[-1] if "@" in from_addr else ""
    if domain in _AUTOMATED_DOMAINS:
        return True
    # Also catch subdomains, e.g. notifications.atlassian.com
    if any(domain.endswith("." + d) for d in _AUTOMATED_DOMAINS):
        return True

    # Subject-line heuristics
    if any(pat in subject for pat in _AUTOMATED_SUBJECT_PATTERNS):
        return True

    return False


def _extract_reply_body(body: str) -> str:
    """Strip quoted lines (>) and 'On ... wrote:' separators."""
    lines = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            continue
        if re.match(r"^On .{10,} wrote:$", stripped):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _looks_like_approval(text: str) -> bool:
    words = set(re.findall(r"\b\w+\b", text.lower()[:120]))
    return bool(words & APPROVAL_WORDS)


def _find_task_by_reply(in_reply_to: str, references: str) -> Optional[dict]:
    """Match an incoming reply to an existing email task via header threading."""
    ref_ids: set = set()
    if in_reply_to:
        ref_ids.add(in_reply_to.strip())
    if references:
        ref_ids.update(r.strip() for r in references.split())

    if not ref_ids:
        return None

    for task in state.email_tasks.values():
        sent = set(task.get("sent_message_ids", []))
        orig = task.get("original_message_id", "")
        if orig:
            sent.add(orig)
        if ref_ids & sent:
            return task
    return None


async def _run_ceo_headless(prompt: str, task_id: str = "") -> str:
    """
    Invoke CEO agent without a WebSocket and return accumulated text.
    Each email task gets its own isolated conversation history via a
    unique agent_id so concurrent tasks never bleed into each other.
    """
    from app.agents.runner import run_agent
    import json as _json

    # Use per-task agent ID so concurrent email tasks get isolated CEO histories
    agent_id = f"email_{task_id}" if task_id else "ceo"

    buffer: list = []

    async def capture(data: dict):
        if data.get("type") == "assistant":
            for blk in data.get("message", {}).get("content", []):
                if isinstance(blk, dict) and blk.get("type") == "text":
                    buffer.append(blk["text"])
        elif "_raw_json" in data:
            try:
                obj = _json.loads(data["_raw_json"])
                if obj.get("type") == "assistant":
                    for blk in obj.get("message", {}).get("content", []):
                        if isinstance(blk, dict) and blk.get("type") == "text":
                            buffer.append(blk["text"])
            except Exception:
                pass

    try:
        await run_agent(agent_id, prompt, capture)
    except Exception as exc:
        logger.error("_run_ceo_headless failed (task=%s): %s", task_id, exc)
        return f"[Agent error: {exc}]"

    return "".join(buffer).strip()


# ── State transitions ──────────────────────────────────────────────────────────

async def _send_verification_challenge(task: dict):
    task["state"]   = "verifying"
    task["updated"] = _now()
    state.save_state()

    body = (
        "Hey there! 👋\n\n"
        "I received your message and I'm happy to help — but first, "
        "a quick identity check so I know you're authorised.\n\n"
        "Saurav usually goes by another name around here. "
        "What is it? 😄\n\n"
        "(Hint: it's the CEO's first name at Shadow Garden)\n\n"
        "— Shadow Garden Command Center"
    )
    result = await inbox.send_reply(
        to=task["from_email"],
        subject=task["subject"],
        body=body,
        in_reply_to=task["original_message_id"],
    )
    if result.get("ok"):
        task["sent_message_ids"].append(result["message_id"])
        task["updated"] = _now()
        state.save_state()
    logger.info("Verification challenge sent → %s", task["from_email"])


async def _run_planning(task: dict):
    task["state"]   = "planning"
    task["updated"] = _now()
    state.save_state()
    logger.info("Planning email task: %s", task["subject"])

    prompt = (
        f"An email task came in from {task['from_name']} ({task['from_email']}).\n\n"
        f"Subject: {task['subject']}\n\n"
        f"Message:\n{task['body']}\n\n"
        "Please:\n"
        "1. Briefly summarise what's being requested (1-2 sentences)\n"
        "2. Draft a clear, concise execution plan\n"
        "3. List any clarifying questions you need before starting "
        "(if none are needed, state you're ready to proceed immediately)\n\n"
        "Keep it concise and professional. "
        "Do NOT execute anything yet — just plan and ask questions."
    )

    plan_text = await _run_ceo_headless(prompt, task_id=task["id"])
    if not plan_text:
        plan_text = "I've reviewed your request and I'm ready to proceed. Please confirm and I'll start immediately."

    task["plan"]    = plan_text
    task["state"]   = "awaiting_approval"
    task["updated"] = _now()
    state.save_state()

    first_name = task["from_name"].split()[0] if task["from_name"] else ""
    body = (
        f"Hi{' ' + first_name if first_name else ''}! 👋\n\n"
        "I've reviewed your request. Here's my plan:\n\n"
        "─────────────────────────\n\n"
        f"{plan_text}\n\n"
        "─────────────────────────\n\n"
        "Please reply to confirm (or answer any questions above) "
        "and I'll get the team started right away.\n\n"
        "— Subaru Natsuki, CEO · Shadow Garden"
    )
    result = await inbox.send_reply(
        to=task["from_email"],
        subject=task["subject"],
        body=body,
        in_reply_to=task["original_message_id"],
        references=" ".join(task["sent_message_ids"]),
    )
    if result.get("ok"):
        task["sent_message_ids"].append(result["message_id"])
        task["updated"] = _now()
        state.save_state()
    logger.info("Plan sent → %s", task["from_email"])


async def _run_execution(task: dict, approval_text: str):
    task["state"]      = "executing"
    task["user_reply"] = approval_text
    task["updated"]    = _now()
    state.save_state()
    logger.info("Executing email task: %s", task["subject"])

    is_owner = task.get("is_owner", True)

    if is_owner:
        prompt = (
            f"Execute the following email task.\n\n"
            f"Requested by: {task['from_name']} ({task['from_email']})\n"
            f"Subject: {task['subject']}\n"
            f"Original request:\n{task['body']}\n\n"
            f"Agreed plan:\n{task['plan']}\n\n"
            f"User confirmation / clarification:\n{approval_text}\n\n"
            "Execute this now using your tools.\n\n"
            "If this task involves building or deploying a website, app, or service, "
            "follow these MANDATORY DEPLOYMENT STEPS:\n\n"
            "1. BUILD: Write all project files to /workspace/<project-name>/\n\n"
            "2. DOCKERFILE: Write a Dockerfile before launching.\n"
            "   Minimum:\n"
            "     FROM python:3.12-slim\n"
            "     WORKDIR /app\n"
            "     COPY requirements.txt .\n"
            "     RUN pip install --no-cache-dir -r requirements.txt\n"
            "     COPY . .\n"
            "     EXPOSE <port>\n"
            "     CMD [\"python3\", \"-m\", \"uvicorn\", \"main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"<port>\"]\n\n"
            "3. CHECK PORTS: GET http://host.docker.internal:3030/api/port-registry\n"
            "   Pick an unused port from 8100-8999.\n\n"
            "4. BUILD IMAGE via sidecar:\n"
            "   POST http://host.docker.internal:3030/api/run-host-command\n"
            "   {\"cmd\": \"docker build -t <project-name> /home/subaru/projects/<project-name>\"}\n\n"
            "5. LAUNCH via sidecar — include subdomain to auto-wire Cloudflare DNS + tunnel:\n"
            "   POST http://host.docker.internal:3030/api/start-service\n"
            "   {\"name\":\"<project-name>\",\"cwd\":\"/workspace/<project-name>\","
            "\"cmd\":\"docker run --name <project-name> -p <port>:<port> --restart unless-stopped <project-name>\","
            "\"port\":<port>,\"subdomain\":\"<url-safe-project-name>\"}\n"
            "   The subdomain must be URL-safe (lowercase letters, digits, hyphens only).\n"
            "   Derive it from the project name (e.g. 'expense-tracker' → subdomain 'expense').\n"
            "   Including the subdomain auto-wires Cloudflare and makes the site live at "
            "<subdomain>.saurav-info.xyz immediately.\n\n"
            "6. VERIFY: curl http://127.0.0.1:<port>/\n\n"
            "When done, write a full completion report. "
            "If deployed, include the live URL (https://<subdomain>.saurav-info.xyz) prominently."
        )
    else:
        prompt = (
            f"Execute the following email task from an external user.\n\n"
            f"Requested by: {task['from_name']} ({task['from_email']})\n"
            f"Subject: {task['subject']}\n"
            f"Original request:\n{task['body']}\n\n"
            f"Agreed plan:\n{task['plan']}\n\n"
            f"User confirmation / clarification:\n{approval_text}\n\n"
            "Execute this now using your tools and build the project completely.\n\n"
            "MANDATORY STEPS — in this order:\n\n"
            "1. BUILD: Write all project files to /workspace/<project-name>/\n\n"
            "2. DOCKERFILE: Every project MUST have a Dockerfile. Write it before launching.\n"
            "   Minimum:\n"
            "     FROM python:3.12-slim\n"
            "     WORKDIR /app\n"
            "     COPY requirements.txt .\n"
            "     RUN pip install --no-cache-dir -r requirements.txt\n"
            "     COPY . .\n"
            "     EXPOSE <port>\n"
            "     CMD [\"python3\", \"-m\", \"uvicorn\", \"main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"<port>\"]\n"
            "   Also use env vars for any file paths (e.g. DB_PATH = os.environ.get('DB_PATH', 'app.db'))\n\n"
            "3. CHECK PORTS: curl -s http://host.docker.internal:3030/api/services\n"
            "   Pick an unused port from 8100-8999.\n\n"
            "4. LAUNCH on the HOST via sidecar (NOT inside this container):\n"
            "   curl -s -X POST http://host.docker.internal:3030/api/start-service \\\n"
            "     -H 'Content-Type: application/json' \\\n"
            "     -d '{\"name\":\"<name>\",\"cwd\":\"/workspace/<dir>\",\"cmd\":\"python3 -m uvicorn main:app --host 0.0.0.0 --port <port>\",\"port\":<port>}'\n\n"
            "5. VERIFY: curl -s http://127.0.0.1:<port>/  (use 127.0.0.1, not localhost)\n\n"
            "At the very END of your response, include exactly this line:\n"
            "PORT_USED: <port_number>\n\n"
            "Write a brief technical summary of what was built and the port used."
        )

    result_text = await _run_ceo_headless(prompt, task_id=task["id"])
    if not result_text:
        result_text = "Task executed as requested."

    task["execution_result"] = result_text
    task["updated"]          = _now()

    if is_owner:
        task["state"] = "reporting"
        state.save_state()

        first_name = task["from_name"].split()[0] if task["from_name"] else ""
        body = (
            f"Hi{' ' + first_name if first_name else ''}! ✅\n\n"
            "Your task is complete. Here's the full report:\n\n"
            "─────────────────────────\n\n"
            f"{result_text}\n\n"
            "─────────────────────────\n\n"
            "Please check the results and reply with your feedback "
            "or any changes you'd like made.\n\n"
            "— Subaru Natsuki, CEO · Shadow Garden"
        )
        result = await inbox.send_reply(
            to=task["from_email"],
            subject=task["subject"],
            body=body,
            in_reply_to=task["original_message_id"],
            references=" ".join(task["sent_message_ids"]),
        )
        if result.get("ok"):
            task["sent_message_ids"].append(result["message_id"])
            task["updated"] = _now()
            state.save_state()
        logger.info("Report sent → %s", task["from_email"])
    else:
        # External user — extract port, then ask for subdomain
        port_match = re.search(r"PORT_USED:\s*(\d+)", result_text)
        task["port_used"] = port_match.group(1) if port_match else "unknown"
        task["state"]     = "awaiting_subdomain"
        state.save_state()

        first_name = task["from_name"].split()[0] if task["from_name"] else ""
        body = (
            f"Hey{' ' + first_name if first_name else ''}! 🎉\n\n"
            "Your project is built and running! To get it live at a proper URL, "
            "I need one quick thing from you:\n\n"
            "What do you want in front of **____.saurav-info.xyz**?\n\n"
            "(For example, reply 'myapp' and your site would be at myapp.saurav-info.xyz)\n\n"
            "Once you reply, I'll sort out the rest!\n\n"
            "— Subaru Natsuki, CEO · Shadow Garden"
        )
        result = await inbox.send_reply(
            to=task["from_email"],
            subject=task["subject"],
            body=body,
            in_reply_to=task["original_message_id"],
            references=" ".join(task["sent_message_ids"]),
        )
        if result.get("ok"):
            task["sent_message_ids"].append(result["message_id"])
            task["updated"] = _now()
            state.save_state()
        logger.info("Subdomain request sent → %s (port=%s)", task["from_email"], task["port_used"])


async def _handle_subdomain_reply(email: dict, task: dict, reply_body: str):
    """External user replied with subdomain — wire Cloudflare directly, send casual report."""
    # Extract first word and sanitise to URL-safe subdomain
    raw = reply_body.strip().split()[0].lower() if reply_body.strip() else "site"
    subdomain = re.sub(r"[^a-z0-9-]", "", raw)[:30] or "site"

    # Check subdomain collision against the port registry via sidecar
    try:
        import httpx as _httpx
        _cf_client = _httpx.AsyncClient()
        r = await _cf_client.get(
            f"http://host.docker.internal:3030/api/check-subdomain/{subdomain}", timeout=3.0
        )
        result_data = r.json()
        if not result_data.get("available"):
            # Suffix with first chars of sender name to make it unique
            suffix = re.sub(r"[^a-z0-9]", "", task.get("from_name", "user").lower())[:4]
            subdomain = f"{subdomain}{suffix}" if suffix else f"{subdomain}1"
    except Exception:
        pass  # Can't reach sidecar — proceed anyway

    task["subdomain"] = subdomain
    task["state"]     = "reporting"
    task["updated"]   = _now()
    state.save_state()

    port = task.get("port_used", "unknown")

    # Wire Cloudflare tunnel directly via sidecar API — no need to email Saurav
    cf_ok = False
    cf_msg = "Cloudflare: not configured"
    if port != "unknown":
        try:
            import httpx as _httpx
            _cf_client2 = _httpx.AsyncClient()
            cf_resp = await _cf_client2.post(
                "http://host.docker.internal:3030/api/register-subdomain",
                json={"port": int(port), "subdomain": subdomain, "service": task["subject"][:40]},
                timeout=15.0,
            )
            cf_data = cf_resp.json()
            cf_ok  = cf_data.get("ok", False)
            cf_msg = cf_data.get("message", str(cf_data))
        except Exception as exc:
            cf_msg = f"Cloudflare wiring failed: {exc}"
    logger.info("[cloudflare] %s", cf_msg)

    # Send casual reply to the external user — site is already live
    url = f"{subdomain}.saurav-info.xyz"
    first_name = task["from_name"].split()[0] if task["from_name"] else ""
    status_note = f"it's live at **{url}**" if cf_ok else f"it's running — {url} should be up shortly"
    casual_body = (
        f"Hey{' ' + first_name if first_name else ''}! All done 🚀\n\n"
        f"Your site is built and {status_note}!\n\n"
        f"We got everything sorted — it's looking great!\n\n"
        f"Want me to walk you through how it all works under the hood? Just say the word!\n\n"
        f"— Subaru Natsuki, CEO · Shadow Garden"
    )
    result = await inbox.send_reply(
        to=task["from_email"],
        subject=task["subject"],
        body=casual_body,
        in_reply_to=email["message_id"],
        references=" ".join(task["sent_message_ids"]),
    )
    if result.get("ok"):
        task["sent_message_ids"].append(result["message_id"])
        task["updated"] = _now()
        state.save_state()
    logger.info("Casual report sent → %s (subdomain: %s.saurav-info.xyz)", task["from_email"], subdomain)


async def _handle_reply(email: dict, task: dict):
    """Route an incoming reply to the correct state handler."""
    reply_body = _extract_reply_body(email["body"])
    logger.info(
        "Reply for task '%s' (state=%s) from %s",
        task["subject"], task["state"], email["from_email"],
    )

    if task["state"] == "verifying":
        words = set(re.findall(r"\b\w+\b", reply_body.lower()))
        if VERIFICATION_WORD in words:
            task["verified"] = True
            await _run_planning(task)
        else:
            body = (
                "Hmm, that's not quite right! 🤔\n\n"
                "Think Re:Zero protagonist — the guy who always comes back. 😄\n\n"
                "— Shadow Garden Command Center"
            )
            result = await inbox.send_reply(
                to=task["from_email"],
                subject=task["subject"],
                body=body,
                in_reply_to=email["message_id"],
                references=" ".join(task["sent_message_ids"]),
            )
            if result.get("ok"):
                task["sent_message_ids"].append(result["message_id"])
                task["updated"] = _now()
                state.save_state()

    elif task["state"] == "awaiting_approval":
        if _looks_like_approval(reply_body):
            await _run_execution(task, reply_body)
        else:
            # User asked follow-up questions — re-plan
            task["state"]   = "planning"
            task["updated"] = _now()
            state.save_state()

            prompt = (
                f"The user replied to your plan with questions or changes.\n\n"
                f"Original request: {task['subject']}\n"
                f"Your previous plan:\n{task['plan']}\n\n"
                f"User's response:\n{reply_body}\n\n"
                "Address their points and provide an updated plan. "
                "Ask if they're ready to proceed."
            )
            new_plan = await _run_ceo_headless(prompt, task_id=task["id"])
            task["plan"]    = new_plan
            task["state"]   = "awaiting_approval"
            task["updated"] = _now()
            state.save_state()

            body = (
                "Updated plan based on your feedback:\n\n"
                "─────────────────────────\n\n"
                f"{new_plan}\n\n"
                "─────────────────────────\n\n"
                "Reply 'yes' or 'proceed' when you're happy to go ahead.\n\n"
                "— Subaru Natsuki, CEO · Shadow Garden"
            )
            result = await inbox.send_reply(
                to=task["from_email"],
                subject=task["subject"],
                body=body,
                in_reply_to=email["message_id"],
                references=" ".join(task["sent_message_ids"]),
            )
            if result.get("ok"):
                task["sent_message_ids"].append(result["message_id"])
                task["updated"] = _now()
                state.save_state()

    elif task["state"] == "reporting":
        task["feedback"] = reply_body
        task["state"]    = "done"
        task["updated"]  = _now()
        state.save_state()

        body = (
            "Thank you for the feedback! 🙏\n\n"
            "Noted. Just send a new email whenever you need anything next.\n\n"
            "— Subaru Natsuki, CEO · Shadow Garden"
        )
        result = await inbox.send_reply(
            to=task["from_email"],
            subject=task["subject"],
            body=body,
            in_reply_to=email["message_id"],
            references=" ".join(task["sent_message_ids"]),
        )
        if result.get("ok"):
            task["sent_message_ids"].append(result["message_id"])
            task["updated"] = _now()
            state.save_state()
        logger.info("Task '%s' done.", task["subject"])

    elif task["state"] == "awaiting_subdomain":
        await _handle_subdomain_reply(email, task, reply_body)

    elif task["state"] in ("executing", "planning"):
        logger.info("Reply received while task is busy (state=%s) — queued as clarification.", task["state"])

    else:
        logger.info("Reply for task in terminal state '%s' — ignored.", task["state"])


async def _process_new_email(email: dict):
    """Handle a brand-new inbound email (not a reply to a known task)."""
    from_email = email["from_email"]
    subject    = email["subject"]
    message_id = email["message_id"] or f"noid-{_now()}"

    logger.info("New email from %s: %s", from_email, subject)

    task = {
        "id":                  message_id,
        "subject":             subject,
        "from_email":          from_email,
        "from_name":           email.get("from_name", from_email),
        "body":                email["body"],
        "state":               "received",
        "original_message_id": message_id,
        "sent_message_ids":    [],
        "plan":                None,
        "user_reply":          None,
        "execution_result":    None,
        "feedback":            None,
        "verified":            _is_trusted(from_email),
        "is_owner":            _is_trusted(from_email),
        "created":             _now(),
        "updated":             _now(),
    }
    state.email_tasks[message_id] = task
    state.save_state()

    if task["verified"]:
        await _run_planning(task)
    else:
        await _send_verification_challenge(task)


async def _safe_process(em: dict):
    """Process one email, catching exceptions so one bad email can't kill the whole poll."""
    if _is_automated_email(em):
        logger.info(
            "Skipping automated/system email from %s — subject: %s",
            em.get("from_email"), em.get("subject"),
        )
        return
    try:
        existing = _find_task_by_reply(
            em.get("in_reply_to", ""),
            em.get("references", ""),
        )
        if existing:
            await _handle_reply(em, existing)
        else:
            await _process_new_email(em)
    except Exception as exc:
        logger.error("Error processing email from %s: %s", em.get("from_email"), exc)


async def _check_approval_replies(emails: list) -> None:
    """Scan incoming emails for APPROVE/DENY responses and process them."""
    from app.services.self_heal import apply_approval, deny_approval, load_approvals
    from app.api.websocket import broadcast_event

    approvals = load_approvals()
    if not approvals:
        return

    pending_ids = {k for k, v in approvals.items() if v.get("status") == "pending"}
    if not pending_ids:
        return

    for email_item in emails:
        text = (
            str(email_item.get("subject", "")) + " " +
            str(email_item.get("body",    ""))
        ).upper()

        for approval_id in list(pending_ids):
            if f"APPROVE {approval_id}" in text:
                ok, msg = apply_approval(approval_id)
                if ok:
                    await broadcast_event({
                        "type":        "approval_applied",
                        "approval_id": approval_id,
                        "message":     msg,
                        "source":      "email",
                    })
                    logger.info("Approval %s applied via email reply", approval_id)
                    pending_ids.discard(approval_id)
                break
            elif f"DENY {approval_id}" in text:
                ok, msg = deny_approval(approval_id)
                if ok:
                    await broadcast_event({
                        "type":        "approval_denied",
                        "approval_id": approval_id,
                        "message":     msg,
                        "source":      "email",
                    })
                    logger.info("Approval %s denied via email reply", approval_id)
                    pending_ids.discard(approval_id)
                break


async def poll_once():
    """Single poll cycle. All emails in a batch are dispatched concurrently."""
    try:
        emails = await inbox.fetch_new_emails(max_emails=10)
        if emails:
            # Check for approval replies first (fast, non-destructive)
            await _check_approval_replies(emails)
            # Run all emails in parallel — each task uses its own CEO history
            await asyncio.gather(*[_safe_process(em) for em in emails])
    except Exception as exc:
        logger.error("poll_once error: %s", exc)


async def _recover_stuck_tasks():
    """
    On startup: find any tasks left in 'executing' or 'planning' state from
    a previous run that was interrupted. Re-trigger them so users aren't abandoned.
    """
    stuck = [
        t for t in state.email_tasks.values()
        if t.get("state") in ("executing", "planning")
    ]
    if not stuck:
        return

    logger.warning("Found %d stuck task(s) from previous run — recovering…", len(stuck))
    for task in stuck:
        logger.info("Recovering task '%s' (state=%s) for %s",
                    task["subject"], task["state"], task["from_email"])
        try:
            if task["state"] == "planning":
                # Re-run planning from scratch
                await _run_planning(task)
            elif task["state"] == "executing":
                # Re-execute with original approval
                approval = task.get("user_reply") or "proceed"
                # Reset to awaiting_approval first so _run_execution transitions cleanly
                task["state"] = "awaiting_approval"
                state.save_state()
                await _run_execution(task, approval)
        except Exception as exc:
            logger.error("Recovery failed for task '%s': %s", task["subject"], exc)
            # Fall back: email the user that their task will be retried
            try:
                first_name = task["from_name"].split()[0] if task.get("from_name") else ""
                await inbox.send_reply(
                    to=task["from_email"],
                    subject=task["subject"],
                    body=(
                        f"Hi{' ' + first_name if first_name else ''}! Just a heads-up —\n\n"
                        "Our system restarted while working on your request. "
                        "I'm picking it back up right now. "
                        "You'll hear from me again shortly!\n\n"
                        "— Subaru Natsuki, CEO · Shadow Garden"
                    ),
                    in_reply_to=task["original_message_id"],
                    references=" ".join(task.get("sent_message_ids", [])),
                )
            except Exception:
                pass


async def start():
    """Background polling loop — launched on app startup."""
    logger.info("Email poller started (interval=%ds, watching %s)", POLL_INTERVAL, config.IMAP_USER)
    # Recover any tasks that were mid-flight when the system last stopped
    await _recover_stuck_tasks()
    while True:
        await poll_once()
        await asyncio.sleep(POLL_INTERVAL)
