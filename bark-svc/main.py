"""Bark TTS sidecar — /speak /sing /filler /health"""
import base64
import io
import logging
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel
from scipy.io.wavfile import write as wav_write

import filler_pool

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

_model_ready = False
_SAMPLE_RATE = 24000

EMOTION_PROFILES = {
    "excited":   {"speaker": "v2/en_speaker_6", "temperature": 0.9},
    "calm":      {"speaker": "v2/en_speaker_2", "temperature": 0.6},
    "sad":       {"speaker": "v2/en_speaker_3", "temperature": 0.5},
    "whisper":   {"speaker": "v2/en_speaker_0", "temperature": 0.4},
    "energetic": {"speaker": "v2/en_speaker_9", "temperature": 1.0},
}
DEFAULT_EMOTION = EMOTION_PROFILES["calm"]

STYLE_SPEAKER_MAP = {
    "hip hop":   "v2/en_speaker_6",
    "rap":       "v2/en_speaker_6",
    "calm":      "v2/en_speaker_2",
    "soft":      "v2/en_speaker_0",
    "slow":      "v2/en_speaker_3",
    "fast":      "v2/en_speaker_9",
    "energetic": "v2/en_speaker_9",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model_ready
    logger.info("Loading Bark model...")
    from bark import preload_models
    preload_models()
    logger.info("Bark model loaded. Building filler pool...")
    filler_pool.build_pool()
    _model_ready = True
    logger.info("bark-svc ready.")
    yield


app = FastAPI(lifespan=lifespan)


def _array_to_b64(audio: np.ndarray) -> str:
    pcm = (audio * 32767).astype(np.int16)
    buf = io.BytesIO()
    wav_write(buf, _SAMPLE_RATE, pcm)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _style_to_speaker(style: str) -> str:
    style_lower = style.lower()
    for keyword, speaker in STYLE_SPEAKER_MAP.items():
        if keyword in style_lower:
            return speaker
    return "v2/en_speaker_6"


@app.get("/health")
def health():
    return {"ready": _model_ready}


class SpeakRequest(BaseModel):
    text: str
    emotion: str = "calm"
    agent_id: str = ""


@app.post("/speak")
async def speak(req: SpeakRequest):
    from bark import generate_audio
    profile = EMOTION_PROFILES.get(req.emotion, DEFAULT_EMOTION)
    audio   = generate_audio(req.text, history_prompt=profile["speaker"])
    return {"audio": _array_to_b64(audio)}


class SingRequest(BaseModel):
    lyrics: str
    style:  str = "expressive"


@app.post("/sing")
async def sing(req: SingRequest):
    from bark import generate_audio
    speaker   = _style_to_speaker(req.style)
    bark_text = f"♪ {req.lyrics} ♪"
    audio     = generate_audio(bark_text, history_prompt=speaker)
    return {"audio": _array_to_b64(audio)}


@app.get("/filler")
def filler(context: str = ""):
    wav = filler_pool.pick(context)
    if wav is None:
        return {"audio": None}
    return {"audio": filler_pool.wav_to_b64(wav)}
