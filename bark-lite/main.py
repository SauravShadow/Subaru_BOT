"""Lightweight TTS sidecar using gTTS — replaces espeak-ng. Same API: /speak /sing /filler /health"""
import io
import base64
import logging
import subprocess

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import filler_pool

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Speed multipliers per emotion (applied via pydub frame_rate trick)
EMOTION_SPEED = {
    "excited":   1.15,
    "calm":      1.0,
    "sad":       0.85,
    "whisper":   0.9,
    "energetic": 1.25,
}

EMOTION_SLOW = {
    "sad": True,
}

app = FastAPI()


MAX_TTS_CHARS = 200


def _gtts_wav(text: str, emotion: str = "calm") -> bytes:
    """Generate WAV bytes via gTTS → pydub speed adjust → WAV export.

    Text is truncated to MAX_TTS_CHARS and output downsampled to 11025 Hz mono
    to keep audio payloads manageable (~4x smaller than full quality).
    """
    from gtts import gTTS
    from pydub import AudioSegment

    # Truncate long text at a word boundary to cap audio duration
    if len(text) > MAX_TTS_CHARS:
        text = text[:MAX_TTS_CHARS].rsplit(" ", 1)[0] + "…"

    slow = EMOTION_SLOW.get(emotion, False)
    tts = gTTS(text=text, lang="en", slow=slow)
    mp3_buf = io.BytesIO()
    tts.write_to_fp(mp3_buf)
    mp3_buf.seek(0)

    audio = AudioSegment.from_mp3(mp3_buf)
    speed = EMOTION_SPEED.get(emotion, 1.0)
    if speed != 1.0:
        audio = audio._spawn(
            audio.raw_data,
            overrides={"frame_rate": int(audio.frame_rate * speed)},
        ).set_frame_rate(audio.frame_rate)

    # Downsample to 11025 Hz mono — reduces payload ~4x; fine for speech
    audio = audio.set_frame_rate(11025).set_channels(1)

    wav_buf = io.BytesIO()
    audio.export(wav_buf, format="wav")
    return wav_buf.getvalue()


def _espeak_fallback(text: str) -> bytes:
    """Fallback to espeak-ng if gTTS fails (e.g. no internet)."""
    result = subprocess.run(
        ["espeak-ng", "--stdout", "-s", "140", "-p", "50", text],
        capture_output=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(f"espeak-ng failed: {result.stderr.decode()}")
    return result.stdout


def _speak_wav(text: str, emotion: str = "calm") -> bytes:
    try:
        return _gtts_wav(text, emotion)
    except Exception as exc:
        logger.warning("gTTS failed (%s), falling back to espeak-ng", exc)
        return _espeak_fallback(text)


def _wav_to_b64(wav_bytes: bytes) -> str:
    return base64.b64encode(wav_bytes).decode("ascii")


@app.on_event("startup")
async def startup():
    logger.info("bark-lite starting — building filler pool...")
    filler_pool.build_pool()
    logger.info("bark-lite ready.")


@app.get("/health")
def health():
    return {"ready": True}


class SpeakRequest(BaseModel):
    text: str
    emotion: str = "calm"
    agent_id: str = ""


@app.post("/speak")
async def speak(req: SpeakRequest):
    try:
        wav = _speak_wav(req.text, req.emotion)
    except Exception as exc:
        logger.error("speak failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    return {"audio": _wav_to_b64(wav)}


class SingRequest(BaseModel):
    lyrics: str
    style: str = "expressive"


@app.post("/sing")
async def sing(req: SingRequest):
    try:
        wav = _speak_wav(req.lyrics, "energetic")
    except Exception as exc:
        logger.error("sing failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    return {"audio": _wav_to_b64(wav)}


@app.get("/filler")
def filler(context: str = ""):
    wav = filler_pool.pick(context)
    if wav is None:
        return {"audio": None}
    return {"audio": filler_pool.wav_to_b64(wav)}
