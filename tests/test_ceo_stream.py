"""run_claude_agent streams CEO assistant text as ceo_stream deltas."""
import pytest
from unittest.mock import AsyncMock, patch


class _FakeStdout:
    def __init__(self, lines):
        self._lines = [l.encode() for l in lines]

    def __aiter__(self):
        async def gen():
            for l in self._lines:
                yield l
        return gen()


class _FakeProc:
    def __init__(self, lines):
        self.stdout = _FakeStdout(lines)
        self.stderr = AsyncMock()
        self.stderr.read = AsyncMock(return_value=b"")
        self.returncode = 0

    async def wait(self):
        return 0


@pytest.mark.asyncio
async def test_ceo_text_streams_as_ceo_stream():
    import app.agents.runner as runner
    import json

    line = json.dumps({
        "type": "assistant",
        "message": {"role": "assistant",
                    "content": [{"type": "text", "text": "Planning the site"}]},
    })
    proc = _FakeProc([line])
    sent = []

    async def send(data):
        sent.append(data)

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as cse, \
         patch.object(runner, "_build_claude_prompt", new_callable=AsyncMock) as bp:
        cse.return_value = proc
        bp.return_value = "prompt"
        result = await runner.run_claude_agent("ceo", "build a books site", send)

    assert "Planning the site" in result
    stream_events = [s for s in sent if s.get("type") == "ceo_stream"]
    assert any("Planning the site" in s.get("delta", "") for s in stream_events)
