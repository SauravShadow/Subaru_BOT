import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from cv_enhancer import CVEdit, apply_edits

SAMPLE_LATEX = r"""\documentclass{article}
\begin{document}
\section{Skills}
Python, Django, REST APIs
\end{document}"""


def test_apply_edits_replaces_text():
    edits = [{"old": "Django, REST APIs", "new": "FastAPI, REST APIs, asyncio"}]
    result = apply_edits(SAMPLE_LATEX, edits)
    assert "FastAPI" in result
    assert "Django" not in result


def test_apply_edits_skips_missing_old():
    edits = [{"old": "NOTEXIST", "new": "something"}]
    result = apply_edits(SAMPLE_LATEX, edits)
    assert result == SAMPLE_LATEX


def test_apply_edits_multiple():
    edits = [
        {"old": "Django", "new": "FastAPI"},
        {"old": "REST APIs", "new": "REST APIs, async"},
    ]
    result = apply_edits(SAMPLE_LATEX, edits)
    assert "FastAPI" in result
    assert "async" in result


@pytest.mark.asyncio
async def test_enhance_cv_calls_anthropic_and_parses():
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"edits": [{"old": "Django", "new": "FastAPI"}], "keywords": ["FastAPI", "async"]}'
        )
    ]

    with patch("cv_enhancer.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            from cv_enhancer import enhance_cv
            result = await enhance_cv("FastAPI JD", SAMPLE_LATEX)

    assert isinstance(result, CVEdit)
    assert result.keywords == ["FastAPI", "async"]
    assert result.edits == [{"old": "Django", "new": "FastAPI"}]


@pytest.mark.asyncio
async def test_enhance_cv_strips_markdown_fences():
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='```json\n{"edits": [], "keywords": ["k1"]}\n```'
        )
    ]

    with patch("cv_enhancer.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            from cv_enhancer import enhance_cv
            result = await enhance_cv("JD", SAMPLE_LATEX)

    assert result.keywords == ["k1"]
