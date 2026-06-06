import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from playwright.async_api import Page
    from session_manager import SlotInfo

logger = logging.getLogger(__name__)

OVERLEAF_EMAIL = os.environ.get("OVERLEAF_EMAIL", "")
OVERLEAF_PASSWORD = os.environ.get("OVERLEAF_PASSWORD", "")
OVERLEAF_PROJECT_URL = os.environ.get("OVERLEAF_PROJECT_URL", "")
CV_EXPORTS_DIR = Path("/app/cv_exports")
CV_DEFAULT_PATH = Path("/app/cv_default.pdf")


async def _login(page: "Page") -> None:
    await page.goto("https://www.overleaf.com/login", wait_until="networkidle")
    await page.fill("input[name='email']", OVERLEAF_EMAIL)
    await page.fill("input[name='password']", OVERLEAF_PASSWORD)
    await page.click("button[type='submit']")
    await page.wait_for_url("**/project**", timeout=15000)


async def _open_project(page: "Page") -> None:
    await page.goto(OVERLEAF_PROJECT_URL, wait_until="networkidle")
    try:
        source_btn = page.locator("button:has-text('Source')")
        if await source_btn.is_visible(timeout=3000):
            await source_btn.click()
            await asyncio.sleep(1)
    except Exception:
        pass


async def _get_latex_source(page: "Page") -> str:
    return await page.evaluate(
        "() => window._codeMirror?.getValue() "
        "|| document.querySelector('.cm-content')?.textContent || ''"
    )


async def _set_latex_source(page: "Page", content: str) -> None:
    escaped = content.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
    await page.evaluate(f"""
        () => {{
            const cm = window._codeMirror;
            if (cm) {{
                cm.setValue(`{escaped}`);
            }} else {{
                const editor = document.querySelector('.cm-content');
                if (editor) {{
                    editor.focus();
                    document.execCommand('selectAll');
                    document.execCommand('insertText', false, `{escaped}`);
                }}
            }}
        }}
    """)


async def _compile_and_wait(page: "Page", timeout: int = 60) -> bool:
    try:
        await page.click(
            "button[data-testid='recompile-btn'], button:has-text('Recompile')",
            timeout=5000,
        )
    except Exception:
        await page.keyboard.press("Control+Enter")
    try:
        await page.wait_for_selector(
            "[data-testid='pdf-viewer'], .pdf-viewer, iframe[src*='pdf']",
            timeout=timeout * 1000,
        )
        return True
    except Exception:
        return False


async def _download_pdf(page: "Page", company: str, role: str) -> Path:
    CV_EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_company = company.replace(" ", "_").replace("/", "_")
    safe_role = role.replace(" ", "_").replace("/", "_")
    dest = CV_EXPORTS_DIR / f"cv_{safe_company}_{safe_role}_{date_str}.pdf"

    async with page.expect_download() as dl_info:
        try:
            await page.click("a[download], button:has-text('Download PDF')", timeout=5000)
        except Exception:
            pass
    dl = await dl_info.value
    await dl.save_as(str(dest))
    return dest


async def tailor_and_export(
    page: "Page",
    job_description: str,
    company: str,
    role: str,
    slot_info: Optional["SlotInfo"] = None,
) -> Path:
    """Run the full Overleaf CV pipeline. Returns PDF path or CV_DEFAULT_PATH on failure."""
    from cv_enhancer import enhance_cv, apply_edits

    if not OVERLEAF_EMAIL or not OVERLEAF_PROJECT_URL:
        logger.warning("Overleaf credentials not configured — using default CV")
        return CV_DEFAULT_PATH

    try:
        if slot_info:
            slot_info.action = "Logging in to Overleaf"
        if "overleaf.com" not in page.url:
            await _login(page)

        if slot_info:
            slot_info.action = "Opening project"
        await _open_project(page)

        if slot_info:
            slot_info.action = "Reading LaTeX source"
        latex = await _get_latex_source(page)
        if not latex.strip():
            raise ValueError("Could not read LaTeX source from Overleaf")

        if slot_info:
            slot_info.action = "Tailoring CV with Claude"
        cv_edit = await enhance_cv(job_description, latex)
        new_latex = apply_edits(latex, cv_edit.edits)

        if slot_info:
            slot_info.action = f"Compiling ({len(cv_edit.keywords)} keywords injected)"
        await _set_latex_source(page, new_latex)
        ok = await _compile_and_wait(page)
        if not ok:
            raise TimeoutError("Compile timed out")

        if slot_info:
            slot_info.action = "Downloading PDF"
        pdf_path = await _download_pdf(page, company, role)
        logger.info("CV exported: %s", pdf_path.name)
        return pdf_path

    except Exception as exc:
        logger.warning("Overleaf pipeline failed (%s) — using default CV", exc)
        return CV_DEFAULT_PATH
