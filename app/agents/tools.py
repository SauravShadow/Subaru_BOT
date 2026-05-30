"""
Local workspace tools for the agentic execution loop.
All filesystem / shell interactions by the tgpt/Claude agents go through here.
"""
import asyncio
import re
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

def parse_tool_call(text: str) -> Tuple[Optional[str], Optional[dict]]:
    if re.search(r'\[READ_INBOX\]', text):
        return "read_inbox", {}

    m = re.search(r'\[DONE:\s*(.*?)\]', text, re.DOTALL)
    if m:
        return "done", {"summary": m.group(1).strip()}

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

    m = re.search(r'\[WEB_EXTRACT:\s*(.*?)\]', text, re.DOTALL)
    if m:
        parts    = m.group(1).strip().split(None, 1)
        url      = parts[0] if parts else ""
        selector = parts[1] if len(parts) > 1 else "body"
        return "web_extract", {"url": url, "selector": selector}

    m = re.search(r'\[WEB_SCREENSHOT\]', text)
    if m:
        return "web_screenshot", {}

    m = re.search(r'\[ASK:(\w+)\]\s*([\s\S]+?)(?=\[|$)', text)
    if m:
        return "ask_agent", {
            "target":   m.group(1).strip().lower(),
            "question": m.group(2).strip(),
        }

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
