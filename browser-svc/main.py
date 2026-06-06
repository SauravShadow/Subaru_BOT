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
    return {"status": "ok", "slots": 5}


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


async def _apply_on_slot(slot: SlotInfo, url: str, use_overleaf: bool):
    """Apply to a job URL using an already-acquired slot (caller handles acquire/release)."""
    from job_workflow import apply_to_job

    overleaf_page = None
    overleaf_acquired = False

    if use_overleaf and not _slot_is_busy(0):
        try:
            overleaf_slot = await session_manager.acquire(0)
            overleaf_acquired = True
        except Exception:
            logger.warning("Could not acquire Overleaf slot for %s — applying without CV tailor", url)

    if overleaf_acquired:
        try:
            await session_manager.start_screencast(0, relay)
            overleaf_page = overleaf_slot.page
        except Exception:
            logger.warning("Overleaf screencast failed for %s — applying without CV tailor", url)
            overleaf_page = None

    try:
        cv_path = str(CV_DEFAULT_PATH)
        result = await apply_to_job(
            slot.page, url, cv_path,
            slot_info=slot, overleaf_page=overleaf_page,
        )
        logger.info("Apply result: %s %s → %s", result.company, result.role, result.status)
        return result
    finally:
        if overleaf_acquired:
            try:
                await session_manager.stop_screencast(0)
            except Exception:
                pass
            try:
                await session_manager.release(0)
            except Exception:
                pass


async def _run_apply(url: str, slot_id: int, use_overleaf: bool):
    slot = await session_manager.acquire(slot_id)
    screencast_started = False
    try:
        await session_manager.start_screencast(slot_id, relay)
        screencast_started = True
        await _apply_on_slot(slot, url, use_overleaf)
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
    use_overleaf: bool = True


@app.post("/apply")
async def apply_endpoint(req: ApplyRequest, bg: BackgroundTasks):
    if req.slot_id < 1 or req.slot_id > 4:
        raise HTTPException(400, "slot_id must be 1–4 (slot 0 is reserved for Overleaf)")
    if _slot_is_busy(req.slot_id):
        raise HTTPException(409, f"Slot {req.slot_id} is busy")
    bg.add_task(_run_apply, req.url, req.slot_id, req.use_overleaf)
    return {"queued": True, "slot_id": req.slot_id, "url": req.url}


class DiscoverRequest(BaseModel):
    keywords: str
    platform: str = "linkedin"
    location: str = "Bangalore"
    slot_id: int = 1
    use_overleaf: bool = True


@app.post("/discover")
async def discover_endpoint(req: DiscoverRequest, bg: BackgroundTasks):
    if _slot_is_busy(req.slot_id):
        raise HTTPException(409, f"Slot {req.slot_id} is busy")

    async def run():
        from job_workflow import discover_jobs_linkedin, discover_jobs_indeed
        slot = await session_manager.acquire(req.slot_id)
        screencast_started = False
        try:
            await session_manager.start_screencast(req.slot_id, relay)
            screencast_started = True
            if req.platform == "indeed":
                urls = await discover_jobs_indeed(slot.page, req.keywords, req.location)
            else:
                urls = await discover_jobs_linkedin(slot.page, req.keywords, req.location)
            for url in urls:
                await _apply_on_slot(slot, url, req.use_overleaf)
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
    use_overleaf: bool = True


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
                await _apply_on_slot(slot, url, req.use_overleaf)
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
    use_overleaf: bool = True


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
                    await _apply_on_slot(slot, url, req.use_overleaf)
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
