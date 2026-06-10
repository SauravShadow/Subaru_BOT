"""
Morning standup generator.

Compiles current system state into a CEO prompt, runs it through the CEO
agent, and broadcasts the result via WebSocket. The CEO sends the email
as part of its response using [EMAIL_USER:...] tag parsing.
"""
import logging
from datetime import datetime

from app.state import manager as state
from app.agents.runner import run_agent
from app.api.websocket import broadcast_event

logger = logging.getLogger(__name__)


async def generate_standup_prompt() -> str:
    """Build the CEO standup prompt from live system state."""
    projects   = state.load_projects()
    queue      = [i for i in state.work_queue if i.get("status") != "completed"]
    history    = state.task_history[-5:]
    now_str    = datetime.now().strftime("%A, %d %B %Y")

    proj_lines  = "\n".join(
        f"  - {p.get('name', '?')}: {p.get('status', '?')}" for p in projects
    ) or "  (none active)"
    queue_lines = "\n".join(
        f"  - [{i['agent']}] {i['task']} ({i['status']})" for i in queue
    ) or "  (queue empty)"
    done_lines  = "\n".join(
        f"  - {h.get('summary', '')}" for h in reversed(history)
    ) or "  (no recent completions)"

    return f"""You are Subaru, the AI command center for Shadow Garden.
Today is {now_str}.

Compose a morning executive briefing for Saurav (your operator).
Open with one sentence of creative inspiration.
Then cover:

ACTIVE PROJECTS:
{proj_lines}

PENDING QUEUE:
{queue_lines}

RECENT COMPLETIONS:
{done_lines}

Close with today's top priority and one energizing line.
Keep it 200-300 words total. Write in first person as Subaru.

After the briefing, send it via email:
[EMAIL_USER:Subaru Morning Briefing — {now_str}]
<the briefing text here>
"""


async def run_morning_standup(broadcast_fn=None) -> str:
    """Generate the standup, run CEO agent, broadcast to WS clients."""
    prompt      = await generate_standup_prompt()
    output_acc: list[str] = []

    async def _send(data: dict) -> None:
        if data.get("type") == "assistant":
            for blk in data.get("message", {}).get("content", []):
                if blk.get("type") == "text" and blk["text"]:
                    output_acc.append(blk["text"])
        _fn = broadcast_fn or broadcast_event
        try:
            await _fn(data)
        except Exception:
            pass

    await run_agent("ceo", prompt, _send, model="claude")
    text = "".join(output_acc)

    # Parse and send any generated emails (background standups fail-safe)
    from app.services import delegation as deleg_svc
    from app.services import email as email_svc
    for target, subj, body in deleg_svc.parse_emails(text):
        await email_svc.send_mail(f"[Shadow Garden] {subj}", body, to=target)

    await broadcast_event({
        "type":    "standup",
        "content": text,
        "date":    datetime.now().isoformat(),
    })

    logger.info("Morning standup completed (%d chars)", len(text))
    return text
