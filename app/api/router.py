"""
All REST API routes for Shadow Garden.
"""
import asyncio
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import JSONResponse, Response, FileResponse

from app import config
from app.agents import definitions as defs
from app.services import email as email_svc
from app.state import manager as state
from app.skills import skill_loader
from app.services.scheduler import (
    load_routines, save_routines, run_routine, get_routine_logs
)
from app.services.browser import navigate, take_screenshot, extract_text, click_element
from app.services.self_heal import load_approvals, apply_approval, deny_approval
from app.agents import tools as agent_tools
from app.services.telephony import (
    build_play_and_gather, build_say_and_gather, build_hangup, validate_twilio_request
)
from app.services import call_store
from app.agents.call_prep import match_utterance, cleanup_call_audio, quick_reply, _AUDIO_DIR

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/agents")
async def api_agents():
    agents = defs.all_agents()
    return {k: defs.public_agent_info(k, v) for k, v in agents.items()}


@router.get("/api/chat/{agent_id}/history")
async def api_chat_history(agent_id: str):
    return state.conversation_histories.get(agent_id, [])


@router.get("/api/storage")
async def api_storage():
    try:
        proc = await asyncio.create_subprocess_exec(
            "du", "-sb", str(config.WORK_DIR),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        used   = int(out.split()[0]) if out else 0
    except Exception:
        used = 0
    used_gb = used / 1024 ** 3
    return {
        "used_gb": round(used_gb, 2),
        "max_gb":  config.MAX_STORAGE,
        "percent": round(min(100, used_gb / config.MAX_STORAGE * 100), 1),
    }


@router.get("/api/projects")
async def api_projects():
    return state.load_projects()


@router.post("/api/projects")
async def api_new_project(body: dict):
    return state.save_project(body)


@router.post("/api/hire")
async def api_hire(body: dict):
    from app.agents.definitions import _worker_persona, AGENT_DEFS, custom_agents
    aid  = body.get("id", f"agent_{len(custom_agents) + 1}")

    # Prevent overwriting built-in agents
    if aid in AGENT_DEFS:
        return {"ok": False, "error": f"Agent id '{aid}' is reserved for a built-in agent."}

    role = body.get("role", "Specialist")
    custom_agents[aid] = {
        "name":        body.get("name", "Contractor"),
        "title":       body.get("title", role),
        "color":       body.get("color", "#94a3b8"),
        "avatar":      body.get("avatar", "CT"),
        "description": body.get("description", role),
        "persona":     _worker_persona(body.get("name", "Contractor"), role,
                                       body.get("stack", "general purpose"), "")(),
    }
    state.conversation_histories[aid] = []
    return {"ok": True, "id": aid}


@router.delete("/api/hire/{agent_id}")
async def api_fire(agent_id: str):
    from app.agents.definitions import AGENT_DEFS, custom_agents
    if agent_id in AGENT_DEFS:
        return {"ok": False, "error": "Cannot remove a built-in agent."}
    if agent_id not in custom_agents:
        return {"ok": False, "error": "Agent not found."}
    del custom_agents[agent_id]
    state.conversation_histories.pop(agent_id, None)
    return {"ok": True}


@router.post("/api/email")
async def api_email(body: dict):
    return await email_svc.send_mail(body.get("subject", "Shadow Garden"), body.get("body", ""), to=body.get("to"))


@router.get("/api/email/inbox")
async def api_email_inbox(max_emails: int = 5, folder: str = "INBOX", unread_only: bool = True):
    return await email_svc.read_emails(max_emails=max_emails, folder=folder, unread_only=unread_only)


@router.get("/api/email-tasks")
async def api_email_tasks():
    from app.services import email_poller
    return email_poller.list_tasks()


@router.get("/api/ceo-sessions")
async def api_ceo_sessions():
    """Group CEO conversation history into resumable sessions (30-min gap = new session)."""
    history = state.conversation_histories.get("ceo", [])
    if not history:
        return []

    SESSION_GAP = 1800  # 30 minutes
    sessions, current = [], []

    for msg in history:
        ts_str = msg.get("ts", "")
        try:
            ts = datetime.fromisoformat(ts_str).timestamp() if ts_str else 0
        except Exception:
            ts = 0

        if current:
            try:
                prev_ts = datetime.fromisoformat(current[-1].get("ts", "")).timestamp()
            except Exception:
                prev_ts = 0
            if ts and prev_ts and (ts - prev_ts) > SESSION_GAP:
                sessions.append(current)
                current = []
        current.append(msg)

    if current:
        sessions.append(current)

    result = []
    for sess in reversed(sessions[-5:]):
        user_msgs = [m for m in sess if m.get("role") == "user"]
        topic     = user_msgs[0]["content"][:80] if user_msgs else "(no topic)"
        last_user = user_msgs[-1]["content"][:120] if user_msgs else topic
        result.append({
            "topic":       topic,
            "started":     sess[0].get("ts", "")[:16].replace("T", " "),
            "last_active": sess[-1].get("ts", "")[:16].replace("T", " "),
            "msg_count":   len(sess),
            "resume_msg":  last_user,
        })
    return result


@router.post("/api/email-tasks/poll")
async def api_email_tasks_poll(request: Request):
    from app.services import email_poller
    email_graph = getattr(request.app.state, "email_graph", None)
    if email_graph is None:
        return JSONResponse({"ok": False, "error": "email_graph not ready"}, status_code=503)
    asyncio.create_task(email_poller.poll_once(email_graph))
    return {"ok": True, "message": "Poll triggered"}


@router.post("/api/rebuild")
async def api_rebuild():
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            res = await client.post("http://host.docker.internal:3030/api/rebuild", timeout=5.0)
            return res.json()
    except Exception as exc:
        return {"status": "error", "message": f"Failed to reach SRE Sidecar: {exc}"}


@router.get("/api/changelog")
async def api_get_changelog():
    return state.load_changelog()


@router.post("/api/changelog")
async def api_post_changelog(body: dict):
    files = body.get("files", [])
    if not isinstance(files, list):
        files = []
    entry = state.log_feature(
        feature=body.get("feature", "Unknown feature"),
        files=files,
        agent=body.get("agent", "worker"),
    )
    return {"ok": True, "entry": entry}


@router.get("/api/skills")
async def api_skills_list():
    return {
        "tools":   skill_loader.list_tools(),
        "learned": skill_loader.list_manifests(),
    }


@router.post("/api/skills/register")
async def api_skills_register(request: Request, body: dict):
    # Only agents running inside the container (localhost) may install skills
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        return JSONResponse({"ok": False, "error": "Skill registration is restricted to localhost"}, status_code=403)
    manifest   = body.get("manifest", {})
    skill_code = body.get("skill_code", "")
    test_code  = body.get("test_code", "")
    if not manifest.get("id"):
        return JSONResponse({"ok": False, "error": "manifest.id required"}, status_code=400)
    try:
        result = skill_loader.register_skill(manifest, skill_code, test_code)
        return {"ok": True, "manifest": result}
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=422)


@router.post("/api/skills/{skill_id}/rollback")
async def api_skills_rollback(skill_id: str):
    ok = skill_loader.rollback(skill_id)
    return {"ok": ok}


@router.delete("/api/skills/{skill_id}")
async def api_skills_delete(skill_id: str):
    import shutil
    skill_dir = skill_loader._dir / "learned" / skill_id
    if not skill_dir.exists():
        return JSONResponse({"ok": False, "error": "Skill not found"}, status_code=404)
    shutil.rmtree(str(skill_dir))
    skill_loader.load_all()
    return {"ok": True}


@router.get("/api/capabilities")
async def api_capabilities():
    def _mask(s: str) -> str:
        if not s:
            return ""
        if "@" in s:
            local, domain = s.split("@", 1)
            return local[:2] + "***@" + domain
        return s[:2] + "***"

    email_ok = all([config.SMTP_USER, config.SMTP_PASS, config.USER_EMAIL])
    return {
        "email_configured": email_ok,
        "smtp_user":        _mask(config.SMTP_USER),
        "user_email":       _mask(config.USER_EMAIL),
        "smtp_host":        config.SMTP_HOST,
        "smtp_port":        config.SMTP_PORT_NUM,
        "skills": [
            {"id": "code_exec",  "name": "Code Execution",   "desc": "Bash, Python, any shell command",           "active": True},
            {"id": "file_io",    "name": "File I/O",          "desc": "Read, Write, Edit files on disk",           "active": True},
            {"id": "web",        "name": "Web Search & Fetch","desc": "Search the web, fetch URLs",                "active": True},
            {"id": "delegation", "name": "Team Delegation",   "desc": "Dispatch tasks to backend/frontend/QA/devops","active": True},
            {"id": "projects",   "name": "Project Tracking",  "desc": "Create & track active projects",            "active": True},
            {"id": "voice",      "name": "Voice I/O",         "desc": "Speech-to-text input, TTS output",          "active": True},
            {"id": "email",      "name": "Email (Out/In)",    "desc": "Send notifications and read recent emails",  "active": email_ok},
            {"id": "sre",        "name": "Phoenix SRE",       "desc": "DevOps portal active on Port 3030",          "active": True},
        ],
    }


# ── Routines ───────────────────────────────────────────────────────────────────

@router.get("/api/routines")
async def api_routines_list():
    return load_routines()


@router.post("/api/routines")
async def api_routines_create(body: dict):
    import re
    required = {"id", "name", "agent", "schedule", "prompt"}
    missing  = required - set(body.keys())
    if missing:
        return JSONResponse({"ok": False, "error": f"Missing fields: {missing}"}, status_code=400)
    if not re.match(r'^[a-zA-Z0-9_-]+$', body["id"]):
        return JSONResponse({"ok": False, "error": "Invalid id format"}, status_code=400)
    routines = load_routines()
    if any(r["id"] == body["id"] for r in routines):
        return JSONResponse({"ok": False, "error": "Routine id already exists"}, status_code=409)
    routine = {
        "id":          body["id"],
        "name":        body["name"],
        "description": body.get("description", ""),
        "agent":       body["agent"],
        "schedule":    body["schedule"],
        "timezone":    body.get("timezone", "Asia/Kolkata"),
        "prompt":      body["prompt"],
        "enabled":     body.get("enabled", True),
        "last_run":    None,
        "last_status": None,
        "run_count":   0,
    }
    routines.append(routine)
    save_routines(routines)
    return {"ok": True, "routine": routine}


@router.put("/api/routines/{routine_id}")
async def api_routines_update(routine_id: str, body: dict):
    routines = load_routines()
    for r in routines:
        if r["id"] == routine_id:
            updatable = {"name", "description", "schedule", "timezone", "prompt", "enabled"}
            for k in updatable:
                if k in body:
                    r[k] = body[k]
            save_routines(routines)
            return {"ok": True, "routine": r}
    return JSONResponse({"ok": False, "error": "Routine not found"}, status_code=404)


@router.delete("/api/routines/{routine_id}")
async def api_routines_delete(routine_id: str):
    routines = load_routines()
    updated  = [r for r in routines if r["id"] != routine_id]
    if len(updated) == len(routines):
        return JSONResponse({"ok": False, "error": "Routine not found"}, status_code=404)
    save_routines(updated)
    return {"ok": True}


@router.post("/api/routines/{routine_id}/run")
async def api_routines_run(routine_id: str):
    routines = load_routines()
    routine  = next((r for r in routines if r["id"] == routine_id), None)
    if not routine:
        return JSONResponse({"ok": False, "error": "Routine not found"}, status_code=404)
    asyncio.create_task(run_routine(routine))
    return {"ok": True, "message": f"Routine '{routine_id}' triggered"}


@router.get("/api/routines/{routine_id}/logs")
async def api_routines_logs(routine_id: str, limit: int = 10):
    return get_routine_logs(routine_id, limit)


# ── Design Preview ─────────────────────────────────────────────────────────────

@router.post("/api/design/preview")
async def api_design_preview(request: Request, body: dict):
    """Write HTML directly to the design preview (localhost-only)."""
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        return JSONResponse({"ok": False, "error": "Restricted to localhost"}, status_code=403)
    html = body.get("html", "")
    if not html.strip():
        return JSONResponse({"ok": False, "error": "html field is required"}, status_code=400)
    from app.services.browser import write_preview
    from app.api.websocket import broadcast_event
    result = write_preview(html)
    asyncio.create_task(broadcast_event({"type": "design_preview_updated", "message": result}))
    return {"ok": True, "message": result}


# ── Browser ────────────────────────────────────────────────────────────────────

@router.post("/api/browser/navigate")
async def api_browser_navigate(body: dict):
    url = body.get("url", "").strip()
    if not url:
        return JSONResponse({"ok": False, "error": "url required"}, status_code=400)
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    result = await navigate(url)
    if "error" in result:
        return JSONResponse({"ok": False, **result}, status_code=422)
    return {"ok": True, **result}


@router.get("/api/browser/screenshot")
async def api_browser_screenshot_get():
    from pathlib import Path
    from fastapi.responses import FileResponse
    screenshot = Path("/app/app/static/previews/browser_screenshot.png")
    if not screenshot.exists():
        return JSONResponse({"ok": False, "error": "No screenshot yet"}, status_code=404)
    return FileResponse(str(screenshot), media_type="image/png")


@router.post("/api/browser/screenshot")
async def api_browser_screenshot_post(body: dict):
    url    = body.get("url", "").strip() or None
    result = await take_screenshot(url)
    if "error" in result:
        return JSONResponse({"ok": False, **result}, status_code=422)
    return {"ok": True, **result}


@router.post("/api/browser/extract")
async def api_browser_extract(body: dict):
    url      = body.get("url", "").strip()
    selector = body.get("selector", "body").strip()
    if not url:
        return JSONResponse({"ok": False, "error": "url required"}, status_code=400)
    text = await extract_text(url, selector)
    if text.startswith("[extract_text error:"):
        return JSONResponse({"ok": False, "error": text}, status_code=422)
    return {"ok": True, "text": text}


@router.post("/api/browser/click")
async def api_browser_click(body: dict):
    url      = body.get("url", "").strip()
    selector = body.get("selector", "").strip()
    if not url or not selector:
        return JSONResponse({"ok": False, "error": "url and selector required"}, status_code=400)
    result = await click_element(url, selector)
    if "error" in result:
        return JSONResponse({"ok": False, **result}, status_code=422)
    return {"ok": True, **result}


# ── Wildcard Browser-svc Proxy ────────────────────────────────────────────────
# Dynamically proxy all requests under /api/browser-svc/* to the browser-svc.

@router.api_route("/api/browser-svc/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def api_browser_svc_proxy(path: str, request: Request):
    import httpx
    from fastapi.responses import Response
    method = request.method
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "authorization")}
    content = await request.body()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.request(
                method,
                f"{config.BROWSER_SVC_URL}/{path}",
                headers=headers,
                content=content,
                params=request.query_params,
            )
            try:
                data = r.json()
                return JSONResponse(data, status_code=r.status_code)
            except Exception:
                return Response(content=r.content, status_code=r.status_code, media_type=r.headers.get("content-type"))
    except Exception as exc:
        return JSONResponse({"ok": False, "error": f"browser-svc unreachable: {exc}"}, status_code=502)



# ── Conversation compact ───────────────────────────────────────────────────────

@router.post("/api/compact")
async def api_compact(body: dict = None):
    """Archive old conversation messages to memory and trim history.

    body: {"agent": "ceo"}  — compact one agent
    body: {}                 — compact all agents
    """
    from app.agents.runner import _auto_compact_history

    agent_id = (body or {}).get("agent")
    targets  = [agent_id] if agent_id else list(state.conversation_histories.keys())

    compacted = []
    for aid in targets:
        if _auto_compact_history(aid):
            compacted.append(aid)

    return {"ok": True, "compacted": compacted, "count": len(compacted)}


# ── Approvals ──────────────────────────────────────────────────────────────────

@router.get("/api/approvals")
async def api_approvals_list():
    return load_approvals()


@router.post("/api/approvals/{approval_id}/apply")
async def api_approvals_apply(approval_id: str):
    from app.api.websocket import broadcast_event
    ok, msg = apply_approval(approval_id.upper())
    if ok:
        asyncio.create_task(broadcast_event({
            "type":        "approval_applied",
            "approval_id": approval_id.upper(),
            "message":     msg,
        }))
    return {"ok": ok, "message": msg}


@router.post("/api/approvals/{approval_id}/deny")
async def api_approvals_deny(approval_id: str):
    from app.api.websocket import broadcast_event
    ok, msg = deny_approval(approval_id.upper())
    if ok:
        asyncio.create_task(broadcast_event({
            "type":        "approval_denied",
            "approval_id": approval_id.upper(),
            "message":     msg,
        }))
    return {"ok": ok, "message": msg}


@router.get("/api/filler")
async def get_filler(context: str = ""):
    """Return a pre-built Bark filler clip based on context keywords."""
    from app.services import bark_client
    audio = await bark_client.get_filler(context)
    return {"audio": audio}


# ── Health ─────────────────────────────────────────────────────────────────────

async def _probe_service(url: str) -> bool:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(url)
            return r.status_code == 200
    except Exception:
        return False


@router.get("/api/health")
async def api_health():
    bark_ok, browser_ok = await asyncio.gather(
        _probe_service(f"{config.BARK_SVC_URL}/health"),
        _probe_service(f"{config.BROWSER_SVC_URL}/health"),
    )
    return {
        "app":     True,
        "bark":    bark_ok,
        "browser": browser_ok,
        "email":   all([config.SMTP_USER, config.SMTP_PASS, config.USER_EMAIL]),
    }


# ── Outbound call — user-initiated ─────────────────────────────────────────────

@router.post("/api/calls/outbound")
async def api_call_outbound(body: dict, background_tasks: BackgroundTasks):
    number   = body.get("number", "")
    goal     = body.get("goal", "")
    language = body.get("language", "en")
    if not number or not goal:
        return JSONResponse({"error": "number and goal required"}, status_code=400)
    result = await agent_tools.run_outbound_call(number=number, goal=goal, language=language)
    return result


# ── Audio serving — Twilio fetches pre-rendered WAV files ──────────────────────

@router.get("/api/calls/audio/{call_id}/{idx}")
async def api_call_audio(call_id: str, idx: int):
    wav_path = _AUDIO_DIR / call_id / f"{idx}.wav"
    if not wav_path.exists():
        return JSONResponse({"error": "audio not found"}, status_code=404)
    return FileResponse(str(wav_path), media_type="audio/wav")


# ── Outbound gather webhook — Twilio posts STT result here ─────────────────────

@router.post("/api/calls/gather")
async def api_calls_gather(request: Request, background_tasks: BackgroundTasks):
    form    = await request.form()
    params  = dict(form)
    sig     = request.headers.get("X-Twilio-Signature", "")
    url     = str(request.url)
    call_id = str(form.get("call_id", ""))
    turn    = int(form.get("turn", 0))
    speech  = str(form.get("SpeechResult", "")).strip()

    if config.TWILIO_AUTH_TOKEN and not validate_twilio_request(url, params, sig):
        return Response("Forbidden", status_code=403)

    sess = call_store.get_session(call_id)
    if not sess:
        return Response(build_hangup("Session expired. Goodbye."), media_type="application/xml")

    gather_url = f"{config.BASE_URL}/api/calls/gather?call_id={call_id}&turn={turn + 1}"

    # turn=0: play opening (idx=0 in script)
    if turn == 0 and sess.script:
        entry = sess.script[0]
        entry.used = True
        sess.status = "connected"
        call_store.add_turn(call_id, "nexus", entry.answer)
        audio_url = f"{config.BASE_URL}/api/calls/audio/{call_id}/0"
        return Response(
            build_play_and_gather(audio_url=audio_url, gather_action=gather_url, language=sess.language),
            media_type="application/xml",
        )

    # Subsequent turns: match speech to script
    if speech:
        call_store.add_turn(call_id, "them", speech)

        # Check if it's a goodbye signal
        goodbye_words = {"bye", "goodbye", "thank you", "that's all", "no thanks", "thanks bye"}
        if any(w in speech.lower() for w in goodbye_words):
            closing = next((e for e in sess.script if e.idx == len(sess.script) - 1), None)
            closing_text = closing.answer if closing else "Thank you. Goodbye!"
            call_store.add_turn(call_id, "nexus", closing_text)
            background_tasks.add_task(
                call_store.end_session, call_id, "success",
                f"Call completed. Last exchange: {speech[:80]}"
            )
            background_tasks.add_task(cleanup_call_audio, call_id)
            return Response(build_hangup(closing_text), media_type="application/xml")

        matched = match_utterance(speech, sess.script)
        if matched and matched.audio_path and Path(matched.audio_path).exists():
            matched.used = True
            call_store.add_turn(call_id, "nexus", matched.answer)
            audio_url = f"{config.BASE_URL}/api/calls/audio/{call_id}/{matched.idx}"
            return Response(
                build_play_and_gather(audio_url=audio_url, gather_action=gather_url, language=sess.language),
                media_type="application/xml",
            )

        # No match — Gemini-flash fast path (reconciliation: quick_reply, not a static line)
        fallback = await quick_reply(sess.goal, sess.transcript, sess.language)
        call_store.add_turn(call_id, "nexus", fallback)
        return Response(
            build_say_and_gather(text=fallback, gather_action=gather_url, language=sess.language),
            media_type="application/xml",
        )

    # No speech detected — re-prompt once
    prompt = "Sorry, I didn't catch that. Could you please say that again?"
    return Response(
        build_say_and_gather(text=prompt, gather_action=gather_url, language=sess.language),
        media_type="application/xml",
    )


# ── SPA fallback (must be last) ────────────────────────────────────────────────

from fastapi.responses import FileResponse as _FileResponse
from pathlib import Path as _Path

_STATIC_DIR = _Path(__file__).parent.parent / "static"


@router.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    """Catch-all: serve index.html for any unmatched GET (SPA client-side routing)."""
    del full_path  # unused — route is catch-all
    index = _STATIC_DIR / "index.html"
    return _FileResponse(str(index))
