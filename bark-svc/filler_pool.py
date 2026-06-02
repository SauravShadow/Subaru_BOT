"""Pre-generates filler audio clips on startup. All clips served from memory."""
import random
import base64
import logging
import io
import numpy as np
from scipy.io.wavfile import write as wav_write

logger = logging.getLogger(__name__)

FILLER_POOL: dict[str, list[bytes]] = {
    "thinking": [],
    "health":   [],
    "facts":    [],
    "creative": [],
}

FILLER_TEXTS = {
    "thinking": [
        "Hmm, let me think on that for a second...",
        "Okay, processing... give me just a moment.",
        "Right, let me work through this...",
    ],
    "health": [
        "Quick tip while I think — drink some water, you probably haven't today.",
        "Fun fact: a 5-minute walk every hour improves focus by 20 percent.",
        "While I prep this — your eyes need a break from the screen every 20 minutes.",
    ],
    "facts": [
        "Did you know honey never expires? Archaeologists found 3000-year-old honey still good.",
        "Interesting thing while I work — the universe is 13.8 billion years old.",
        "While I am thinking — octopuses have three hearts and blue blood.",
    ],
    "creative": [
        "Setting the stage, give me just a second...",
        "Warming up the vocals, one moment...",
        "Getting into character...",
    ],
}

_SAMPLE_RATE = 24000


def _audio_array_to_wav_bytes(audio_array: np.ndarray) -> bytes:
    pcm = (audio_array * 32767).astype(np.int16)
    buf = io.BytesIO()
    wav_write(buf, _SAMPLE_RATE, pcm)
    return buf.getvalue()


def generate_clip(text: str) -> bytes:
    from bark import generate_audio
    audio = generate_audio(text, history_prompt="v2/en_speaker_2")
    return _audio_array_to_wav_bytes(audio)


def build_pool() -> None:
    logger.info("Building filler pool (%d clips)...",
                sum(len(v) for v in FILLER_TEXTS.values()))
    for category, texts in FILLER_TEXTS.items():
        for text in texts:
            try:
                wav = generate_clip(text)
                FILLER_POOL[category].append(wav)
                logger.info("  ✓ %s: %s", category, text[:40])
            except Exception as exc:
                logger.error("  ✗ filler failed (%s): %s", text[:40], exc)
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
