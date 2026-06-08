import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel

from relay_client import relay
from session_manager import SlotInfo, SlotState, session_manager

logger = logging.getLogger(__name__)
PROFILE_PATH = Path("/app/browser_profile.json")
CV_DEFAULT_PATH = Path("/app/cv_default.pdf")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await session_manager.start()
    relay.start()
    yield
    await session_manager.stop()


app = FastAPI(title="browser-svc", lifespan=lifespan)


# ── Status ─────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "slots": 4}


@app.get("/slots")
def get_slots():
    return session_manager.status()


# ── Profile ────────────────────────────────────────────────────────────────────

@app.get("/profile")
def get_profile():
    if not PROFILE_PATH.exists():
        raise HTTPException(404, "Profile not found")
    return json.loads(PROFILE_PATH.read_text())


class ProfileUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin: str | None = None
    experience_years: int | None = None
    notice_period: str | None = None
    target_roles: list[str] | None = None
    target_companies: list[str] | None = None
    skills: list[str] | None = None
    location_preference: str | None = None


@app.patch("/profile")
def update_profile(update: ProfileUpdate):
    if not PROFILE_PATH.exists():
        raise HTTPException(404, "Profile not found")
    current = json.loads(PROFILE_PATH.read_text())
    current.update(update.model_dump(exclude_none=True))
    PROFILE_PATH.write_text(json.dumps(current, indent=2))
    return current


# ── Helpers ────────────────────────────────────────────────────────────────────

def _slot_is_busy(slot_id: int) -> bool:
    return session_manager.status()[slot_id]["state"] == SlotState.BUSY


async def _apply_on_slot(slot: SlotInfo, url: str, tailor_cv: bool):
    """Apply to a job URL using an already-acquired slot (caller handles acquire/release)."""
    from job_workflow import apply_to_job

    cv_path = str(CV_DEFAULT_PATH)
    result = await apply_to_job(
        slot.page, url, cv_path,
        slot_info=slot, tailor_cv=tailor_cv,
    )
    logger.info("Apply result: %s %s → %s", result.company, result.role, result.status)
    return result


async def _run_apply(url: str, slot_id: int, tailor_cv: bool):
    slot = await session_manager.acquire(slot_id)
    screencast_started = False
    try:
        await session_manager.start_screencast(slot_id, relay)
        screencast_started = True
        await _apply_on_slot(slot, url, tailor_cv)
    except Exception:
        logger.exception("_run_apply failed for %s", url)
    finally:
        if screencast_started:
            try:
                await session_manager.stop_screencast(slot_id)
            except Exception:
                pass
        await session_manager.release(slot_id)


# ── Apply endpoints ────────────────────────────────────────────────────────────

class ApplyRequest(BaseModel):
    url: str
    slot_id: int = 1
    tailor_cv: bool = True


@app.post("/apply")
async def apply_endpoint(req: ApplyRequest, bg: BackgroundTasks):
    if req.slot_id < 1 or req.slot_id > 4:
        raise HTTPException(400, "slot_id must be 1–4")
    if _slot_is_busy(req.slot_id):
        raise HTTPException(409, f"Slot {req.slot_id} is busy")
    bg.add_task(_run_apply, req.url, req.slot_id, req.tailor_cv)
    return {"queued": True, "slot_id": req.slot_id, "url": req.url}


class DiscoverRequest(BaseModel):
    keywords: str
    platform: str = "linkedin"
    location: str = "Bangalore"
    slot_id: int = 1
    tailor_cv: bool = True


@app.post("/discover")
async def discover_endpoint(req: DiscoverRequest, bg: BackgroundTasks):
    if _slot_is_busy(req.slot_id):
        raise HTTPException(409, f"Slot {req.slot_id} is busy")

    async def run():
        from job_workflow import discover_jobs_linkedin, discover_jobs_indeed, discover_jobs_naukri
        slot = await session_manager.acquire(req.slot_id)
        screencast_started = False
        try:
            await session_manager.start_screencast(req.slot_id, relay)
            screencast_started = True
            if req.platform == "indeed":
                urls = await discover_jobs_indeed(slot.page, req.keywords, req.location)
            elif req.platform == "naukri":
                urls = await discover_jobs_naukri(slot.page, req.keywords, req.location)
            else:
                urls = await discover_jobs_linkedin(slot.page, req.keywords, req.location)
            for url in urls:
                await _apply_on_slot(slot, url, req.tailor_cv)
        except Exception:
            logger.exception("discover run() failed for keywords=%s", req.keywords)
        finally:
            if screencast_started:
                try:
                    await session_manager.stop_screencast(req.slot_id)
                except Exception:
                    pass
            await session_manager.release(req.slot_id)

    bg.add_task(run)
    return {"queued": True, "platform": req.platform, "keywords": req.keywords}


class CompanyRequest(BaseModel):
    company: str
    slot_id: int = 1
    tailor_cv: bool = True


@app.post("/company-apply")
async def company_apply_endpoint(req: CompanyRequest, bg: BackgroundTasks):
    if _slot_is_busy(req.slot_id):
        raise HTTPException(409, f"Slot {req.slot_id} is busy")

    async def run():
        from job_workflow import discover_company_roles, load_profile
        slot = await session_manager.acquire(req.slot_id)
        screencast_started = False
        try:
            await session_manager.start_screencast(req.slot_id, relay)
            screencast_started = True
            profile = load_profile()
            urls = await discover_company_roles(
                slot.page, req.company, profile.get("target_roles", [])
            )
            for url in urls:
                await _apply_on_slot(slot, url, req.tailor_cv)
        except Exception:
            logger.exception("company_apply run() failed for company=%s", req.company)
        finally:
            if screencast_started:
                try:
                    await session_manager.stop_screencast(req.slot_id)
                except Exception:
                    pass
            await session_manager.release(req.slot_id)

    bg.add_task(run)
    return {"queued": True, "company": req.company}


class ProfileMatchRequest(BaseModel):
    slot_id: int = 1
    tailor_cv: bool = True


@app.post("/profile-match")
async def profile_match_endpoint(req: ProfileMatchRequest, bg: BackgroundTasks):
    if _slot_is_busy(req.slot_id):
        raise HTTPException(409, f"Slot {req.slot_id} is busy")

    async def run():
        from job_workflow import discover_company_roles, load_profile
        profile = load_profile()
        companies = profile.get("target_companies", [])
        roles = profile.get("target_roles", [])
        slot = await session_manager.acquire(req.slot_id)
        screencast_started = False
        try:
            await session_manager.start_screencast(req.slot_id, relay)
            screencast_started = True
            for company in companies:
                urls = await discover_company_roles(slot.page, company, roles)
                for url in urls:
                    await _apply_on_slot(slot, url, req.tailor_cv)
        except Exception:
            logger.exception("profile_match run() failed")
        finally:
            if screencast_started:
                try:
                    await session_manager.stop_screencast(req.slot_id)
                except Exception:
                    pass
            await session_manager.release(req.slot_id)

    bg.add_task(run)
    return {"queued": True, "mode": "profile_match"}


# ── Interaction Endpoints ──────────────────────────────────────────────────────

class ClickRequest(BaseModel):
    x: int
    y: int


@app.post("/slots/{slot_id}/click")
async def slot_click(slot_id: int, req: ClickRequest):
    if slot_id < 0 or slot_id >= session_manager.NUM_SLOTS:
        raise HTTPException(400, f"slot_id must be 0–{session_manager.NUM_SLOTS - 1}")
    page = await session_manager.ensure_interactive(slot_id, relay)
    try:
        await page.mouse.click(req.x, req.y)
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(500, f"Click failed: {exc}")


class TypeRequest(BaseModel):
    text: str


@app.post("/slots/{slot_id}/type")
async def slot_type(slot_id: int, req: TypeRequest):
    if slot_id < 0 or slot_id >= session_manager.NUM_SLOTS:
        raise HTTPException(400, f"slot_id must be 0–{session_manager.NUM_SLOTS - 1}")
    page = await session_manager.ensure_interactive(slot_id, relay)
    try:
        await page.keyboard.type(req.text)
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(500, f"Type failed: {exc}")


class KeyRequest(BaseModel):
    key: str


@app.post("/slots/{slot_id}/key")
async def slot_key(slot_id: int, req: KeyRequest):
    if slot_id < 0 or slot_id >= session_manager.NUM_SLOTS:
        raise HTTPException(400, f"slot_id must be 0–{session_manager.NUM_SLOTS - 1}")
    page = await session_manager.ensure_interactive(slot_id, relay)
    try:
        await page.keyboard.press(req.key)
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(500, f"Keypress failed: {exc}")


class NavigateRequest(BaseModel):
    url: str


@app.post("/slots/{slot_id}/navigate")
async def slot_navigate(slot_id: int, req: NavigateRequest):
    if slot_id < 0 or slot_id >= session_manager.NUM_SLOTS:
        raise HTTPException(400, f"slot_id must be 0–{session_manager.NUM_SLOTS - 1}")
    page = await session_manager.ensure_interactive(slot_id, relay)
    url = req.url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(500, f"Navigation failed: {exc}")


@app.post("/slots/{slot_id}/reload")
async def slot_reload(slot_id: int):
    if slot_id < 0 or slot_id >= session_manager.NUM_SLOTS:
        raise HTTPException(400, f"slot_id must be 0–{session_manager.NUM_SLOTS - 1}")
    page = await session_manager.ensure_interactive(slot_id, relay)
    try:
        await page.reload(wait_until="domcontentloaded", timeout=15000)
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(500, f"Reload failed: {exc}")


@app.post("/slots/{slot_id}/back")
async def slot_back(slot_id: int):
    if slot_id < 0 or slot_id >= session_manager.NUM_SLOTS:
        raise HTTPException(400, f"slot_id must be 0–{session_manager.NUM_SLOTS - 1}")
    page = await session_manager.ensure_interactive(slot_id, relay)
    try:
        await page.go_back(wait_until="domcontentloaded", timeout=15000)
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(500, f"Go back failed: {exc}")

