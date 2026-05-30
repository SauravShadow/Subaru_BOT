"""
Agent execution engine.
Provides run_agent() — a multi-turn agentic loop that calls tgpt or Claude CLI
and pipes all events back through the WebSocket via a lock-protected sender.
"""
import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path
from time import time as _time
from typing import Callable, Awaitable

from app import config
from app.agents import backend_state, definitions as defs
from app.agents.tools import (
    local_bash, local_read, local_write, local_edit,
    parse_tool_call, summarize_output,
)
from app.state import manager as state
import pytz as _pytz
from app.services import memory as mem_svc
from app.skills import skill_loader

logger = logging.getLogger(__name__)

# Signature: async (data: dict) -> None
Sender = Callable[[dict], Awaitable[None]]


def _truncate_content(text: str, max_chars: int = 8000) -> str:
    if not isinstance(text, str):
        text = str(text)
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + f"\n... [Truncated {len(text) - max_chars} characters of old output] ...\n" + text[-half:]


_ceo_context_cache: tuple = (0.0, "")
_CEO_CONTEXT_TTL = 60.0


def _get_ceo_context() -> str:
    """Returns cached system self-awareness context for the CEO agent (refreshed every 60s)."""
    global _ceo_context_cache
    now = _time()
    if now - _ceo_context_cache[0] < _CEO_CONTEXT_TTL:
        return _ceo_context_cache[1]

    # App file tree
    try:
        result = subprocess.run(
            ["find", "/app", "-name", "*.py",
             "-not", "-path", "*/__pycache__/*",
             "-not", "-path", "*/.*",
             "-not", "-name", "__init__.py"],
            capture_output=True, text=True, timeout=5,
        )
        files = sorted(f.replace("/app/", "") for f in result.stdout.strip().split("\n") if f.strip())
        file_list = "\n".join(f"  /app/{f}" for f in files[:25])
    except Exception:
        file_list = "  (unavailable)"

    # Recent changelog
    try:
        recent = state.load_changelog()[-3:]
        if recent:
            changelog_str = "\n".join(
                f"  • {e['timestamp'][:10]}: {e['feature']}"
                for e in reversed(recent)
            )
        else:
            changelog_str = "  (none yet)"
    except Exception:
        changelog_str = "  (unavailable)"

    ctx = (
        f"\nSYSTEM SELF-AWARENESS:\n"
        f"Modifiable app files:\n{file_list}\n\n"
        f"Recent self-improvements:\n{changelog_str}\n"
    )
    _ceo_context_cache = (now, ctx)
    return ctx


_IST = _pytz.timezone("Asia/Kolkata")

def _build_context_block(agent_id: str, user_query: str) -> str:
    """Live context injected into every agent prompt."""
    try:
        import datetime as _dt
        memories  = mem_svc.get_relevant_memories(agent_id, user_query, limit=5)
        queue     = [i for i in state.work_queue if i.get("status") != "completed"][-3:]
        now_str   = _dt.datetime.now(_IST).strftime("%A %d %B %Y, %H:%M IST")
        mem_lines = "\n".join(f"  - {m}" for m in memories) or "  (none yet)"
        queue_str = json.dumps(queue, indent=2) if queue else "  []"
        return (
            f"\nLIVE CONTEXT [{now_str}]:\n"
            f"Active tasks:\n{queue_str}\n"
            f"Relevant memories:\n{mem_lines}\n"
        )
    except Exception:
        return ""


def _build_tgpt_prompt(agent_id: str, user_msg: str) -> str:
    agent = defs.get_agent(agent_id)
    persona = defs.agent_persona(agent_id)
    history = state.get_history(agent_id)

    hist_str = "\n".join(
        f"{'User' if h['role'] == 'user' else agent['name']}: {_truncate_content(h['content'])}"
        for h in history[-(config.MAX_HISTORY):]
    )

    context = _get_ceo_context() if agent_id == "ceo" else ""

    tool_instructions = f"""
You are working in the directory: {config.WORK_DIR}
You have access to local workspace tools. Output ONE tool call tag and STOP — wait for results before continuing.

AVAILABLE TOOLS:
1. [BASH: command]         — Run any shell command
2. [READ: path/to/file]    — Read a file
3. [WRITE: path/to/file]   — Write a file (follow with ```\\ncontents\\n```)
4. [EDIT: path/to/file]    — Edit a block (follow with TARGET:``` and REPLACEMENT:```)
5. [READ_INBOX]            — Read recent unread emails
6. [DONE: summary]         — Signal task completion
7. [WRITE_PREVIEW:]        — Write HTML to the live design preview panel
   (follow with ```html\ncontents\n```)
8. [WEB_NAVIGATE: https://url]  — Navigate browser to URL, take screenshot
9. [WEB_EXTRACT: https://url selector]  — Extract text from CSS selector on page
10. [WEB_SCREENSHOT]            — Take screenshot of current browser page

Always state your approach in 2 sentences before calling your first tool.
"""
    live_ctx = _build_context_block(agent_id, user_msg)
    return (
        f"{persona}\n{tool_instructions}\n"
        f"{context}{live_ctx}"
        f"Conversation History:\n{hist_str}\n\n"
        f"User: {user_msg}\n\n{agent['name']}:"
    )


def _build_claude_prompt(agent_id: str, user_msg: str) -> str:
    """Prompt for Claude CLI — no tgpt tool syntax; Claude uses its own native tools."""
    agent   = defs.get_agent(agent_id)
    persona = defs.agent_persona(agent_id)
    history = state.get_history(agent_id)
    context = _get_ceo_context() if agent_id == "ceo" else ""

    hist_str = "\n".join(
        f"{'User' if h['role'] == 'user' else agent['name']}: {_truncate_content(h['content'])}"
        for h in history[-(config.MAX_HISTORY):]
    )

    live_ctx = _build_context_block(agent_id, user_msg)
    return (
        f"{persona}\n\n"
        f"Working directory: {config.WORK_DIR}"
        f"{context}{live_ctx}\n"
        f"Conversation History:\n{hist_str}\n\n"
        f"User: {user_msg}"
    )


_provider_blacklist: dict = {}  # provider_name -> expiration_timestamp


async def _run_tgpt_turn(
    prompt: str,
    agent_id: str,
    send: Sender,
    provider: str = "sky",
) -> str:
    """Single tgpt turn; returns the raw text response (never raises)."""
    tgpt_bin = config.TGPT_BIN
    
    # Build list of candidate providers
    candidates = [provider]
    for p in ["sky", "pollinations", "isou"]:
        if p not in candidates:
            candidates.append(p)

    # Filter out temporarily blacklisted providers
    now = _time()
    providers = []
    for p in candidates:
        if p in _provider_blacklist and now < _provider_blacklist[p]:
            continue
        providers.append(p)

    # If all candidates are blacklisted, clear blacklist and try all
    if not providers:
        providers = candidates

    for active_p in providers:
        proc = await asyncio.create_subprocess_exec(
            tgpt_bin, "-q", "--provider", active_p,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(config.WORK_DIR),
        )
        proc.stdin.write(prompt.encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()

        text = ""
        while True:
            chunk = await proc.stdout.read(1024)
            if not chunk:
                break
            text += chunk.decode(errors="replace")
        await proc.wait()

        bad = (
            proc.returncode != 0
            or "statuscode: 429" in text.lower()
            or "too many requests" in text.lower()
            or "error has occurred" in text.lower()
            or not text.strip()
        )
        if not bad:
            return text

        # Blacklist this provider for 5 minutes (300 seconds)
        _provider_blacklist[active_p] = _time() + 300.0
        
        # Log retry if we have other providers left to try
        remaining = [p for p in providers if p != active_p]
        if remaining:
            await send({
                "type": "assistant", "agent": agent_id,
                "message": {"content": [{"type": "text", "text":
                    f"\n[Retrying with provider '{active_p}' → rate limited, switching...]\n"
                }]},
            })

    return "\n✕ All providers hit rate limits. Please wait and retry.\n"


async def run_tgpt_agent(
    agent_id: str,
    prompt: str,
    send: Sender,
    provider: str = "sky",
) -> str:
    """Multi-turn tgpt agentic loop. Returns full accumulated response."""
    full_resp = ""
    current_prompt = prompt
    max_turns = 10

    for turn in range(max_turns):
        if turn > 0:
            await asyncio.sleep(1.5)   # pace requests

        full_input = _build_tgpt_prompt(agent_id, current_prompt)
        turn_text  = await _run_tgpt_turn(full_input, agent_id, send, provider)

        await send({
            "type":    "assistant",
            "agent":   agent_id,
            "message": {"content": [{"type": "text", "text": turn_text}]},
        })

        full_resp += turn_text
        tool_type, tool_args = parse_tool_call(turn_text)

        if not tool_type:
            break

        if tool_type == "done":
            summary   = tool_args.get("summary", "Task completed.")
            state.complete_work_item(
                state.active_agent_tasks.get(agent_id, -1), summary
            )
            break

        # Execute tool
        tool_result = await _execute_tool(agent_id, tool_type, tool_args, send)

        # Stream summarised output
        await send({
            "type": "assistant", "agent": agent_id,
            "message": {"content": [{"type": "text", "text":
                f"[Tool Output]:\n{summarize_output(tool_result)}\n\n"
            }]},
        })

        state.record(agent_id, "assistant", turn_text + f"\n[Tool Output]:\n{tool_result}\n\n")
        current_prompt = (
            f"Tool '{tool_type}' executed. Results:\n{tool_result}\n\nPlease proceed."
        )

    try:
        mem_svc.save_memory(agent_id, prompt, mem_type="user_query", importance=0.4)
        if full_resp.strip():
            mem_svc.save_memory(agent_id, full_resp[:500], mem_type="agent_response", importance=0.3)
    except Exception:
        pass
    return full_resp


async def run_claude_agent(
    agent_id: str,
    prompt: str,
    send: Sender,
) -> str:
    """Single-pass Claude CLI agent (streaming JSON). Falls back to tgpt on quota errors."""
    full_resp = ""
    args = [
        config.CLAUDE_BIN, "-p", _build_claude_prompt(agent_id, prompt),
        "--output-format", "stream-json",
        "--verbose",
        "--allowedTools", config.ALLOWED_TOOLS,
    ]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(config.WORK_DIR),
        env={**os.environ},
        limit=16 * 1024 * 1024,
    )
    # Read stderr concurrently — prevents pipe-buffer deadlock when Claude writes
    # large stderr before closing stdout.
    stderr_task = asyncio.create_task(proc.stderr.read())

    non_json_stdout = []
    async for raw in proc.stdout:
        line = raw.decode(errors="replace").strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            await send({"_raw_json": line, "agent": agent_id})
            if obj.get("type") == "assistant":
                for blk in obj.get("message", {}).get("content", []):
                    if blk.get("type") == "text":
                        full_resp += blk["text"]
        except json.JSONDecodeError:
            non_json_stdout.append(line)

    await proc.wait()
    err_bytes = await stderr_task

    if proc.returncode != 0:
        err = err_bytes.decode().strip()
        non_json_text = " ".join(non_json_stdout).strip()
        combined = err + " " + non_json_text + " " + full_resp
        if backend_state.is_quota_error(combined):
            changed = backend_state.mark_quota_exhausted()
            if changed:
                await send({"type": "backend_status", "agent": agent_id,
                            **backend_state.status_dict()})
            await send({
                "type": "backend_switch", "agent": agent_id,
                **backend_state.status_dict(),
                "message": f"Claude quota hit — switching to Gemini. Retry at {backend_state.retry_due_at().strftime('%H:%M')}.",
            })
            full_resp = await run_gemini_agent(agent_id, prompt, send)
        elif err or non_json_text:
            msg = err if err else non_json_text
            await send({"type": "error", "agent": agent_id, "message": msg})
    else:
        # Successful Claude call — recover if we were previously in tgpt mode
        if backend_state.get_current_backend() == "tgpt" and backend_state.should_use_claude():
            changed = backend_state.mark_claude_recovered()
            if changed:
                await send({"type": "backend_status", "agent": agent_id,
                            **backend_state.status_dict()})

    try:
        mem_svc.save_memory(agent_id, prompt, mem_type="user_query", importance=0.4)
        if full_resp.strip():
            mem_svc.save_memory(agent_id, full_resp[:500], mem_type="agent_response", importance=0.3)
    except Exception:
        pass
    return full_resp


async def run_gemini_agent(
    agent_id: str,
    prompt: str,
    send: Sender,
) -> str:
    """Single Gemini API turn via google-genai SDK. Falls back to tgpt on any error."""
    try:
        if not config.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY not configured — skipping Gemini")
        import google.genai as genai
        client = genai.Client(api_key=config.GEMINI_API_KEY)
        full_prompt = _build_claude_prompt(agent_id, prompt)
        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.0-flash",
            contents=full_prompt,
        )
        text = (response.text or "").strip()
        if not text:
            raise ValueError("Empty Gemini response")
        await send({
            "type":    "assistant",
            "agent":   agent_id,
            "message": {"content": [{"type": "text", "text": text}]},
        })
        try:
            mem_svc.save_memory(agent_id, prompt, mem_type="user_query", importance=0.4)
            mem_svc.save_memory(agent_id, text[:500], mem_type="agent_response", importance=0.3)
        except Exception:
            pass
        return text
    except Exception as exc:
        logger.warning("Gemini API error (%s) — falling back to tgpt", exc)
        changed = backend_state.mark_gemini_failed()
        if changed:
            await send({"type": "backend_switch", "agent": agent_id,
                        **backend_state.status_dict()})
        return await run_tgpt_agent(agent_id, prompt, send, "pollinations")


async def run_claude_vision(
    agent_id: str,
    text: str,
    images: list[dict],
    send: Sender,
) -> str:
    """Multimodal Claude API call for image+text inputs.

    Uses the Anthropic Python SDK directly (not Claude CLI) since the CLI
    does not support image content blocks.

    images: list of {media_type: str, data: str (base64)}
    """
    try:
        import anthropic

        content: list[dict] = []
        for img in images:
            content.append({
                "type": "image",
                "source": {
                    "type":       "base64",
                    "media_type": img["media_type"],
                    "data":       img["data"],
                },
            })
        content.append({
            "type": "text",
            "text": text or "What do you see in this image?",
        })

        client    = anthropic.AsyncAnthropic()
        full_resp = ""

        async with client.messages.stream(
            model=config.DEFAULT_MODEL,
            max_tokens=4096,
            system=defs.agent_persona(agent_id),
            messages=[{"role": "user", "content": content}],
        ) as stream:
            async for chunk in stream.text_stream:
                await send({
                    "type":    "assistant",
                    "agent":   agent_id,
                    "message": {"content": [{"type": "text", "text": chunk}]},
                })
                full_resp += chunk

        try:
            query_label = text if text else "What do you see in this image?"
            mem_svc.save_memory(agent_id, query_label, mem_type="vision_query", importance=0.5)
            if full_resp:
                mem_svc.save_memory(agent_id, full_resp[:500], mem_type="vision_response", importance=0.4)
        except Exception:
            pass

        return full_resp

    except Exception as exc:
        logger.warning("run_claude_vision failed: %s", exc)
        error_msg = f"[vision error: {exc}]"
        await send({
            "type":    "assistant",
            "agent":   agent_id,
            "message": {"content": [{"type": "text", "text": error_msg}]},
        })
        return error_msg


# ── Task-type classifier ───────────────────────────────────────────────────────

_CLAUDE_SIGNALS = (
    # Coding & logic
    "code", "function", "class", "def ", "import ", "implement", "refactor",
    "debug", "fix", "error:", "traceback", "exception", "syntax",
    "python", "javascript", "typescript", "sql", "json", "yaml", "html", "css",
    "test", "pytest", "assert", "api", "endpoint", "schema", "database",
    # Strict structure / reasoning
    "step by step", "follow exactly", "conditional", "algorithm", "logic",
    # Creative / nuanced writing
    "write a", "draft", "poem", "essay", "tone", "voice", "story",
)

def _classify_model(prompt: str) -> str:
    """Choose the ideal model for this task before quota checks.

    Routing map:
      Long context (>8 KB)          → gemini  (1M context window, cheap)
      Coding / logic / structure     → claude  (stronger reasoning)
      Nuanced writing / strict rules → claude
      Short chitchat (<150 chars)    → gemini  (fast, cheap)
      Default                        → claude
    """
    length = len(prompt)
    p = prompt.lower()

    if length > 8000:          # large uploads, full file reads → Gemini
        return "gemini"
    if any(sig in p for sig in _CLAUDE_SIGNALS):
        return "claude"
    if length < 150:           # quick questions / chitchat → Gemini
        return "gemini"
    return "claude"


# ── Unified dispatcher ─────────────────────────────────────────────────────────

async def run_agent(
    agent_id: str,
    prompt: str,
    send: Sender,
    model: str = "claude",   # kept for compat; explicit override skips classification
) -> str:
    """Route to the correct backend.

    Priority:
      1. Explicit model override (chatgpt / gemini flag).
      2. Task-type classification → ideal model.
      3. Quota/availability fallback: Claude → Gemini → tgpt.
    """
    if model == "chatgpt":
        return await run_tgpt_agent(agent_id, prompt, send, "sky")
    if model == "gemini":
        return await run_gemini_agent(agent_id, prompt, send)

    ideal = _classify_model(prompt)

    if ideal == "gemini":
        # Prefer Gemini for this task type
        if backend_state.gemini_available():
            return await run_gemini_agent(agent_id, prompt, send)
        if backend_state.should_use_claude():
            return await run_claude_agent(agent_id, prompt, send)
        return await run_tgpt_agent(agent_id, prompt, send, "pollinations")

    # ideal == "claude" (default)
    if backend_state.should_use_claude():
        return await run_claude_agent(agent_id, prompt, send)
    if backend_state.gemini_available():
        return await run_gemini_agent(agent_id, prompt, send)
    return await run_tgpt_agent(agent_id, prompt, send, "pollinations")


# ── Internal tool dispatcher ───────────────────────────────────────────────────

async def _execute_tool(
    agent_id: str, tool_type: str, tool_args: dict, send: Sender
) -> str:
    from app.services import email as email_svc  # lazy import

    icon_map = {
        "bash":          "⚙",
        "read":          "📖",
        "write":         "✍",
        "edit":          "✏",
        "read_inbox":    "📬",
        "write_preview": "🎨",
        "web_navigate":   "🌐",
        "web_screenshot": "📸",
        "web_extract":    "🔍",
    }
    label_map = {
        "bash":          "Executing Bash",
        "read":          "Reading File",
        "write":         "Writing File",
        "edit":          "Editing File",
        "read_inbox":    "Reading Inbox",
        "write_preview": "Writing Design Preview",
        "web_navigate":   "Navigating Browser",
        "web_screenshot": "Taking Screenshot",
        "web_extract":    "Extracting Text",
    }

    path  = tool_args.get("path", tool_args.get("cmd", ""))
    label = label_map.get(tool_type, tool_type)
    await send({
        "type":  "tool_call",
        "agent": agent_id,
        "tool":  tool_type,
        "label": label,
        "path":  path,
    })

    try:
        if tool_type == "bash":
            result = await local_bash(tool_args["cmd"])
        elif tool_type == "read":
            result = local_read(tool_args["path"])
        elif tool_type == "write":
            result = local_write(tool_args["path"], tool_args["content"])
        elif tool_type == "edit":
            result = local_edit(tool_args["path"], tool_args["target"], tool_args["replacement"])
        elif tool_type == "read_inbox":
            data   = await email_svc.read_emails(max_emails=5, unread_only=True)
            result = json.dumps(data, indent=2)
        elif tool_type == "write_preview":
            from app.services.browser import write_preview as _wp
            from app.api.websocket import broadcast_event
            html = tool_args.get("html_content", tool_args.get("content", ""))
            if not html.strip():
                result = "[write_preview error: empty HTML content — provide a complete HTML document]"
            else:
                result = _wp(html)
                asyncio.create_task(broadcast_event({
                    "type":    "design_preview_updated",
                    "message": result,
                }))
        elif tool_type == "web_navigate":
            from app.services.browser import navigate as _nav
            from app.api.websocket import broadcast_event
            url = tool_args.get("url", "")
            if url and not url.startswith(("http://", "https://")):
                url = "https://" + url
            result_d = await _nav(url)
            result   = str(result_d)
            asyncio.create_task(broadcast_event({
                "type":       "browser_navigated",
                "screenshot": result_d.get("screenshot", ""),
                "title":      result_d.get("title", ""),
                "url":        url,
            }))
        elif tool_type == "web_screenshot":
            from app.services.browser import take_screenshot as _ss
            result_d = await _ss()
            result   = str(result_d)
        elif tool_type == "web_extract":
            from app.services.browser import extract_text as _ex
            url      = tool_args.get("url", "")
            selector = tool_args.get("selector", "body")
            result   = await _ex(url, selector)
        else:
            handler = skill_loader.get_tool(tool_type)
            if handler:
                result = await handler(tool_args)
            else:
                result = f"[Unknown tool: {tool_type}]"
        return str(result)
    except Exception as exc:
        return f"[Tool error: {exc}]"
