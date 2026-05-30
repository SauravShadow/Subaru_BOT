"""
Design preview writer.

write_preview() is called by Emilia via the [WRITE_PREVIEW:] tool tag.
It writes agent-generated HTML to the live preview iframe target file.
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Inside the container: /app = project root
PREVIEW_FILE = Path("/app/app/static/previews/index.html")


def write_preview(html_content: str) -> str:
    """Write agent-generated HTML to the live design preview file."""
    try:
        PREVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
        PREVIEW_FILE.write_text(html_content, encoding="utf-8")
        logger.info("Design preview updated (%d chars)", len(html_content))
        return f"Preview written ({len(html_content)} chars). Visible at /static/previews/index.html"
    except Exception as exc:
        logger.error("write_preview failed: %s", exc)
        return f"[write_preview error: {exc}]"
