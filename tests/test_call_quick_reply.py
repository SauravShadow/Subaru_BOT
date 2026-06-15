import pytest
from unittest.mock import MagicMock, patch
from app.services.call_store import Turn


@pytest.mark.asyncio
async def test_quick_reply_uses_gemini_flash(monkeypatch):
    from app.agents import call_prep
    monkeypatch.setattr(call_prep.config, "GEMINI_API_KEY", "key")

    fake_resp = MagicMock(text="Sure, 7pm works for two people.")
    fake_models = MagicMock()
    fake_models.generate_content.return_value = fake_resp
    fake_client = MagicMock(models=fake_models)

    with patch("google.genai.Client", return_value=fake_client):
        out = await call_prep.quick_reply(
            goal="Book a table for 2 at 7pm",
            transcript=[Turn(speaker="them", text="What time did you want?")],
            language="en")
    assert "7pm" in out
    assert fake_models.generate_content.call_args.kwargs["model"] == "gemini-3.5-flash"


@pytest.mark.asyncio
async def test_quick_reply_falls_back_to_claude_cli(monkeypatch):
    """When Gemini fails (e.g. quota), quick_reply uses the Claude CLI."""
    from app.agents import call_prep
    monkeypatch.setattr(call_prep.config, "GEMINI_API_KEY", "key")

    with patch("google.genai.Client", side_effect=RuntimeError("429 RESOURCE_EXHAUSTED")):
        async def fake_cli(prompt, timeout=60.0):
            return "Sure, I can help with that.\nextra line that should be dropped"
        monkeypatch.setattr(call_prep, "_claude_cli_generate", fake_cli)
        out = await call_prep.quick_reply(
            goal="Help the caller",
            transcript=[Turn(speaker="them", text="Can you assist?")],
            language="en")
    assert out == "Sure, I can help with that."


@pytest.mark.asyncio
async def test_quick_reply_safe_fallback_without_key(monkeypatch):
    from app.agents import call_prep
    monkeypatch.setattr(call_prep.config, "GEMINI_API_KEY", "")
    out = await call_prep.quick_reply("goal", [Turn("them", "hi")], "en")
    assert isinstance(out, str) and out  # non-empty safe fallback
