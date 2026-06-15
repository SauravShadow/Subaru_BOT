"""HTTP client for the bark-svc sidecar. Returns None on any failure — callers degrade gracefully."""
import logging
import httpx
from app import config

logger = logging.getLogger(__name__)
_TIMEOUT = 15.0


async def speak(text: str, emotion: str = "calm", voice: str | None = None) -> str | None:
    """POST /speak → base64 WAV string, or None if bark-svc is unavailable."""
    try:
        payload: dict = {"text": text, "emotion": emotion}
        if voice:
            payload["voice"] = voice
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{config.BARK_SVC_URL}/speak",
                json=payload,
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()["audio"]
    except Exception as exc:
        logger.warning("bark_client.speak failed: %s", exc)
        return None


async def sing(lyrics: str, style: str = "expressive") -> str | None:
    """POST /sing → base64 WAV string, or None if bark-svc is unavailable."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{config.BARK_SVC_URL}/sing",
                json={"lyrics": lyrics, "style": style},
                timeout=30.0,
            )
            resp.raise_for_status()
            return resp.json()["audio"]
    except Exception as exc:
        logger.warning("bark_client.sing failed: %s", exc)
        return None


async def get_filler(context: str = "") -> str | None:
    """GET /filler → base64 WAV string, or None if unavailable / pool not ready."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{config.BARK_SVC_URL}/filler",
                params={"context": context},
                timeout=5.0,
            )
            resp.raise_for_status()
            return resp.json().get("audio")
    except Exception as exc:
        logger.warning("bark_client.get_filler failed: %s", exc)
        return None
