"""
Local workspace tools for the agentic execution loop.
All filesystem / shell interactions by the tgpt/Claude agents go through here.
"""
import asyncio
import base64
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

from app import config


# ── Path normalisation ─────────────────────────────────────────────────────────

def _norm(path_str: str) -> str:
    p = path_str.strip()
    if p.startswith("/app/"):
        p = "virtual-company/" + p[len("/app/"):]
    elif p == "/app":
        p = "virtual-company"
    if p.startswith("/workspace/"):
        p = p[len("/workspace/"):]
    elif p.startswith("workspace/"):
        p = p[len("workspace/"):]
    if p.startswith("app/"):
        sub = p[len("app/"):]
        if (config.WORK_DIR / "virtual-company" / sub).exists():
            p = "virtual-company/" + sub
    return p


def _resolve(path_str: str) -> Path:
    norm = _norm(path_str)
    return (config.WORK_DIR / norm).resolve()


def _safe(p: Path) -> bool:
    return str(p).startswith(str(config.WORK_DIR.resolve()))


# ── Tools ──────────────────────────────────────────────────────────────────────

_SERVER_START_PATTERNS = [
    r"uvicorn\s+\S+\s+.*--port",
    r"python3?\s+-m\s+http\.server",
    r"python3?\s+server\.py",
    r"python3?\s+app\.py",
    r"node\s+\S*server",
    r"npm\s+(run\s+)?start",
    r"gunicorn\s+",
    r"flask\s+run",
]

def _looks_like_server_start(cmd: str) -> bool:
    """Detect commands that try to start a persistent server inside the container."""
    c = cmd.lower()
    # Allow sidecar API calls (correct path)
    if "host.docker.internal" in c and "start-service" in c:
        return False
    import re as _re
    return any(_re.search(p, c) for p in _SERVER_START_PATTERNS)


async def local_bash(cmd: str) -> str:
    # Guard: catch attempts to start servers directly inside the container
    if _looks_like_server_start(cmd) and "&" not in cmd.split("#")[0]:
        # Background launches (&) are fine for quick test; persistent foreground servers are not
        pass  # foreground server — will time out, warn below
    if _looks_like_server_start(cmd) and "&" not in cmd:
        return (
            "[BLOCKED] You cannot start a persistent server directly inside the container — "
            "it won't be reachable from the internet.\n\n"
            "Use the sidecar API instead:\n"
            "  curl -s -X POST http://host.docker.internal:3030/api/start-service \\\n"
            "    -H 'Content-Type: application/json' \\\n"
            "    -d '{\"name\":\"<service>\",\"cwd\":\"/workspace/<dir>\",\"cmd\":\"<cmd>\",\"port\":<port>}'\n\n"
            "This starts the service on the HOST where all ports are publicly reachable."
        )

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(config.WORK_DIR),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=45)
        out = stdout.decode(errors="replace").strip()
        err = stderr.decode(errors="replace").strip()
        parts = []
        if out:
            parts.append(out)
        if err:
            parts.append(f"[stderr]\n{err}")
        return "\n".join(parts) or "[Command returned empty output]"
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return "[Error: Command timed out after 45 seconds — if you're trying to start a server, use the sidecar API instead]"
    except Exception as exc:
        return f"[Error executing command: {exc}]"


def local_read(path_str: str) -> str:
    try:
        p = _resolve(path_str)
        if not p.exists():
            # Try virtual-company sub-path
            alt = (config.WORK_DIR / "virtual-company" / _norm(path_str)).resolve()
            if alt.exists() and not alt.is_dir():
                p = alt
        if not _safe(p):
            return "[Error: Path outside workspace]"
        if not p.exists():
            return f"[Error: File '{path_str}' does not exist]"
        if p.is_dir():
            return f"[Error: '{path_str}' is a directory]"
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"[Error reading file: {exc}]"


def local_write(path_str: str, content: str) -> str:
    try:
        p = _resolve(path_str)
        if not _safe(p):
            return "[Error: Path outside workspace]"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} chars to '{path_str}'."
    except Exception as exc:
        return f"[Error writing file: {exc}]"


def local_edit(path_str: str, target: str, replacement: str) -> str:
    try:
        p = _resolve(path_str)
        if not p.exists():
            alt = (config.WORK_DIR / "virtual-company" / _norm(path_str)).resolve()
            if alt.exists() and not alt.is_dir():
                p = alt
        if not _safe(p):
            return "[Error: Path outside workspace]"
        if not p.exists():
            return f"[Error: File '{path_str}' does not exist]"
        content = p.read_text(encoding="utf-8", errors="replace")
        if target not in content:
            return f"[Error: Target text not found in '{path_str}']"
        p.write_text(content.replace(target, replacement, 1), encoding="utf-8")
        return f"Successfully edited '{path_str}'."
    except Exception as exc:
        return f"[Error editing file: {exc}]"


# ── Tool call parser ───────────────────────────────────────────────────────────

_KNOWN_PLATFORMS = {"linkedin", "naukri", "indeed", "glassdoor", "instahyre"}


def parse_browser_discover_args(raw: str) -> dict:
    """Split 'keywords | platform | location' into a dict, defaulting platform/location
    when the second segment isn't a recognised job board (so 'keywords | a city name'
    isn't mistaken for 'keywords | platform')."""
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) >= 2 and parts[1].lower() not in _KNOWN_PLATFORMS:
        return {
            "keywords": parts[0],
            "platform": "linkedin",
            "location": "Bangalore",
        }
    return {
        "keywords": parts[0] if parts else "",
        "platform": parts[1] if len(parts) > 1 else "linkedin",
        "location": parts[2] if len(parts) > 2 else "Bangalore",
    }


def parse_tool_call(text: str) -> Tuple[Optional[str], Optional[dict]]:
    if re.search(r'\[READ_INBOX\]', text):
        return "read_inbox", {}

    m = re.search(r'\[BASH:\s*(.*?)\]', text, re.DOTALL)
    if m:
        return "bash", {"cmd": m.group(1).strip()}

    m = re.search(r'\[READ:\s*(.*?)\]', text, re.DOTALL)
    if m:
        return "read", {"path": m.group(1).strip()}

    m = re.search(r'\[WRITE:\s*(.*?)\]', text, re.DOTALL)
    if m:
        path = m.group(1).strip()
        code_m = re.search(r'```(?:\w+)?\n(.*?)```', text[m.end():], re.DOTALL)
        content = code_m.group(1) if code_m else text[m.end():].strip()
        return "write", {"path": path, "content": content}

    m = re.search(r'\[EDIT:\s*(.*?)\]', text, re.DOTALL)
    if m:
        path = m.group(1).strip()
        rest = text[m.end():]
        tm = re.search(r'TARGET:\s*```(?:\w+)?\n(.*?)```', rest, re.DOTALL)
        rm = re.search(r'REPLACEMENT:\s*```(?:\w+)?\n(.*?)```', rest, re.DOTALL)
        if tm and rm:
            return "edit", {"path": path, "target": tm.group(1), "replacement": rm.group(1)}

    m = re.search(r'\[WRITE_PREVIEW:\s*\]', text, re.DOTALL)
    if m:
        code_m = re.search(r'```(?:html)?\n(.*?)```', text[m.end():], re.DOTALL)
        content = code_m.group(1) if code_m else text[m.end():].strip()
        return "write_preview", {"html_content": content}

    m = re.search(r'\[WEB_NAVIGATE:\s*(\S+)\]', text)
    if m:
        return "web_navigate", {"url": m.group(1).strip()}

    m = re.search(r'\[WEB_CLICK:\s*([^\]]+)\]', text)
    if m:
        return "web_click", {"selector": m.group(1).strip()}

    m = re.search(r'\[WEB_TYPE:\s*([^:\]]+):\s*([^\]]+)\]', text)
    if m:
        return "web_type", {"selector": m.group(1).strip(), "text": m.group(2).strip()}

    m = re.search(r'\[WEB_WAIT:\s*([^\]]+)\]', text)
    if m:
        return "web_wait", {"selector": m.group(1).strip()}

    m = re.search(r'\[WEB_GET_TEXT\]', text)
    if m:
        return "web_get_text", {}

    m = re.search(r'\[WEB_EXTRACT:\s*([^\]]*)\]', text)
    if m:
        raw = m.group(1).strip()
        parts = raw.split(None, 1)
        if parts and parts[0].startswith(("http://", "https://")):
            return "web_extract", {"url": parts[0], "selector": parts[1] if len(parts) > 1 else "body"}
        return "web_extract", {"url": "", "selector": raw or "body"}

    m = re.search(r'\[WEB_SCREENSHOT\]', text)
    if m:
        return "web_screenshot", {}

    m = re.search(r'\[ASK:(\w+)\]\s*([\s\S]+?)(?=\[|$)', text)
    if m:
        return "ask_agent", {
            "target":   m.group(1).strip().lower(),
            "question": m.group(2).strip(),
        }

    m = re.search(r'\[READ_SOURCE:\s*(.*?)\]', text, re.DOTALL)
    if m:
        return "read_source", {"path": m.group(1).strip()}

    m = re.search(r'\[WRITE_SOURCE:\s*(.*?)\]', text, re.DOTALL)
    if m:
        path = m.group(1).strip()
        code_m = re.search(r'```(?:\w+)?\n(.*?)```', text[m.end():], re.DOTALL)
        content = code_m.group(1) if code_m else text[m.end():].strip()
        return "write_source", {"path": path, "content": content}

    m = re.search(r'\[RUN_TESTS\]', text)
    if m:
        return "run_tests", {}

    m = re.search(r'\[GENERATE_IMAGE:\s*(.*?)\]', text, re.DOTALL)
    if m:
        return "generate_image", {"prompt": m.group(1).strip()}

    m = re.search(r'\[JIRA_GET:\s*([^\]]+)\]', text)
    if m:
        return "jira_get", {"ticket_id": m.group(1).strip()}

    m = re.search(r'\[JIRA_SEARCH:\s*(.*?)\]', text, re.DOTALL)
    if m:
        return "jira_search", {"jql": m.group(1).strip()}

    m = re.search(r'\[JIRA_STATUS:\s*([^:\]]+):\s*([^\]]+)\]', text)
    if m:
        return "jira_status", {"ticket_id": m.group(1).strip(), "transition": m.group(2).strip()}

    m = re.search(r'\[JIRA_COMMENT:\s*([^:\]]+):\s*(.*?)\]', text, re.DOTALL)
    if m:
        return "jira_comment", {"ticket_id": m.group(1).strip(), "body": m.group(2).strip()}

    m = re.search(r'\[BROWSER_APPLY:\s*([^\]]+)\]', text)
    if m:
        return "browser_apply", {"url": m.group(1).strip()}

    m = re.search(r'\[BROWSER_DISCOVER:\s*([^\]]+)\]', text)
    if m:
        return "browser_discover", parse_browser_discover_args(m.group(1))

    m = re.search(r'\[BROWSER_COMPANY:\s*([^\]]+)\]', text)
    if m:
        return "browser_company", {"company": m.group(1).strip()}

    m = re.search(r'\[BROWSER_PROFILE_MATCH\]', text)
    if m:
        return "browser_profile_match", {}

    m = re.search(r'\[MAKE_CALL:\s*([^\]]+)\]', text)
    if m:
        parts = [p.strip() for p in m.group(1).split("|")]
        return "make_call", {
            "number":   parts[0] if len(parts) > 0 else "",
            "goal":     parts[1] if len(parts) > 1 else "",
            "language": parts[2] if len(parts) > 2 else "en",
        }

    m = re.search(r'\[DONE:\s*(.*?)\]', text, re.DOTALL)
    if m:
        return "done", {"summary": m.group(1).strip()}

    return None, None



def summarize_output(text: str, max_lines: int = 15, max_chars: int = 800) -> str:
    if not text:
        return "[Empty Output]"
    lines = text.splitlines()
    if len(lines) <= max_lines and len(text) <= max_chars:
        return text
    truncated = "\n".join(lines[:max_lines])
    if len(truncated) > max_chars:
        truncated = truncated[:max_chars]
    hidden_l = len(lines) - len(truncated.splitlines())
    hidden_c = len(text) - len(truncated)
    return (
        f"{truncated}\n\n"
        f"... [TRUNCATED: {hidden_l} lines, {hidden_c} chars hidden]"
    )


# ── Telephony tools ────────────────────────────────────────────────────────────

from app.services import call_store as _call_store
from app.services import call_store


async def run_outbound_call(number: str, goal: str, language: str = "en", voice: str = "") -> dict:
    """Full async orchestration: script gen → pre-render → dial. Returns session info."""
    import uuid
    from app.agents.call_prep import generate_script, prerender_audio
    from app.services.telephony import dial_outbound
    from app import config as cfg

    if not cfg.TWILIO_ACCOUNT_SID:
        return {"error": "Twilio not configured — set TWILIO_ACCOUNT_SID in .env"}
    if not cfg.BASE_URL:
        return {"error": "BASE_URL not configured — set public tunnel URL in .env"}

    call_id = str(uuid.uuid4())
    speaker = voice or cfg.BARK_SPEAKER

    sess = call_store.create_session(
        call_id=call_id, direction="outbound",
        number=number, goal=goal, language=language, speaker=speaker,
    )
    sess.status = "prep"

    script_data = await generate_script(goal, language)
    entries = await prerender_audio(script_data, call_id, speaker)
    sess.script = entries
    sess.status = "dialing"

    webhook_url = f"{cfg.BASE_URL}/api/calls/gather?call_id={call_id}&turn=0"
    twilio_sid = dial_outbound(to=number, call_id=call_id, webhook_url=webhook_url)
    sess.twilio_sid = twilio_sid

    return {"call_id": call_id, "status": "dialing", "twilio_sid": twilio_sid}


async def make_call(number: str, goal: str, language: str = "en") -> dict:
    """Agent tool: make an outbound phone call."""
    return await run_outbound_call(number=number, goal=goal, language=language)


async def get_call_transcript(call_id: str) -> dict:
    """Agent tool: retrieve the transcript of a completed call."""
    result = call_store.get_transcript(call_id)
    if result is None:
        return {"error": f"No call found with id {call_id}"}
    return result


async def list_calls(limit: int = 20) -> list:
    """Agent tool: list recent call history."""
    return call_store.get_call_history(limit=limit)
