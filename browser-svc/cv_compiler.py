import asyncio
import logging
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from session_manager import SlotInfo

logger = logging.getLogger(__name__)

CV_TEMPLATE_PATH = Path("/app/cv_template.tex")
CV_EXPORTS_DIR = Path("/app/cv_exports")
CV_DEFAULT_PATH = Path("/app/cv_default.pdf")


async def _compile_latex(tex_source: str, dest: Path) -> bool:
    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        tex_file = tmp_path / "cv.tex"
        tex_file.write_text(tex_source)
        proc = await asyncio.create_subprocess_exec(
            "tectonic", str(tex_file), "-o", str(tmp_path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0:
            logger.warning("tectonic compile failed: %s", stderr.decode(errors="replace")[-2000:])
            return False
        pdf_file = tmp_path / "cv.pdf"
        if not pdf_file.exists():
            return False
        CV_EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(pdf_file.read_bytes())
        return True


async def tailor_and_compile(
    job_description: str,
    company: str,
    role: str,
    slot_info: Optional["SlotInfo"] = None,
) -> Path:
    """Tailor cv_template.tex to the job description with Gemini, then compile it locally
    with Tectonic. Returns the exported PDF path, or CV_DEFAULT_PATH on any failure."""
    from cv_enhancer import enhance_cv, apply_edits

    if not CV_TEMPLATE_PATH.exists():
        logger.warning("CV template not found at %s — using default CV", CV_TEMPLATE_PATH)
        return CV_DEFAULT_PATH

    try:
        latex = CV_TEMPLATE_PATH.read_text()

        if slot_info:
            slot_info.action = "Tailoring CV with Gemini"
        cv_edit = await enhance_cv(job_description, latex)
        new_latex = apply_edits(latex, cv_edit.edits)

        if slot_info:
            slot_info.action = f"Compiling CV ({len(cv_edit.keywords)} keywords injected)"
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_company = company.replace(" ", "_").replace("/", "_")
        safe_role = role.replace(" ", "_").replace("/", "_")
        dest = CV_EXPORTS_DIR / f"cv_{safe_company}_{safe_role}_{date_str}.pdf"

        if not await _compile_latex(new_latex, dest):
            raise RuntimeError("Tectonic compile failed")

        logger.info("CV compiled: %s", dest.name)
        return dest

    except Exception as exc:
        logger.warning("CV compile pipeline failed (%s) — using default CV", exc)
        return CV_DEFAULT_PATH
