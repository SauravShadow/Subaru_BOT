"""IMAGE handler — converts [GENERATE_IMAGE: description] to a generated image."""
import asyncio
import base64
import re
import urllib.parse
import urllib.request
import logging
from typing import Callable, Awaitable

logger  = logging.getLogger(__name__)
TAG     = "GENERATE_IMAGE"
PATTERN = re.compile(r'\[GENERATE_IMAGE:\s*(.*?)\]', re.DOTALL)

Sender = Callable[[dict], Awaitable[None]]


async def _fetch_image(prompt: str) -> dict:
    try:
        encoded = urllib.parse.quote(prompt)
        url = (
            f"https://image.pollinations.ai/prompt/{encoded}"
            f"?width=512&height=512&nologo=true"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

        def _do():
            resp = urllib.request.urlopen(req, timeout=45)
            return resp.read(), resp.headers.get("Content-Type", "image/png")

        data, mime = await asyncio.get_event_loop().run_in_executor(None, _do)
        return {"ok": True, "data": base64.b64encode(data).decode("ascii"),
                "mime_type": mime, "size": len(data)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def handle(args: str, agent_id: str, send: Sender) -> tuple[str, bool]:
    prompt = args.strip()
    await send({"type": "tool_call", "agent": agent_id,
                "tool": "generate_image", "label": "Generating Image",
                "path": prompt[:60]})
    result = await _fetch_image(prompt)
    if result.get("ok"):
        await send({
            "type":  "assistant",
            "agent": agent_id,
            "message": {"content": [{
                "type":       "image",
                "media_type": result["mime_type"],
                "data":       result["data"],
            }]},
        })
        logger.info("Image sent for prompt: %s", prompt[:60])
    else:
        logger.error("Image generation failed: %s", result.get("error"))
    return "", False
