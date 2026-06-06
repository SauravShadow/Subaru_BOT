import json
import os
from dataclasses import dataclass

import anthropic

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
    client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=_SYSTEM,
        messages=[{
            "role": "user",
            "content": f"JOB DESCRIPTION:\n{job_description}\n\nLATEX CV:\n{latex_source}",
        }],
    )
    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    raw = raw.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude returned non-JSON response: {raw!r}") from e
    return CVEdit(edits=data.get("edits", []), keywords=data.get("keywords", []))


def apply_edits(latex_source: str, edits: list[dict[str, str]]) -> str:
    result = latex_source
    for edit in edits:
        old, new = edit.get("old", ""), edit.get("new", "")
        if old and old in result:
            result = result.replace(old, new, 1)
    return result
