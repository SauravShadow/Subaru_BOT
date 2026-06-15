"""
Pre-call prep: LLM script generation, TTS pre-render, fuzzy Q&A matching.
"""
import asyncio
import base64
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from app import config
from app.services import bark_client
from app.services.call_store import ScriptEntry   # canonical definition lives in call_store

logger = logging.getLogger(__name__)

_AUDIO_DIR = Path(tempfile.gettempdir()) / "nexus_calls"
_AUDIO_DIR.mkdir(parents=True, exist_ok=True)


def generate_script_prompt(goal: str, language: str = "en") -> str:
    return f"""You are preparing a phone call script for an AI assistant named NEXUS.

CALL GOAL: {goal}
LANGUAGE: {language}

Generate a JSON object with this exact structure:
{{
  "opening": "<first thing NEXUS says when call connects>",
  "script": [
    {{"question": "<likely thing the other party says>", "answer": "<NEXUS response>"}},
    ... (8-12 entries covering the most likely conversation turns)
  ],
  "closing": "<final line before hanging up>"
}}

Rules:
- Write naturally, conversationally — not robotic
- Cover the most likely questions/responses for this specific goal
- Keep each answer under 30 words
- Output ONLY the JSON, no explanation
"""


async def _claude_cli_generate(prompt: str, timeout: float = 60.0) -> str:
    """One-shot generation via the Claude CLI (CLAUDE_BIN) — the project's keyless
    Claude access path (uses the user's subscription, no ANTHROPIC_API_KEY needed).
    Returns the raw stdout text, or "" on any failure."""
    claude_bin = config.CLAUDE_BIN
    if not claude_bin:
        return ""
    if claude_bin == "claude":  # default — only usable if actually on PATH
        import shutil
        if not shutil.which("claude"):
            return ""
    try:
        proc = await asyncio.create_subprocess_exec(
            claude_bin, "-p", prompt, "--model", config.DEFAULT_MODEL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(config.WORK_DIR),
            env={**os.environ},
            limit=16 * 1024 * 1024,
        )
        out, _err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return (out.decode(errors="replace") or "").strip()
    except Exception as exc:
        logger.warning("Claude CLI generation failed: %s", exc)
        return ""


async def generate_script(goal: str, language: str = "en") -> dict:
    """Call an LLM to generate a call script. Returns dict with opening/script/closing.

    This deployment authenticates Claude via the CLI (CLAUDE_BIN), not the anthropic
    SDK, so there is no ANTHROPIC_API_KEY. Generator priority:
      1. Claude CLI (keyless, the project's canonical Claude access)
      2. Gemini (configured GEMINI_API_KEY)
      3. anthropic SDK (deployments that do set an API key)
      4. minimal default script
    """
    prompt = generate_script_prompt(goal, language)
    raw = await _claude_cli_generate(prompt)

    # Secondary: Gemini (matches the configured GEMINI_API_KEY)
    if not raw and config.GEMINI_API_KEY:
        try:
            import google.genai as genai
            client = genai.Client(api_key=config.GEMINI_API_KEY)
            resp = await asyncio.to_thread(
                client.models.generate_content,
                model="gemini-2.0-flash",
                contents=prompt,
            )
            raw = (resp.text or "").strip()
        except Exception as exc:
            logger.warning("Gemini script generation failed: %s", exc)

    # Secondary: anthropic SDK (only works where ANTHROPIC_API_KEY is set)
    if not raw:
        try:
            import anthropic
            client = anthropic.AsyncAnthropic()
            msg = await client.messages.create(
                model=config.DEFAULT_MODEL,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()
        except Exception as exc:
            logger.error("Script generation failed: %s", exc)

    if raw:
        try:
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            return json.loads(raw)
        except Exception as exc:
            logger.error("Script JSON parse failed: %s", exc)

    return {
        "opening": f"Hello, I'm calling regarding: {goal}",
        "script": [],
        "closing": "Thank you for your time. Goodbye.",
    }


async def prerender_audio(
    script_data: dict,
    call_id: str,
    speaker: str,
) -> list[ScriptEntry]:
    """Pre-render all script lines to WAV files. Returns list of ScriptEntry."""
    call_dir = _AUDIO_DIR / call_id
    call_dir.mkdir(parents=True, exist_ok=True)
    entries: list[ScriptEntry] = []

    lines: list[tuple[str, str]] = []  # (question, answer)
    lines.append(("", script_data.get("opening", "")))
    for item in script_data.get("script", []):
        lines.append((item.get("question", ""), item.get("answer", "")))
    lines.append(("", script_data.get("closing", "")))

    async def render_one(idx: int, question: str, answer: str) -> ScriptEntry:
        wav_path = str(call_dir / f"{idx}.wav")
        audio_b64 = await bark_client.speak(answer, "calm", voice=speaker)
        if audio_b64:
            wav_bytes = base64.b64decode(audio_b64)
            Path(wav_path).write_bytes(wav_bytes)
        else:
            wav_path = ""
            logger.warning("Pre-render failed for entry %d: %s", idx, answer)
        return ScriptEntry(idx=idx, question=question, answer=answer, audio_path=wav_path)

    tasks = [render_one(i, q, a) for i, (q, a) in enumerate(lines)]
    return list(await asyncio.gather(*tasks))


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def match_utterance(
    stt_text: str,
    script: list[ScriptEntry],
    threshold: float = 0.45,
) -> Optional[ScriptEntry]:
    """Fuzzy-match STT text against unused script entries. Returns best match or None."""
    best_score, best_entry = 0.0, None
    for entry in script:
        if entry.used or not entry.question:
            continue
        score = _similarity(stt_text, entry.question)
        if score > best_score:
            best_score, best_entry = score, entry
    return best_entry if best_score >= threshold else None


_FALLBACK_REPLY = "Sorry, could you repeat that?"


async def quick_reply(goal: str, transcript: list, language: str = "en") -> str:
    """Fast reply for a live call turn. Never raises.

    Tries Gemini-flash first (sub-2s); if it fails or is quota-exhausted, falls back
    to the Claude CLI (keyless, slower but real) before the canned line. `transcript`
    is a list of call_store.Turn (objects with .speaker/.text).
    """
    convo = "\n".join(
        f"{'You' if t.speaker == 'nexus' else 'Caller'}: {t.text}"
        for t in transcript[-8:]
    )
    prompt = (
        f"You are NEXUS on a live phone call. Goal: {goal}\n"
        f"Reply in {language}. ONE short spoken sentence — no markdown, no emojis, "
        f"no stage directions. If the goal is met or the caller is done, close politely.\n\n"
        f"Conversation so far:\n{convo}\n\nYour next spoken line:"
    )

    # Primary: Gemini-flash (fastest)
    if config.GEMINI_API_KEY:
        try:
            import google.genai as genai
            client = genai.Client(api_key=config.GEMINI_API_KEY)
            resp = await asyncio.wait_for(
                asyncio.to_thread(
                    client.models.generate_content,
                    model="gemini-3.5-flash",
                    contents=prompt,
                ),
                timeout=4.0,
            )
            text = (resp.text or "").strip()
            if text:
                return text
        except Exception as exc:
            logger.warning("quick_reply Gemini failed: %s", exc)

    # Fallback: Claude CLI (keyless). Slower, but kept within Twilio's webhook
    # response window. One short sentence, so strip to the first line.
    cli = await _claude_cli_generate(prompt, timeout=12.0)
    if cli:
        return cli.splitlines()[0].strip() or _FALLBACK_REPLY

    return _FALLBACK_REPLY


def cleanup_call_audio(call_id: str) -> None:
    """Remove temp WAV files after a call ends."""
    import shutil
    call_dir = _AUDIO_DIR / call_id
    if call_dir.exists():
        shutil.rmtree(call_dir, ignore_errors=True)
