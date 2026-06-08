import asyncio
import json
import os
from dataclasses import dataclass

import google.genai as genai

_SYSTEM = (
    "You are an expert LaTeX CV editor. Given a job description and a LaTeX CV source, "
    "output ONLY a JSON object with two fields:\n"
    "- \"edits\": list of {\"old\": str, \"new\": str} pairs (LaTeX block replacements)\n"
    "- \"keywords\": list of keywords injected\n\n"
    "Rules: tailor to highlight relevant skills, inject up to 8 keywords naturally, "
    "keep changes minimal and professional. Output valid JSON only, no markdown."
)


@dataclass
class CVEdit:
    edits: list[dict[str, str]]
    keywords: list[str]


async def enhance_cv(job_description: str, latex_source: str) -> CVEdit:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    response = await asyncio.to_thread(
        client.models.generate_content,
        model="gemini-3.5-flash",
        contents=(
            f"{_SYSTEM}\n\n"
            f"JOB DESCRIPTION:\n{job_description}\n\nLATEX CV:\n{latex_source}"
        ),
    )
    raw = (response.text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    raw = raw.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Gemini returned non-JSON response: {raw!r}") from e
    return CVEdit(edits=data.get("edits", []), keywords=data.get("keywords", []))


def apply_edits(latex_source: str, edits: list[dict[str, str]]) -> str:
    result = latex_source
    for edit in edits:
        old, new = edit.get("old", ""), edit.get("new", "")
        if old and old in result:
            result = result.replace(old, new, 1)
    return result
