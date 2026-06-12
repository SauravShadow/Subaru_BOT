# Browser Agent Maya — Design Spec

**Date:** 2026-06-06
**Status:** Approved

## Overview

Add Maya, a 5th worker agent to NEXUS, specializing in browser automation. Maya can search for jobs, tailor CVs via Overleaf, and apply to job boards and company career pages — all observable in real time via a live Browser Board tab in the NEXUS dashboard.

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│              NEXUS app container (port 3030)     │
│                                                  │
│  FastAPI + WebSocket server                      │
│  CEO Agent (Alexandra) + 4 existing workers      │
│  MayaAgent stub → HTTP calls to browser-svc      │
│  WebSocket relay: browser-svc frames → frontend  │
└────────────────┬────────────────────────────────┘
                 │ internal Docker network
                 │ HTTP REST + WebSocket
┌────────────────▼────────────────────────────────┐
│              browser-svc container               │
│                                                  │
│  FastAPI service                                 │
│  Playwright + Chromium (up to 5 instances)       │
│  Session manager (slots 0–4)                     │
│  CDP screencast → frames pushed to NEXUS         │
│  Job workflows, Overleaf CV pipeline             │
└─────────────────────────────────────────────────┘
```

- `browser-svc` is a new Docker service added to `docker-compose.yml`
- NEXUS app contains a `MayaAgent` class that delegates tasks to `browser-svc` via internal HTTP
- CEO delegates using `[DELEGATE:browser]` — same pattern as existing workers
- `browser-svc` connects back to NEXUS via WebSocket to push CDP screencast frames
- Frontend gets a new **Browser Board** tab

---

## Session Management

Up to 5 named browser slots. Each is an independent Playwright browser context with its own cookies, storage, and CDP session.

| Slot | Purpose |
|------|---------|
| 0 | Reserved for Overleaf (CV tailoring + PDF export) |
| 1–4 | Job application instances |

- Sessions are created on-demand and reused (persistent login state across tasks)
- A slot is either `busy` or `idle`
- If all 4 application slots are busy, new jobs queue until one frees
- Queue is displayed in the Browser Board UI

---

## Live Streaming (CDP Screencast)

When a session starts, `browser-svc` calls `Page.startScreencast(format=jpeg, quality=60, maxWidth=1280)` on that slot's CDP session. Chrome pushes frames as events — no polling.

**Frame pipeline:**
1. CDP pushes JPEG frame to browser-svc
2. browser-svc emits over WebSocket to NEXUS:
   ```json
   {
     "type": "browser_frame",
     "slot": 1,
     "frame": "<base64 jpeg>",
     "url": "https://linkedin.com/jobs/apply/...",
     "action": "Filling Name field"
   }
   ```
3. NEXUS WebSocket server broadcasts to Browser Board clients

**Effective frame rate:** ~10fps (CDP event-driven, not polled).

---

## Browser Board UI

New tab in NEXUS dashboard. 2×3 grid — 5 live browser tiles + 1 queue/log tile.

```
┌──────────────┬──────────────┬──────────────┐
│  Overleaf    │  LinkedIn    │  Indeed      │
│  [live view] │  [live view] │  [live view] │
│  ● Editing   │  ● Applying  │  ● Searching │
├──────────────┼──────────────┼──────────────┤
│  Naukri      │  Slot 4      │  Queue / Log │
│  [live view] │  [idle]      │  3 pending   │
└──────────────┴──────────────┴──────────────┘
```

Each tile shows:
- Live JPEG stream (updated on each incoming frame)
- Current URL
- Current action label
- Slot status badge (busy / idle / error)

**Profile button** — opens an editable form for `browser_profile.json` fields. Changes take effect on the next application.

---

## Applicant Profile Config

Stored as `browser-svc/browser_profile.json`, volume-mounted from host (editable directly or via Browser Board UI).

```json
{
  "name": "Saurav Subaru",
  "email": "sauravsubaru@gmail.com",
  "phone": "",
  "linkedin": "",
  "experience_years": 5,
  "notice_period": "immediate",
  "target_roles": ["Backend Engineer", "Python Developer", "ML Engineer"],
  "target_companies": ["Stripe", "Razorpay", "CRED"],
  "skills": ["Python", "FastAPI", "ML"],
  "location_preference": "Bangalore / Remote"
}
```

Maya reads this fresh before each application — no restart needed after edits.

---

## Job Application Workflow

### Two Modes

**Discovery mode**
CEO: `[DELEGATE:browser] find Python backend jobs in Bangalore on LinkedIn and apply`
1. Slot opens job board, searches with given keywords
2. Scrapes matching job URLs and job descriptions
3. Queues each as an individual apply task

**Targeted mode**
CEO: `[DELEGATE:browser] apply to https://linkedin.com/jobs/view/12345`
1. Skips discovery, goes straight to apply pipeline

**Direct company mode**
CEO: `[DELEGATE:browser] apply to Stripe careers for backend roles`
1. Maya navigates to company careers page
2. Searches for matching roles based on `target_roles` in profile
3. Applies directly on company ATS

**Profile-matched discovery**
CEO: `[DELEGATE:browser] find relevant companies for my profile and apply`
1. Uses `target_companies` + `skills` + `target_roles` from profile
2. Visits each company's careers page, finds matching open roles, applies

### Apply Pipeline (per job)

```
1. Fetch job description from listing page
        ↓
2. Send JD + CV LaTeX source to Claude API
   → returns tailored LaTeX diff + injected keywords list
        ↓
3. Slot 0 (Overleaf):
   - Log in (session cached after first run)
   - Apply LaTeX edits to source in editor
   - Compile → wait for green tick (timeout: 60s)
   - Download PDF
   - Save as cv_<company>_<role>_<date>.pdf
        ↓
   Fallback: if compile fails or times out → use cv_default.pdf
        ↓
4. Application slot:
   - Navigate to job URL
   - Detect form type (Easy Apply / external ATS / email)
   - Fill all fields using browser_profile.json values
   - Attach PDF
   - Submit
        ↓
5. Log result: applied / failed / captcha-blocked / skipped
```

### Supported Job Sources

- LinkedIn Easy Apply
- Indeed
- Naukri
- Internshala
- Glassdoor
- Direct company career pages (generic ATS: Workday, Greenhouse, Lever, Taleo, custom)

---

## CV Enhancement Pipeline

**Overleaf credentials** stored in `.env`:
```
OVERLEAF_EMAIL=...
OVERLEAF_PASSWORD=...
OVERLEAF_PROJECT_URL=https://www.overleaf.com/project/...
```

**Claude prompt** (called before Overleaf editing):
- Input: job description text + current LaTeX CV source
- Output: changed LaTeX blocks + list of injected keywords
- Model: claude-sonnet-4-6 (existing NEXUS Claude instance)

**Saved exports:** All tailored CVs kept at `browser-svc/cv_exports/`. Browser Board log shows each: company, role, keywords injected, date. Past versions downloadable from UI.

**Default CV fallback:** `browser-svc/cv_default.pdf` — provided by user upfront, used when Overleaf pipeline fails.

---

## Bot Detection Avoidance

Best-effort stealth — no proxy rotation or captcha solving.

| Technique | Implementation |
|-----------|---------------|
| Stealth patch | `playwright-stealth` — removes `navigator.webdriver`, Chrome runtime leaks, plugin arrays |
| Randomized timing | 800ms–2500ms between keystrokes, 300ms–1200ms between clicks |
| Mouse simulation | Curved paths to click targets (bezier), not straight teleports |
| User-agent rotation | Current Chrome version on Windows/Mac, rotated per session |
| Viewport randomization | 1280–1440px width, slight height variation per session |
| Scroll behavior | Pages scrolled before interaction to mimic reading |

**Expected coverage:** LinkedIn Easy Apply, Indeed, Naukri, Internshala, Glassdoor, most Greenhouse/Lever forms.

**Known limits:** May be blocked by Cloudflare-protected Workday instances. Captcha-blocked attempts are logged and skipped — not retried.

---

## CEO Delegation Examples

```
[DELEGATE:browser] apply to https://linkedin.com/jobs/view/12345
[DELEGATE:browser] find and apply to Python backend jobs in Bangalore on LinkedIn
[DELEGATE:browser] apply to Stripe careers page for backend roles
[DELEGATE:browser] find relevant companies for my profile and apply
[DELEGATE:browser] apply to Razorpay, CRED, and any FastAPI roles on Indeed
```

---

## Maya's Responses to CEO

- Progress: `"Applied to Stripe (Backend Engineer) — CV tailored (8 keywords injected), submitted via Greenhouse"`
- Failure: `"Workday on Infosys blocked after captcha — skipped, used default CV on fallback attempt"`
- Summary: `"Session complete: 7 applied, 1 skipped (captcha), 2 queued"`

---

## New Files / Changes

| Path | Description |
|------|-------------|
| `browser-svc/` | New Docker service directory |
| `browser-svc/main.py` | FastAPI app — session manager, job workflow endpoints |
| `browser-svc/session_manager.py` | Slot lifecycle, CDP screencast, Playwright contexts |
| `browser-svc/job_workflow.py` | Discovery, targeted, direct-company apply pipelines |
| `browser-svc/overleaf_pipeline.py` | Overleaf login, LaTeX edit, compile, PDF export |
| `browser-svc/cv_enhancer.py` | Claude API call for CV tailoring |
| `browser-svc/stealth.py` | Playwright stealth setup, human-timing helpers |
| `browser-svc/browser_profile.json` | Applicant profile config |
| `browser-svc/cv_default.pdf` | Fallback CV (provided by user) |
| `browser-svc/cv_exports/` | Tailored CV versions |
| `browser-svc/Dockerfile` | Python + Playwright + Chromium image |
| `browser-svc/requirements.txt` | Dependencies |
| `app/agents/maya.py` | MayaAgent stub in NEXUS app |
| `app/agents/tools.py` | Add `[DELEGATE:browser]` tag parsing |
| `app/web_cli.py` | Add Browser Board WebSocket relay, Browser Board tab |
| `docker-compose.yml` | Add browser-svc service + internal network |
