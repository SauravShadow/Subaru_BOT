# app/graph/email/nodes.py
"""Email graph nodes — 7-node state machine."""
import asyncio
import logging
import re
from typing import Literal

from langchain_core.runnables import RunnableConfig

from app import config
from app.graph.state import EmailState
from app.services import email_inbox as inbox

logger = logging.getLogger(__name__)


def _is_trusted(email_addr: str) -> bool:
    trusted = {
        config.USER_EMAIL,
        config.IMAP_USER,
        config.SMTP_USER,
    }
    return email_addr.strip().lower() in {e.lower() for e in trusted if e}


def route_after_verify(state: EmailState) -> Literal["plan_node", "send_challenge_node"]:
    return "plan_node" if state["is_owner"] else "send_challenge_node"


def route_after_execute(state: EmailState) -> Literal["report_node", "ask_subdomain_node"]:
    if state.get("port_used"):
        return "ask_subdomain_node"
    return "report_node"


async def verify_node(state: EmailState, config_: RunnableConfig) -> dict:
    email = state["email"]
    is_owner = _is_trusted(email.get("from_email", ""))
    return {"is_owner": is_owner, "verified": is_owner}


async def send_challenge_node(state: EmailState, config_: RunnableConfig) -> dict:
    email = state["email"]
    try:
        msg_id = await inbox.send_reply(
            original=email,
            body=(
                "I received your message. To verify your identity, "
                "please reply with the word VERIFY."
            ),
            subject=f"Re: {email.get('subject', 'Your request')} [verification]",
        )
        return {"sent_message_ids": state.get("sent_message_ids", []) + [msg_id]}
    except Exception as exc:
        logger.warning("send_challenge error: %s", exc)
        return {}


async def plan_node(state: EmailState, config_: RunnableConfig) -> dict:
    """Run the CEO headless to create a plan, email it for approval."""
    from app.services.email_poller import _run_ceo_headless
    email = state["email"]
    subject = email.get("subject", "task")
    body = email.get("body", "")
    task_prompt = f"Email task: {subject}\n\nDetails:\n{body}"

    try:
        plan = await _run_ceo_headless(task_prompt, task_id=email.get("message_id", ""))
        msg_id = await inbox.send_reply(
            original=email,
            body=f"Here is my plan:\n\n{plan}\n\nReply APPROVE to proceed or DENY to cancel.",
            subject=f"Re: {subject} [plan approval needed]",
        )
        return {"plan": plan, "sent_message_ids": state.get("sent_message_ids", []) + [msg_id]}
    except Exception as exc:
        logger.warning("plan_node error: %s", exc)
        return {"plan": f"Error creating plan: {exc}"}


async def execute_node(state: EmailState, config_: RunnableConfig) -> dict:
    """Execute the approved plan."""
    from app.services.email_poller import _run_ceo_headless
    plan = state.get("plan", "")
    email = state["email"]
    try:
        result = await _run_ceo_headless(
            f"Execute this plan:\n{plan}",
            task_id=email.get("message_id", "exec"),
        )
        pm = re.search(r'PORT:(\d+)', result)
        port_match = pm.group(1) if pm else ""
        return {"execution_result": result, "port_used": port_match}
    except Exception as exc:
        logger.warning("execute_node error: %s", exc)
        return {"execution_result": f"Error: {exc}", "port_used": ""}


async def report_node(state: EmailState, config_: RunnableConfig) -> dict:
    email = state["email"]
    result = state.get("execution_result", "No result.")
    try:
        msg_id = await inbox.send_reply(
            original=email,
            body=f"Task complete.\n\n{result[:1500]}",
            subject=f"Re: {email.get('subject', 'task')} [done]",
        )
        return {"sent_message_ids": state.get("sent_message_ids", []) + [msg_id]}
    except Exception as exc:
        logger.warning("report_node error: %s", exc)
        return {}


async def ask_subdomain_node(state: EmailState, config_: RunnableConfig) -> dict:
    email = state["email"]
    port = state.get("port_used", "")
    try:
        msg_id = await inbox.send_reply(
            original=email,
            body=(
                f"Your service is running on port {port}. "
                "Reply with your desired subdomain (e.g. 'myapp') "
                "and I'll wire up a Cloudflare tunnel."
            ),
            subject=f"Re: {email.get('subject', 'task')} [subdomain needed]",
        )
        return {"sent_message_ids": state.get("sent_message_ids", []) + [msg_id]}
    except Exception as exc:
        logger.warning("ask_subdomain_node error: %s", exc)
        return {}


async def wire_cf_node(state: EmailState, config_: RunnableConfig) -> dict:
    """Wire a Cloudflare tunnel via the operations sidecar API."""
    email = state["email"]
    subdomain = state.get("user_reply", "").strip().split()[0] if state.get("user_reply", "").strip() else ""
    port = state.get("port_used", "")
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "http://127.0.0.1:8899/tunnel",
                json={"subdomain": subdomain, "port": int(port) if port else 0},
            )
        result_text = resp.text
    except Exception as exc:
        logger.warning("wire_cf tunnel API error: %s", exc)
        result_text = f"Tunnel wiring failed: {exc}"
    try:
        msg_id = await inbox.send_reply(
            original=email,
            body=f"Tunnel result:\n{result_text}\n\nSubdomain: {subdomain}.shadowgarden.app → port {port}",
            subject=f"Re: {email.get('subject', 'task')} [done]",
        )
        return {
            "subdomain": subdomain,
            "sent_message_ids": state.get("sent_message_ids", []) + [msg_id],
        }
    except Exception as exc:
        logger.warning("wire_cf_node reply error: %s", exc)
        return {"subdomain": subdomain}
