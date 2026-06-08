import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from cv_enhancer import CVEdit
import cv_compiler
from cv_compiler import tailor_and_compile, CV_DEFAULT_PATH


@pytest.mark.asyncio
async def test_tailor_and_compile_returns_default_when_template_missing(tmp_path):
    with patch.object(cv_compiler, "CV_TEMPLATE_PATH", tmp_path / "missing.tex"):
        result = await tailor_and_compile("JD text", "Acme", "Backend Engineer")
    assert result == CV_DEFAULT_PATH


@pytest.mark.asyncio
async def test_tailor_and_compile_returns_default_on_compile_failure(tmp_path):
    template = tmp_path / "cv_template.tex"
    template.write_text(r"\documentclass{article}\begin{document}Skills: Django\end{document}")

    fake_edit = CVEdit(edits=[{"old": "Django", "new": "FastAPI"}], keywords=["FastAPI"])

    with patch.object(cv_compiler, "CV_TEMPLATE_PATH", template), \
         patch("cv_enhancer.enhance_cv", new=AsyncMock(return_value=fake_edit)), \
         patch.object(cv_compiler, "_compile_latex", new=AsyncMock(return_value=False)):
        result = await tailor_and_compile("JD text", "Acme", "Backend Engineer")

    assert result == CV_DEFAULT_PATH


@pytest.mark.asyncio
async def test_tailor_and_compile_returns_exported_pdf_on_success(tmp_path):
    template = tmp_path / "cv_template.tex"
    template.write_text(r"\documentclass{article}\begin{document}Skills: Django\end{document}")
    exports_dir = tmp_path / "cv_exports"

    fake_edit = CVEdit(edits=[{"old": "Django", "new": "FastAPI"}], keywords=["FastAPI"])

    async def fake_compile(tex_source, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"%PDF-fake")
        return True

    with patch.object(cv_compiler, "CV_TEMPLATE_PATH", template), \
         patch.object(cv_compiler, "CV_EXPORTS_DIR", exports_dir), \
         patch("cv_enhancer.enhance_cv", new=AsyncMock(return_value=fake_edit)), \
         patch.object(cv_compiler, "_compile_latex", new=AsyncMock(side_effect=fake_compile)):
        result = await tailor_and_compile("JD text", "Acme Corp", "Backend Engineer")

    assert result != CV_DEFAULT_PATH
    assert result.exists()
    assert result.name.startswith("cv_Acme_Corp_Backend_Engineer_")
