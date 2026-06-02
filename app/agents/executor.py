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
    parse_tool_call, summarize_output, generate_image,
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


_ASK_TIMEOUT: float = 120.0   # seconds before inter-agent ask times out

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


def _auto_compact_history(agent_id: str) -> bool:
    """Archive old messages to FTS5 memory and trim conversation history.

    Fires when history exceeds config.COMPACT_THRESHOLD. The archived messages
    are retrievable via memory injection on future turns — context is compressed,
    not lost. Returns True if compaction happened.
    """
    history = state.get_history(agent_id)
    if len(history) <= config.COMPACT_THRESHOLD:
        return False

    to_archive = history[: -config.COMPACT_KEEP]
    for msg in to_archive:
        content = msg.get("content", "")
        if content and len(content) > 30:
            try:
                mem_svc.save_memory(
                    agent_id,
                    content[:800],
                    mem_type="compacted_history",
                    importance=0.55,
                )
            except Exception:
                pass

    state.conversation_histories[agent_id] = history[-config.COMPACT_KEEP :]
    state.save_state()
    logger.info(
        "Auto-compacted %d messages for agent '%s' (kept last %d)",
        len(to_archive), agent_id, config.COMPACT_KEEP,
    )
    return True


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
11. [ASK:agent_id] question    — Ask another agent a question mid-task; their reply is injected back
    Agents: ceo, backend, frontend, qa, devops
    Example: [ASK:ceo] Should I use Postgres or SQLite for this?
12. [READ_SOURCE: /app/app/agents/executor.py]  — Read any source file in /app/
13. [WRITE_SOURCE: /app/app/services/foo.py]    — Write/modify source file (zone-checked)
    Follow with: ```python\n<content>\n```
14. [RUN_TESTS]                                  — Run pytest and return pass/fail summary
15. [GENERATE_IMAGE: description of the image]   — Generate an image from a text prompt
    Example: [GENERATE_IMAGE: A futuristic city skyline at sunset, cyberpunk style]
16. [EMAIL_USER:recipient@domain.com | Subject] body  — Send an email to a specific address
    Example: [EMAIL_USER:john@example.com | Meeting Tomorrow] Hi John, let's meet at 3pm.
    Or:      [EMAIL_USER:Task Done] Your task has been completed.   (sends to the main user)

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
        f"IMAGE GENERATION: When the user asks you to generate, create, or make an image, "
        f"output this tag in your response and the system will generate it:\n"
        f"  [GENERATE_IMAGE: detailed description of the image to generate]\n"
        f"  Example: [GENERATE_IMAGE: A futuristic Tokyo skyline at sunset with neon lights]\n"
        f"Do NOT write Python/Pillow scripts for image generation — use the tag instead.\n\n"
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
        
        remaining = [p for p in providers if p != active_p]
        if remaining:
            await send({
                "type": "tool_call",
                "agent": agent_id,
                "tool": "fallback",
                "label": "Switching Provider",
                "path": f"rate limited on '{active_p}', trying next"
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

    # Send the final response at the end of the tgpt execution
    if full_resp.strip():
        import re as _re
        clean_resp = full_resp.strip()
        clean_resp = _re.sub(r'\[GENERATE_IMAGE:\s*.*?\]', '', clean_resp, flags=_re.DOTALL).strip()
        clean_resp = _re.sub(r'\[DONE:\s*.*?\]', '', clean_resp, flags=_re.DOTALL).strip()
        clean_resp = _re.sub(r'\[Tool Output\]:.*', '', clean_resp, flags=_re.DOTALL).strip()
        
        # Fall back to last turn_text if clean_resp is completely empty
        if not clean_resp and 'turn_text' in locals() and turn_text.strip():
            clean_resp = _re.sub(r'\[(DONE|GENERATE_IMAGE):\s*.*?\]', '', turn_text, flags=_re.DOTALL).strip()
            
        if clean_resp:
            await send({
                "type":    "assistant",
                "agent":   agent_id,
                "message": {"content": [{"type": "text", "text": clean_resp}]},
            })

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
            # Only stream tool calls to the frontend as thinking steps;
            # do not stream intermediate assistant text to avoid cluttering the chat.
            if obj.get("type") != "assistant" and obj.get("message", {}).get("role") != "assistant":
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

        # Send the final compiled, clean response at the end of successful execution
        if full_resp.strip():
            import re as _re
            clean_resp = full_resp.strip()
            clean_resp = _re.sub(r'\[GENERATE_IMAGE:\s*.*?\]', '', clean_resp, flags=_re.DOTALL).strip()
            clean_resp = _re.sub(r'\[DONE:\s*.*?\]', '', clean_resp, flags=_re.DOTALL).strip()
            
            await send({
                "type":    "assistant",
                "agent":   agent_id,
                "message": {"content": [{"type": "text", "text": clean_resp}]},
            })

    try:
        mem_svc.save_memory(agent_id, prompt, mem_type="user_query", importance=0.4)
        if full_resp.strip():
            mem_svc.save_memory(agent_id, full_resp[:500], mem_type="agent_response", importance=0.3)
    except Exception:
        pass

    # Check if Claude wants to generate an image
    import re as _re
    img_match = _re.search(r'\[GENERATE_IMAGE:\s*(.*?)\]', full_resp, _re.DOTALL)
    if img_match:
        img_prompt = img_match.group(1).strip()
        await send({"type": "tool_call", "agent": agent_id,
                    "tool": "generate_image", "label": "Generating Image",
                    "path": img_prompt[:60]})
        img_result = await generate_image(img_prompt)
        if img_result.get("ok"):
            await send({
                "type":    "assistant",
                "agent":   agent_id,
                "message": {"content": [{
                    "type":       "image",
                    "media_type": img_result["mime_type"],
                    "data":       img_result["data"],
                }]},
            })

    return full_resp


def _build_gemini_prompt(agent_id: str, user_msg: str) -> str:
    """Prompt for Gemini API — conversational only, no tool syntax."""
    agent   = defs.get_agent(agent_id)
    persona = defs.agent_persona(agent_id)
    history = state.get_history(agent_id)

    # Strip tool-related instructions from persona for Gemini
    # (Gemini can't execute tools, so it just prints them as text)
    clean_persona = persona.split("AVAILABLE TOOLS:")[0] if "AVAILABLE TOOLS:" in persona else persona

    hist_str = "\n".join(
        f"{'User' if h['role'] == 'user' else agent['name']}: {_truncate_content(h['content'])}"
        for h in history[-(config.MAX_HISTORY):]
    )

    live_ctx = _build_context_block(agent_id, user_msg)
    return (
        f"{clean_persona}\n\n"
        f"IMPORTANT: You are responding via Gemini API (limited tool access). "
        f"Answer conversationally and helpfully. Do NOT output [BASH:], [READ:], [WRITE:], "
        f"[DELEGATE:], or any other execution tool tags.\n"
        f"EXCEPTIONS — you CAN use these tags:\n"
        f"  [GENERATE_IMAGE: description]  — generate an image\n"
        f"    Example: [GENERATE_IMAGE: A futuristic city skyline at sunset, cyberpunk neon lights]\n"
        f"  [EMAIL_USER:recipient@domain.com | Subject] body  — send an email to anyone\n"
        f"    Example: [EMAIL_USER:john@example.com | Hello from Shadow Garden] Hi John, just checking in!\n"
        f"  [EMAIL_USER:Subject] body  — send an email to the main user (no recipient = owner)\n"
        f"    Example: [EMAIL_USER:Task Complete] Your task has been finished.\n"
        f"{live_ctx}\n"
        f"Conversation History:\n{hist_str}\n\n"
        f"User: {user_msg}"
    )


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
        full_prompt = _build_gemini_prompt(agent_id, prompt)
        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-3-flash-preview",
            contents=full_prompt,
        )
        text = (response.text or "").strip()
        if not text:
            raise ValueError("Empty Gemini response")
        import re as _re
        display_text = _re.sub(r'\[GENERATE_IMAGE:\s*.*?\]', '', text, flags=_re.DOTALL).strip()
        await send({
            "type":    "assistant",
            "agent":   agent_id,
            "message": {"content": [{"type": "text", "text": display_text}]},
        })

        # Check if Gemini wants to generate an image
        import re as _re
        img_match = _re.search(r'\[GENERATE_IMAGE:\s*(.*?)\]', text, _re.DOTALL)
        if img_match:
            img_prompt = img_match.group(1).strip()
            logger.info("🎨 GENERATE_IMAGE detected: %s", img_prompt[:80])
            await send({"type": "tool_call", "agent": agent_id,
                        "tool": "generate_image", "label": "Generating Image",
                        "path": img_prompt[:60]})
            img_result = await generate_image(img_prompt)
            logger.info("🎨 Image result: ok=%s, size=%s", img_result.get("ok"), img_result.get("size", img_result.get("error")))
            if img_result.get("ok"):
                await send({
                    "type":    "assistant",
                    "agent":   agent_id,
                    "message": {"content": [{
                        "type":       "image",
                        "media_type": img_result["mime_type"],
                        "data":       img_result["data"],
                    }]},
                })
                logger.info("🎨 Image sent to frontend!")
        else:
            logger.info("No GENERATE_IMAGE tag found in response (len=%d)", len(text))

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
    """Multimodal vision — tries Anthropic SDK, falls back to Gemini 3.5 Flash.

    images: list of {media_type: str, data: str (base64)}
    """
    query_label = text or "What do you see in this image?"

    # ── Attempt 1: Anthropic SDK (needs ANTHROPIC_API_KEY) ──
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if anthropic_key:
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
            content.append({"type": "text", "text": query_label})

            client    = anthropic.AsyncAnthropic(api_key=anthropic_key)
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
                mem_svc.save_memory(agent_id, query_label, mem_type="vision_query", importance=0.5)
                if full_resp:
                    mem_svc.save_memory(agent_id, full_resp[:500], mem_type="vision_response", importance=0.4)
            except Exception:
                pass
            return full_resp

        except Exception as exc:
            logger.warning("Anthropic vision failed (%s) — trying Gemini", exc)

    # ── Attempt 2: Gemini 3.5 Flash multimodal vision ──
    if config.GEMINI_API_KEY:
        try:
            import google.genai as genai
            from google.genai import types as genai_types

            client = genai.Client(api_key=config.GEMINI_API_KEY)

            # Build multimodal parts: images + text
            parts = []
            for img in images:
                parts.append(genai_types.Part.from_bytes(
                    data=__import__("base64").b64decode(img["data"]),
                    mime_type=img["media_type"],
                ))
            parts.append(genai_types.Part.from_text(text=query_label))

            persona = defs.agent_persona(agent_id)
            clean_persona = persona.split("AVAILABLE TOOLS:")[0] if "AVAILABLE TOOLS:" in persona else persona

            response = await asyncio.to_thread(
                client.models.generate_content,
                model="gemini-3-flash-preview",
                contents=[genai_types.Content(role="user", parts=parts)],
                config=genai_types.GenerateContentConfig(
                    system_instruction=clean_persona[:2000],
                ),
            )
            full_resp = (response.text or "").strip()
            if not full_resp:
                raise ValueError("Empty Gemini vision response")

            await send({
                "type":    "assistant",
                "agent":   agent_id,
                "message": {"content": [{"type": "text", "text": full_resp}]},
            })
            try:
                mem_svc.save_memory(agent_id, query_label, mem_type="vision_query", importance=0.5)
                if full_resp:
                    mem_svc.save_memory(agent_id, full_resp[:500], mem_type="vision_response", importance=0.4)
            except Exception:
                pass
            return full_resp

        except Exception as exc:
            logger.warning("Gemini vision failed: %s", exc)
            error_msg = f"[Vision error: Gemini failed — {exc}]"
            await send({
                "type":    "assistant",
                "agent":   agent_id,
                "message": {"content": [{"type": "text", "text": error_msg}]},
            })
            return error_msg

    # ── No vision backend available ──
    error_msg = (
        "⚠️ Image analysis unavailable — no ANTHROPIC_API_KEY or GEMINI_API_KEY configured. "
        "Please send a text-only message."
    )
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
    async def _notify_backend(backend_name: str) -> None:
        """Tell the frontend which backend is handling this request."""
        prev = backend_state.get_current_backend()
        if prev != backend_name:
            await send({"type": "backend_status", "agent": agent_id,
                        "backend": backend_name,
                        "quota_ok": backend_state._quota_exhausted_at is None,
                        "gemini_ok": backend_state._gemini_failed_at is None,
                        "retry_at": None})

    # Auto-compact history before building the prompt — saves tokens on long sessions
    _auto_compact_history(agent_id)

    if model == "chatgpt":
        await _notify_backend("tgpt")
        return await run_tgpt_agent(agent_id, prompt, send, "sky")
    if model == "gemini":
        await _notify_backend("gemini")
        return await run_gemini_agent(agent_id, prompt, send)

    ideal = _classify_model(prompt)

    if ideal == "gemini":
        # Prefer Gemini for this task type
        if backend_state.gemini_available():
            await _notify_backend("gemini")
            return await run_gemini_agent(agent_id, prompt, send)
        if backend_state.should_use_claude():
            await _notify_backend("claude")
            return await run_claude_agent(agent_id, prompt, send)
        await _notify_backend("tgpt")
        return await run_tgpt_agent(agent_id, prompt, send, "pollinations")

    # ideal == "claude" (default)
    if backend_state.should_use_claude():
        await _notify_backend("claude")
        return await run_claude_agent(agent_id, prompt, send)
    if backend_state.gemini_available():
        await _notify_backend("gemini")
        return await run_gemini_agent(agent_id, prompt, send)
    await _notify_backend("tgpt")
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
        "web_click":      "🖱",
        "web_type":       "⌨",
        "web_wait":       "⏳",
        "web_get_text":   "📄",
        "ask_agent":     "💬",
        "read_source":   "📋",
        "write_source":  "🔧",
        "run_tests":     "🧪",
        "generate_image": "🎨",
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
        "web_click":      "Clicking Element",
        "web_type":       "Typing Text",
        "web_wait":       "Waiting for Element",
        "web_get_text":   "Reading Page",
        "ask_agent":     "Asking agent",
        "read_source":    "Reading Source",
        "write_source":   "Writing Source",
        "run_tests":      "Running Tests",
        "generate_image": "Generating Image",
    }

    path  = tool_args.get("path", tool_args.get("cmd", tool_args.get("target", tool_args.get("url", ""))))
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
            from app.services.browser import navigate as _nav
            url      = tool_args.get("url", "")
            selector = tool_args.get("selector", "body")
            if url:
                await _nav(url)
            result = await _ex(selector)

        elif tool_type == "web_click":
            from app.services.browser import click_element as _click
            from app.api.websocket import broadcast_event
            selector = tool_args.get("selector", "")
            result_d = await _click(selector)
            result   = str(result_d)
            if result_d.get("screenshot"):
                asyncio.create_task(broadcast_event({
                    "type":       "browser_navigated",
                    "screenshot": result_d.get("screenshot", ""),
                    "title":      result_d.get("title", ""),
                    "url":        result_d.get("url", ""),
                }))

        elif tool_type == "web_type":
            from app.services.browser import type_text as _type
            from app import config as _cfg
            selector = tool_args.get("selector", "")
            raw_text = tool_args.get("text", "")
            if raw_text.startswith("$CRED_"):
                cred_key = raw_text[6:]
                resolved = _cfg.get_credential(cred_key)
                if not resolved:
                    result = f"[web_type: credential '{raw_text}' not set — add CRED_{cred_key} to env]"
                else:
                    result_d = await _type(selector, resolved)
                    result   = str(result_d) + " [credential used]"
            else:
                result_d = await _type(selector, raw_text)
                result   = str(result_d)

        elif tool_type == "web_wait":
            from app.services.browser import wait_for_element as _wait
            selector = tool_args.get("selector", "body")
            result_d = await _wait(selector)
            result   = str(result_d)

        elif tool_type == "web_get_text":
            from app.services.browser import get_page_text as _gpt
            from app.api.websocket import broadcast_event
            result_d = await _gpt()
            result   = str(result_d)
            if result_d.get("screenshot"):
                asyncio.create_task(broadcast_event({
                    "type":       "browser_navigated",
                    "screenshot": result_d.get("screenshot", ""),
                    "title":      result_d.get("title", ""),
                    "url":        result_d.get("url", ""),
                }))
        elif tool_type == "ask_agent":
            target   = tool_args.get("target", "ceo")
            question = tool_args.get("question", "")

            try:
                reply = await asyncio.wait_for(
                    run_agent(target, question, send),
                    timeout=_ASK_TIMEOUT,
                )
                result = (reply or "").strip() or f"[{target} sent no text reply]"
            except asyncio.TimeoutError:
                result = (
                    f"[{target} timed out after {int(_ASK_TIMEOUT)}s — "
                    f"proceeding with best judgement]"
                )

        elif tool_type == "read_source":
            result = local_read(tool_args.get("path", ""))

        elif tool_type == "write_source":
            from app.services.self_heal import (
                classify_path, create_approval, build_approval_email, load_approvals,
            )
            from app.services import email as email_svc_sh
            from app.api.websocket import broadcast_event
            from app.agents.tools import _resolve, _safe

            file_path = tool_args.get("path", "")
            content   = tool_args.get("content", "")
            if not content.strip():
                result = "[write_source error: empty content — provide a fenced code block after the tag]"
            else:
                zone      = classify_path(file_path)

                if zone == "immutable":
                    result = (
                        f"[BLOCKED] {file_path} is in the immutable core — "
                        "it cannot be modified by any agent."
                    )
                elif zone in ("surface", "learning"):
                    resolved = _resolve(file_path)
                    if not _safe(resolved):
                        result = "[BLOCKED] Path is outside the workspace."
                    else:
                        result = local_write(file_path, content)
                        asyncio.create_task(broadcast_event({
                            "type":  "source_file_modified",
                            "path":  file_path,
                            "zone":  zone,
                            "agent": agent_id,
                        }))
                else:  # protected — email gate
                    resolved    = _resolve(file_path)
                    approval_id = create_approval(file_path, content, agent_id, resolved)
                    stored_diff = load_approvals().get(approval_id, {}).get("diff", "")
                    subj, body  = build_approval_email(approval_id, file_path, agent_id, stored_diff)
                    asyncio.create_task(email_svc_sh.send_mail(subj, body))
                    asyncio.create_task(broadcast_event({
                        "type":        "approval_requested",
                        "approval_id": approval_id,
                        "file_path":   file_path,
                        "agent":       agent_id,
                    }))
                    result = (
                        f"Change pending approval (ID: {approval_id}). "
                        f"Email sent to {config.USER_EMAIL}. "
                        f"Reply 'APPROVE {approval_id}' or 'DENY {approval_id}'."
                    )

        elif tool_type == "run_tests":
            result = await local_bash(
                "python -m pytest /app/tests/ -q --tb=short --no-header 2>&1 | tail -20"
            )

        elif tool_type == "generate_image":
            prompt = tool_args.get("prompt", "")
            img_result = await generate_image(prompt)
            if img_result.get("ok"):
                # Send the image inline to the frontend
                await send({
                    "type":    "assistant",
                    "agent":   agent_id,
                    "message": {"content": [{
                        "type":       "image",
                        "media_type": img_result["mime_type"],
                        "data":       img_result["data"],
                    }]},
                })
                result = f"Image generated successfully ({img_result['size']} bytes)"
            else:
                result = f"[Image generation failed: {img_result.get('error', 'unknown')}]"

        else:
            handler = skill_loader.get_tool(tool_type)
            if handler:
                result = await handler(tool_args)
            else:
                result = f"[Unknown tool: {tool_type}]"
        return str(result)
    except Exception as exc:
        return f"[Tool error: {exc}]"
