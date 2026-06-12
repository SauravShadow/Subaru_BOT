"""Pre-generates filler audio clips on startup using gTTS (falls back to espeak-ng)."""
import base64
import io
import logging
import random
import subprocess

logger = logging.getLogger(__name__)

FILLER_POOL: dict[str, list[bytes]] = {
    "thinking": [],
    "health":   [],
    "facts":    [],
    "creative": [],
}

FILLER_TEXTS = {
    "thinking": [
        "Hmm, let me think on that for a second.",
        "Okay, processing, give me just a moment.",
        "Right, let me work through this.",
    ],
    "health": [
        "Quick tip while I think, drink some water, you probably haven't today.",
        "Fun fact: a 5-minute walk every hour improves focus.",
        "While I prep this, your eyes need a break from the screen every 20 minutes.",
    ],
    "facts": [
        "Did you know honey never expires? Archaeologists found 3000-year-old honey still good.",
        "Interesting thing while I work, the universe is 13.8 billion years old.",
        "While I am thinking, octopuses have three hearts and blue blood.",
    ],
    "creative": [
        "Setting the stage, give me just a second.",
        "Warming up, one moment.",
        "Getting into character.",
    ],
}


def _gtts_wav(text: str) -> bytes | None:
    try:
        from gtts import gTTS
        from pydub import AudioSegment
        tts = gTTS(text=text, lang="en")
        mp3_buf = io.BytesIO()
        tts.write_to_fp(mp3_buf)
        mp3_buf.seek(0)
        audio = AudioSegment.from_mp3(mp3_buf)
        wav_buf = io.BytesIO()
        audio.export(wav_buf, format="wav")
        return wav_buf.getvalue()
    except Exception as exc:
        logger.warning("gTTS filler failed (%s), trying espeak-ng", exc)
        return None


def _espeak_wav(text: str) -> bytes | None:
    try:
        result = subprocess.run(
            ["espeak-ng", "--stdout", "-s", "140", "-p", "50", text],
            capture_output=True,
            timeout=30,
        )
        if result.returncode == 0:
            return result.stdout
        logger.error("espeak-ng error: %s", result.stderr.decode())
    except Exception as exc:
        logger.error("espeak-ng exception: %s", exc)
    return None


def build_pool() -> None:
    total = sum(len(v) for v in FILLER_TEXTS.values())
    logger.info("Building filler pool (%d clips)...", total)
    for category, texts in FILLER_TEXTS.items():
        for text in texts:
            wav = _gtts_wav(text) or _espeak_wav(text)
            if wav:
                FILLER_POOL[category].append(wav)
                logger.info("  ✓ %s: %s", category, text[:40])
            else:
                logger.warning("  ✗ filler failed: %s", text[:40])
    logger.info("Filler pool ready.")


def pick(context: str = "") -> bytes | None:
    ctx = context.lower()
    if any(w in ctx for w in ["sing", "song", "music", "rap", "hum", "perform"]):
        pool = FILLER_POOL["creative"]
    elif any(w in ctx for w in ["health", "food", "sleep", "tired", "eat"]):
        pool = FILLER_POOL["health"]
    elif any(w in ctx for w in ["code", "build", "fix", "debug", "error"]):
        pool = FILLER_POOL["thinking"]
    else:
        pool = FILLER_POOL["thinking"] + FILLER_POOL["facts"]
    return random.choice(pool) if pool else None


def wav_to_b64(wav_bytes: bytes) -> str:
    return base64.b64encode(wav_bytes).decode("ascii")
