"""Thin HTTP client for the browser-svc sidecar."""
import httpx

from app.config import BROWSER_SVC_URL

_ENDPOINT_MAP = {
    "browser_apply":         "/apply",
    "browser_discover":      "/discover",
    "browser_company":       "/company-apply",
    "browser_profile_match": "/profile-match",
}

_PAYLOAD_MAP = {
    "browser_apply":         lambda a: {"url": a.get("url", ""), "slot_id": 1, "tailor_cv": True},
    "browser_discover":      lambda a: {
        "keywords": a.get("keywords", ""),
        "platform": a.get("platform", "linkedin"),
        "location": a.get("location", "Bangalore"),
        "slot_id": 1,
        "tailor_cv": True,
    },
    "browser_company":       lambda a: {"company": a.get("company", ""), "slot_id": 1, "tailor_cv": True},
    "browser_profile_match": lambda a: {"slot_id": 1, "tailor_cv": True},
}


async def call_browser_svc(tool_type: str, tool_args: dict) -> str:
    endpoint = _ENDPOINT_MAP.get(tool_type, "/apply")
    payload_fn = _PAYLOAD_MAP.get(tool_type, lambda a: {})
    payload = payload_fn(tool_args)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(f"{BROWSER_SVC_URL}{endpoint}", json=payload)
            if r.status_code == 409:
                return f"[browser-svc: slot busy — task will run when a slot frees]"
            r.raise_for_status()
            return str(r.json())
    except Exception as exc:
        return f"[browser-svc unreachable: {exc}]"
