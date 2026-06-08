# Job Application — Info Checklist

What the browser-svc form-filler needs, grouped by what it already handles vs. what
commonly shows up on job sites that it doesn't yet (and may need manual input for).

## 1. Site access (login/session)

The agent currently has **no stored credentials** for job sites — it relies on whatever
browser session/cookies already exist in the persistent context. To reliably search and
apply on these, you'd need to either log in manually once per site (session gets reused),
or store credentials for the agent to log in itself:

| Site      | What's needed                          | Status                    |
|-----------|----------------------------------------|---------------------------|
| LinkedIn  | `LINKEDIN_EMAIL` / `LINKEDIN_PASSWORD` in `.env` (or persisted session) | not yet configured |
| Naukri    | `NAUKRI_EMAIL` / `NAUKRI_PASSWORD` in `.env`     | configured (sauravkr031@gmail.com) |
| Indeed    | `INDEED_EMAIL` / `INDEED_PASSWORD` in `.env` (or persisted session) | not yet configured |
| Company sites (Greenhouse/Lever/etc.) | usually no login — direct apply forms | n/a |

Credentials live in `.env` (git-ignored) — never in this doc or any tracked file.
Naukri creds are now there; add `LINKEDIN_EMAIL`/`LINKEDIN_PASSWORD` and
`INDEED_EMAIL`/`INDEED_PASSWORD` the same way if you want the agent to log in itself
(login flows for these aren't wired up in code yet — currently it relies on an
already-authenticated session).

## 2. Fields the agent already auto-fills (from `browser_profile.json`)

`job_workflow.py` matches form labels against these patterns and fills from your profile:

| Form field (matched by label/name/placeholder) | Source in profile        |
|-------------------------------------------------|--------------------------|
| First / last / full name                        | `name`                   |
| Email                                            | `email`                  |
| Phone / mobile / contact                        | `phone`                  |
| LinkedIn                                         | `linkedin`               |
| Years of experience                              | `experience_years`       |
| Notice period / availability                     | `notice_period`          |
| Location / city                                  | `location_preference`    |
| Resume/CV upload (file input)                    | `cv_default.pdf` (or a CV tailored to the job description and compiled locally from `cv_template.tex` via Tectonic — see `cv_compiler.py`) |

These are the fields that are safe to leave to the agent right now.

## 3. Fields commonly asked that the agent does NOT yet handle

Worth documenting so you know what might require manual completion or a future profile
field + pattern addition in `_FIELD_PATTERNS` (`job_workflow.py`):

- **Work authorization / visa status** ("Are you authorized to work in India") -> Yes
- **Willingness to relocate** -> yes if the company is in Bangalore
- **Expected / current salary (CTC)** -> Current - 15 lpa and expected 25 lpa
- **Earliest start date** (distinct from notice period in some forms) -> 45 days from the current data
- **Cover letter** (free-text or file upload) 
- **Portfolio / GitHub / personal website URL** (you have these in your CV — `Portfolio`, `LeetCode`, `SauravShadow`/GitHub — but they're not in `browser_profile.json` yet) -> INclude it
- **How did you hear about us?** (dropdown — usually skippable/optional) -> Linkedin
- **EEO / diversity questions** (gender, race/ethnicity, veteran status, disability — almost always optional in India-based forms, more common on US company sites) - Male, Asiam, Non-veteran, no disability
- **References** (name/email/phone of past managers — rarely required upfront)
- **Highest education / degree / graduation year** (you have this in your CV: M.Tech IISc 2023, B.Tech NIT Jamshedpur)
- **Current company / current title** -> R&D Engineer 1, Keysight Technologies
- **Why do you want to work here?** / motivation free-text questions (company-specific, hard to template)

## 4. Suggested next additions to `browser_profile.json`

If you want broader auto-coverage, the highest-value additions (all derivable from your
CV, no guesswork) would be: `github`/`portfolio` URL, `current_company`, `current_title`,
`education` (degree + institution + year), and `work_authorization` (e.g. "Indian citizen,
no visa required"). Salary expectation and relocation preference are judgment calls only
you can make — happy to add them whenever you decide on values.
