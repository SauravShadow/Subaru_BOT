import pytest
from pathlib import Path
from unittest.mock import patch


def test_write_preview_creates_file(tmp_path):
    preview_file = tmp_path / "previews" / "index.html"
    with patch("app.services.browser.PREVIEW_FILE", preview_file):
        from app.services.browser import write_preview
        result = write_preview("<html><body>hello</body></html>")
    assert preview_file.exists()
    assert preview_file.read_text() == "<html><body>hello</body></html>"
    assert "Preview written" in result


def test_write_preview_returns_error_string_on_failure():
    from app.services.browser import write_preview
    # Write to an invalid path (root-owned location)
    with patch("app.services.browser.PREVIEW_FILE", Path("/proc/invalid_test_path/index.html")):
        result = write_preview("<html>test</html>")
    assert "write_preview error" in result


def test_write_preview_encoding(tmp_path):
    preview_file = tmp_path / "index.html"
    html = "<html><body>日本語テスト</body></html>"
    with patch("app.services.browser.PREVIEW_FILE", preview_file):
        from app.services.browser import write_preview
        write_preview(html)
    assert preview_file.read_text(encoding="utf-8") == html
