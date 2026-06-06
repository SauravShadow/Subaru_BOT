import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import overleaf_pipeline as op


@pytest.mark.asyncio
async def test_tailor_and_export_no_credentials_returns_default():
    page = AsyncMock()
    original_email = op.OVERLEAF_EMAIL
    original_url = op.OVERLEAF_PROJECT_URL
    op.OVERLEAF_EMAIL = ""
    op.OVERLEAF_PROJECT_URL = ""

    result = await op.tailor_and_export(page, "JD text", "Stripe", "Backend")

    op.OVERLEAF_EMAIL = original_email
    op.OVERLEAF_PROJECT_URL = original_url
    assert result == op.CV_DEFAULT_PATH


@pytest.mark.asyncio
async def test_tailor_and_export_returns_default_on_login_error():
    page = AsyncMock()
    page.goto = AsyncMock(side_effect=Exception("Network error"))

    with patch.object(op, "OVERLEAF_EMAIL", "test@test.com"), \
         patch.object(op, "OVERLEAF_PROJECT_URL", "https://overleaf.com/project/abc"):
        result = await op.tailor_and_export(page, "JD", "CRED", "ML")

    assert result == op.CV_DEFAULT_PATH


def test_cv_exports_dir_is_inside_app():
    assert str(op.CV_EXPORTS_DIR) == "/app/cv_exports"


def test_cv_default_path_is_inside_app():
    assert str(op.CV_DEFAULT_PATH) == "/app/cv_default.pdf"
