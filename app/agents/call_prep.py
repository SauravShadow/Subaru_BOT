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


async def generate_script(goal: str, language: str = "en") -> dict:
    """Call LLM to generate a call script. Returns dict with opening/script/closing."""
    prompt = generate_script_prompt(goal, language)
    try:
        import anthropic
        client = anthropic.AsyncAnthropic()
        msg = await client.messages.create(
            model=config.DEFAULT_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)
    except Exception as exc:
        logger.error("Script generation failed: %s", exc)
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


def cleanup_call_audio(call_id: str) -> None:
    """Remove temp WAV files after a call ends."""
    import shutil
    call_dir = _AUDIO_DIR / call_id
    if call_dir.exists():
        shutil.rmtree(call_dir, ignore_errors=True)
