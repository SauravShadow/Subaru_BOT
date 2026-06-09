import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from urllib.parse import urlparse

if TYPE_CHECKING:
    from playwright.async_api import Page
    from session_manager import SlotInfo

logger = logging.getLogger(__name__)
PROFILE_PATH = Path("/app/browser_profile.json")


def load_profile() -> dict:
    try:
        return json.loads(PROFILE_PATH.read_text())
    except FileNotFoundError:
        raise RuntimeError(f"Browser profile not found at {PROFILE_PATH}") from None
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Browser profile JSON is malformed: {exc}") from exc


@dataclass
class ApplyResult:
    url: str
    company: str
    role: str
    status: str  # "applied" | "failed" | "captcha" | "skipped"
    cv_path: str = ""
    keywords: list[str] = field(default_factory=list)
    error: str = ""


# ── Field resolver ─────────────────────────────────────────────────────────────

_FIELD_PATTERNS = [
    (r"(?i)first.?name|fname", "first_name"),
    (r"(?i)last.?name|lname|surname", "last_name"),
    (r"(?i)full.?name|your.?name", "full_name"),
    (r"(?i)email", "email"),
    (r"(?i)phone|mobile|contact", "phone"),
    (r"(?i)linkedin", "linkedin"),
    (r"(?i)experience|years", "experience_years"),
    (r"(?i)notice|availability", "notice_period"),
    (r"(?i)location|city", "location_preference"),
]


def _resolve_field(label_text: str, profile: dict) -> Optional[str]:
    full_name = profile.get("name", "")
    parts = full_name.split(" ", 1)
    resolved = {
        "first_name": parts[0] if parts else "",
        "last_name": parts[1] if len(parts) > 1 else "",
        "full_name": full_name,
        "email": profile.get("email", ""),
        "phone": profile.get("phone", ""),
        "linkedin": profile.get("linkedin", ""),
        "experience_years": str(profile.get("experience_years", "")),
        "notice_period": profile.get("notice_period", ""),
        "location_preference": profile.get("location_preference", ""),
    }
    for pattern, field_key in _FIELD_PATTERNS:
        if re.search(pattern, label_text):
            return resolved.get(field_key, "")
    return None


_CARRIER = {"careers", "jobs", "apply", "boards", "hire", "work", "talent"}


def _guess_company(url: str) -> str:
    host = urlparse(url).netloc.lower()
    parts = host.replace("www.", "").split(".")
    label = parts[0] if parts[0] not in _CARRIER else (parts[-2] if len(parts) >= 2 else parts[0])
    return label.capitalize() if label else "Unknown"


# ── Job description extraction ─────────────────────────────────────────────────

async def fetch_job_description(page: "Page", url: str) -> str:
    from stealth import scroll_to_read
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await scroll_to_read(page)
    for selector in [
        "[data-testid='jobDescriptionText']",
        ".jobs-description__content",
        ".job-description",
        ".description__text",
        "#job-description",
        "article",
        "main",
    ]:
        try:
            el = page.locator(selector).first
            if await el.is_visible(timeout=2000):
                return await el.inner_text()
        except Exception:
            continue
    return await page.inner_text("body") or ""


# ── Form filling ──────────────────────────────────────────────────────────────

async def fill_form_fields(page: "Page", profile: dict) -> int:
    from stealth import human_click_delay
    filled = 0
    inputs = await page.locator("input:visible, textarea:visible").all()
    for inp in inputs:
        try:
            inp_id = await inp.get_attribute("id") or ""
            inp_name = await inp.get_attribute("name") or ""
            inp_placeholder = await inp.get_attribute("placeholder") or ""
            inp_aria = await inp.get_attribute("aria-label") or ""
            label_text = ""
            if inp_id and re.match(r'^[\w\-]+$', inp_id):
                label_el = page.locator(f"label[for='{inp_id}']")
                if await label_el.count() > 0:
                    label_text = await label_el.first.inner_text()
            search_text = " ".join([label_text, inp_name, inp_placeholder, inp_aria])
            value = _resolve_field(search_text, profile)
            if value:
                await inp.fill(value)
                filled += 1
                await human_click_delay(100, 300)
        except Exception:
            continue
    return filled


async def attach_cv(page: "Page", cv_path: str) -> bool:
    from stealth import human_delay
    p = Path(cv_path).resolve()
    if not p.exists():
        logger.warning("CV file not found: %s", cv_path)
        return False
    if p.suffix.lower() != ".pdf":
        logger.warning("CV file is not a PDF: %s", cv_path)
        return False
    for selector in [
        "input[type='file'][accept*='pdf']",
        "input[type='file']",
        "[data-testid='file-upload']",
    ]:
        try:
            file_input = page.locator(selector).first
            if await file_input.count() > 0:
                await file_input.set_input_files(str(p))
                await human_delay(500, 1000)
                return True
        except Exception:
            continue
    return False


# ── Blocker detection ─────────────────────────────────────────────────────────

_CAPTCHA_SELECTORS = [
    "iframe[src*='recaptcha']",
    "iframe[title*='challenge']",
    "[class*='captcha']",
    "#captcha",
]
_CAPTCHA_TEXT_PATTERNS = [
    r"(?i)verify you('re| are) human",
    r"(?i)i'?m not a robot",
    r"(?i)complete the (security check|captcha)",
]
_LOGIN_WALL_SELECTORS = [
    "input[type='password']",
    "form[action*='login']",
    "form[action*='signin']",
]
_LOGIN_WALL_TEXT_PATTERNS = [
    r"(?i)sign in to continue",
    r"(?i)log ?in to (view|continue|apply)",
    r"(?i)please log ?in",
]


async def _any_visible(page: "Page", selectors: list[str]) -> bool:
    for selector in selectors:
        try:
            if await page.locator(selector).first.is_visible(timeout=500):
                return True
        except Exception:
            continue
    return False


def _any_match(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


async def detect_blocker(page: "Page") -> Optional[dict]:
    """Classify a blocking condition on the current page, if any.

    Returns {"blocker_type": "captcha"|"login_wall", "description": "..."} or
    None. Captcha is checked first — a captcha overlay can sit on top of what
    would otherwise look like a login form, and misclassifying it as a login
    wall would send a human toward the wrong remedy.
    """
    try:
        body_text = (await page.inner_text("body"))[:4000]
    except Exception:
        body_text = ""

    if await _any_visible(page, _CAPTCHA_SELECTORS) or _any_match(body_text, _CAPTCHA_TEXT_PATTERNS):
        return {"blocker_type": "captcha", "description": f"Captcha challenge on {page.url}"}

    if await _any_visible(page, _LOGIN_WALL_SELECTORS) or _any_match(body_text, _LOGIN_WALL_TEXT_PATTERNS):
        return {"blocker_type": "login_wall", "description": f"Login wall on {page.url}"}

    return None


async def pause_for_input(page: "Page", slot_info: "SlotInfo", blocker: dict, relay) -> None:
    """Escalate a detected blocker to a human, per the spec's escalation sequence:
    switch to interactive mode, mark the slot 'awaiting input' for the dashboard,
    notify the user with a Take-over prompt, then block until they signal resume.
    On the way out, report what happened so the learning loop can persist it.
    """
    import session_manager as sm_module

    blocker_type = blocker["blocker_type"]
    description  = blocker["description"]
    logger.warning("Slot %d blocked (%s): %s", slot_info.slot_id, blocker_type, description)

    slot_info.action = f"Awaiting input — {description}"
    await sm_module.session_manager.mark_blocked(slot_info.slot_id, description)
    await sm_module.session_manager.ensure_interactive(slot_info.slot_id, relay)
    relay.push({
        "type": "browser_blocked",
        "slot_id": slot_info.slot_id,
        "blocker_type": blocker_type,
        "description": description,
    })

    await sm_module.session_manager.wait_for_resume(slot_info.slot_id)

    logger.info("Slot %d resumed by user — continuing on %s", slot_info.slot_id, page.url)
    slot_info.action = f"Resumed — continuing on {_guess_company(page.url)}"
    relay.push({
        "type": "browser_blocker_resolved",
        "agent_id": "maya",
        "site": urlparse(page.url).netloc,
        "blocker_type": blocker_type,
        "description": description,
        "resolution": "user took over in interactive mode and resumed manually",
        "timestamp": datetime.now().isoformat(),
    })


# ── LinkedIn Easy Apply ───────────────────────────────────────────────────────

async def _apply_linkedin_easy(page: "Page", profile: dict, cv_path: str) -> bool:
    from stealth import human_delay
    try:
        easy_btn = page.locator("button:has-text('Easy Apply'), .jobs-apply-button")
        if not await easy_btn.is_visible(timeout=3000):
            return False
        await easy_btn.click()
        await human_delay(1000, 2000)
        cv_attached = False
        for _ in range(10):
            await fill_form_fields(page, profile)
            if not cv_attached:
                attached = await attach_cv(page, cv_path)
                if attached:
                    cv_attached = True
            submit_btn = page.locator(
                "button:has-text('Submit application'), button:has-text('Review')"
            ).first
            next_btn = page.locator(
                "button:has-text('Next'), button:has-text('Continue'),"
                "button[aria-label='Continue to next step']"
            ).first
            if await submit_btn.is_visible(timeout=1000):
                await submit_btn.click()
                await human_delay(2000, 3000)
                return True
            elif await next_btn.is_visible(timeout=1000):
                await next_btn.click()
                await human_delay(800, 1500)
            else:
                break
        return False
    except Exception as exc:
        logger.warning("LinkedIn Easy Apply failed: %s", exc)
        return False


# ── Generic ATS ───────────────────────────────────────────────────────────────

async def _apply_generic_ats(page: "Page", profile: dict, cv_path: str) -> bool:
    from stealth import human_delay
    try:
        apply_btn = page.locator(
            "a:has-text('Apply'), button:has-text('Apply Now'),"
            "button:has-text('Apply for this job'),"
            "a:has-text('Apply Now'), a:has-text('Apply for this job')"
        ).first
        if await apply_btn.is_visible(timeout=3000):
            await apply_btn.click()
            await human_delay(1500, 2500)
        filled = await fill_form_fields(page, profile)
        await attach_cv(page, cv_path)
        submit = page.locator(
            "button[type='submit'], button:has-text('Submit'), input[type='submit']"
        ).first
        if await submit.is_visible(timeout=3000):
            await submit.click()
            await human_delay(2000, 3000)
            return True
        return filled > 0
    except Exception as exc:
        logger.warning("Generic ATS apply failed: %s", exc)
        return False


# ── Main apply entry point ────────────────────────────────────────────────────

async def apply_to_job(
    page: "Page",
    url: str,
    cv_path: str,
    slot_info: Optional["SlotInfo"] = None,
    tailor_cv: bool = False,
    relay=None,
) -> ApplyResult:
    try:
        profile = load_profile()
    except RuntimeError as exc:
        logger.error("Skipping %s — %s", url, exc)
        return ApplyResult(url=url, company=_guess_company(url), role="", status="skipped", error=str(exc))
    company = _guess_company(url)
    role = ""
    try:
        if slot_info:
            slot_info.url = url
            slot_info.action = "Fetching job description"
        jd = await fetch_job_description(page, url)

        if slot_info is not None and relay is not None:
            blocker = await detect_blocker(page)
            if blocker:
                await pause_for_input(page, slot_info, blocker, relay)
                # Use page.url (current post-resolution URL) not the original url,
                # so we don't navigate back into the same captcha/login wall.
                jd = await fetch_job_description(page, page.url)

        try:
            role = await page.title() or "Role"
        except Exception:
            role = "Role"
        if tailor_cv:
            from cv_compiler import tailor_and_compile
            cv_path = str(await tailor_and_compile(jd, company, role, slot_info=slot_info))
        if slot_info:
            slot_info.action = f"Applying to {company}"
        ok = await _apply_linkedin_easy(page, profile, cv_path)
        if not ok:
            ok = await _apply_generic_ats(page, profile, cv_path)
        status = "applied" if ok else "failed"
        return ApplyResult(url=url, company=company, role=role, status=status, cv_path=cv_path)
    except Exception as exc:
        err = str(exc)
        if "captcha" in err.lower() or "cloudflare" in err.lower():
            return ApplyResult(url=url, company=company, role=role, status="captcha", error=err)
        return ApplyResult(url=url, company=company, role=role, status="failed", error=err)


# ── Discovery modes ───────────────────────────────────────────────────────────

async def discover_jobs_linkedin(
    page: "Page", keywords: str, location: str = "Bangalore"
) -> list[str]:
    from stealth import scroll_to_read
    query = keywords.replace(" ", "%20")
    loc = location.replace(" ", "%20")
    url = f"https://www.linkedin.com/jobs/search/?keywords={query}&location={loc}&f_AL=true"
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await scroll_to_read(page)
    links = await page.locator("a.job-card-list__title, a.base-card__full-link").all()
    urls = []
    for link in links[:10]:
        href = await link.get_attribute("href")
        if href and "/jobs/" in href:
            urls.append(href.split("?")[0])
    return list(dict.fromkeys(urls))


async def discover_jobs_indeed(
    page: "Page", keywords: str, location: str = "Bangalore"
) -> list[str]:
    from stealth import scroll_to_read
    query = keywords.replace(" ", "+")
    loc = location.replace(" ", "+")
    url = f"https://in.indeed.com/jobs?q={query}&l={loc}"
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await scroll_to_read(page)
    links = await page.locator("a.jcs-JobTitle, h2.jobTitle a").all()
    urls = []
    for link in links[:10]:
        href = await link.get_attribute("href")
        if href:
            if not href.startswith("http"):
                href = "https://in.indeed.com" + href
            urls.append(href)
    return list(dict.fromkeys(urls))


async def _login_naukri(page: "Page") -> bool:
    """Log into Naukri using NAUKRI_EMAIL / NAUKRI_PASSWORD env vars, if set.

    Returns True if a login was attempted and appears to have succeeded, False if
    no credentials are configured or the login could not be confirmed. Discovery
    can proceed without login (listings are public), but applying to a job on
    Naukri requires an authenticated session.
    """
    from stealth import human_delay

    email = os.environ.get("NAUKRI_EMAIL")
    password = os.environ.get("NAUKRI_PASSWORD")
    if not email or not password:
        logger.info("NAUKRI_EMAIL/NAUKRI_PASSWORD not set — skipping Naukri login")
        return False
    try:
        already = page.locator("a[title='My Naukri'], a:has-text('My Naukri')")
        if await already.is_visible(timeout=2000):
            return True
    except Exception:
        pass
    try:
        await page.goto("https://www.naukri.com/nlogin/login", wait_until="domcontentloaded", timeout=30000)
        await page.fill("#usernameField", email)
        await page.fill("#passwordField", password)
        await human_delay(300, 700)
        await page.click("button[type='submit']")
        await human_delay(2000, 3000)
        logged_in = page.locator("a[title='My Naukri'], a:has-text('My Naukri')")
        return await logged_in.is_visible(timeout=5000)
    except Exception as exc:
        logger.warning("Naukri login failed: %s", exc)
        return False


async def discover_jobs_naukri(
    page: "Page", keywords: str, location: str = "Bangalore"
) -> list[str]:
    from stealth import scroll_to_read
    await _login_naukri(page)
    query = keywords.strip().lower().replace(" ", "-")
    loc = location.strip().lower().replace(" ", "-")
    url = f"https://www.naukri.com/{query}-jobs-in-{loc}"
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await scroll_to_read(page)
    links = await page.locator("a.title, a.title.ellipsis").all()
    urls = []
    for link in links[:10]:
        href = await link.get_attribute("href")
        if href and href.startswith("http"):
            urls.append(href.split("?")[0])
    return list(dict.fromkeys(urls))


async def discover_company_roles(
    page: "Page", company: str, target_roles: list[str]
) -> list[str]:
    from stealth import scroll_to_read
    query = f"{company}+careers+jobs"
    await page.goto(
        f"https://www.google.com/search?q={query}",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    await scroll_to_read(page)
    try:
        link = page.locator(f"a[href*='{company.lower()}']").first
        href = await link.get_attribute("href")
        if href and href.startswith("http"):
            await page.goto(href, wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass
    urls = []
    for role in target_roles:
        try:
            role_links = await page.locator("a").filter(has_text=role).all()
            for rl in role_links[:3]:
                href = await rl.get_attribute("href")
                if href:
                    if not href.startswith("http"):
                        parsed = urlparse(page.url)
                        href = f"{parsed.scheme}://{parsed.netloc}{href}"
                    urls.append(href)
        except Exception:
            continue
    return list(dict.fromkeys(urls))
