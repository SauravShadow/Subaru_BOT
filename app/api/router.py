"""
All REST API routes for Shadow Garden.
"""
import asyncio
import asyncio as _asyncio
import logging
import re as _re
import time
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
from app.services import telephony
from app.services import call_store
from app.services.call_metrics import TurnTimer
from app.agents.call_prep import cleanup_call_audio, quick_reply, _AUDIO_DIR

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
    voice    = body.get("voice", config.BARK_SPEAKER)
    if not number or not goal:
        return JSONResponse({"error": "number and goal required"}, status_code=400)
    result = await agent_tools.run_outbound_call(
        number=number, goal=goal, language=language, voice=voice
    )
    return result


# ── Audio serving — Telnyx fetches pre-rendered WAV files ──────────────────────

@router.get("/api/calls/audio/{call_id}/{idx}")
async def api_call_audio(call_id: str, idx: int):
    wav_path = _AUDIO_DIR / call_id / f"{idx}.wav"
    if not wav_path.exists():
        return JSONResponse({"error": "audio not found"}, status_code=404)
    return FileResponse(str(wav_path), media_type="audio/wav")


# ── Live-call helpers ──────────────────────────────────────────────────────────

_GOODBYE_WORDS = {"bye", "goodbye", "thank you", "that's all", "no thanks", "thanks bye"}

_SILENCE_MS = 700  # interim unchanged this long => end of turn


def _normalize(text: str) -> str:
    cleaned = _re.sub(r"[^a-z0-9 ]", "", (text or "").lower())
    return _re.sub(r" +", " ", cleaned).strip()


def _silence_should_fire(sess, now: float) -> bool:
    txt = (sess.last_interim_text or "").strip()
    if not txt:
        return False
    if _normalize(txt) == _normalize(sess.responded_text):
        return False
    return (now - sess.last_interim_at) * 1000 >= _SILENCE_MS


async def _live_reply(call_id: str, speech: str, ssml: bool = False) -> str:
    """Generate a live, contextual reply (LLM). Answers whatever the caller said and
    advances the goal; the call script (if any) is passed as guidance, not canned text."""
    sess = call_store.get_session(call_id)
    goal       = sess.goal if sess else "this call"
    language   = sess.language if sess else "en"
    transcript = sess.transcript if sess else []
    points     = [e.answer for e in sess.script] if sess and sess.script else None
    return await quick_reply(goal, transcript, language, talking_points=points, ssml=ssml)


async def _speculate(call_id: str, text: str) -> None:
    try:
        reply = await _live_reply(call_id, text, ssml=True)
    except Exception:
        return
    sess = call_store.get_session(call_id)
    if sess and sess.speculative_key == _normalize(text):
        sess.speculative_text = reply


def _audio_url(call_id: str, idx: int) -> str:
    return f"{config.BASE_URL}/api/calls/audio/{call_id}/{idx}"


async def _silence_watch(call_id: str, ccid: str) -> None:
    try:
        await _asyncio.sleep(_SILENCE_MS / 1000)
    except _asyncio.CancelledError:
        return
    sess = call_store.get_session(call_id)
    if sess and _silence_should_fire(sess, time.monotonic()):
        await _finalize_turn(call_id, ccid, sess.last_interim_text)


def _arm_silence_timer(call_id: str, ccid: str) -> None:
    sess = call_store.get_session(call_id)
    if not sess:
        return
    if sess.silence_task is not None:
        sess.silence_task.cancel()
    sess.silence_task = _asyncio.create_task(_silence_watch(call_id, ccid))


async def _finalize_turn(call_id: str, ccid: str, speech: str) -> None:
    sess = call_store.get_session(call_id)
    if not sess:
        return
    speech = (speech or "").strip()
    if not speech or _normalize(speech) == _normalize(sess.responded_text):
        return
    sess.responded_text = speech
    sess._backchanneled = False
    if sess.is_speaking:
        sess.pending_caller_text = speech    # handle when call.speak.ended fires
        return
    if sess.silence_task is not None:
        sess.silence_task.cancel()
        sess.silence_task = None
    sess.turn = TurnTimer()
    sess.turn.mark("last_interim", at=sess.last_interim_at or None)
    sess.turn.mark("final")
    call_store.add_turn(call_id, "them", speech)
    await _respond_to_turn(call_id, ccid, speech)


async def _respond_to_turn(call_id: str, ccid: str, speech: str) -> None:
    sess = call_store.get_session(call_id)
    if not sess:
        return
    if sess.turn is None:          # normally set by _finalize_turn; guard direct calls
        sess.turn = TurnTimer()
        sess.turn.mark("final")
    lang = sess.language
    if any(w in speech.lower() for w in _GOODBYE_WORDS):
        closing_text = ("Thank you. Goodbye!" if sess.direction == "outbound"
                        else "Thank you for calling. Have a great day! Goodbye.")
        call_store.add_turn(call_id, "nexus", closing_text)
        telephony.speak_text(ccid, closing_text, language=lang, call_id=call_id)
        telephony.hangup_call(ccid)
        return
    if sess.speculative_key and sess.speculative_key == _normalize(speech) and sess.speculative_text:
        reply = sess.speculative_text
        sess.speculative_key = sess.speculative_text = ""
        sess.turn.mark("llm_done")
        call_store.add_turn(call_id, "nexus", reply)
        from app.agents.call_prep import sanitize_ssml
        payload, ptype = sanitize_ssml(reply)
        telephony.speak_text(ccid, payload, language=lang, call_id=call_id, payload_type=ptype)
        sess.turn.mark("speak")
        logger.info("[call %s] %s (speculative hit)", call_id, sess.turn.summary_line())
        return
    from app.agents.call_prep import pick_filler, sanitize_ssml
    reply_task = _asyncio.create_task(_live_reply(call_id, speech, ssml=True))
    done, _pending = await _asyncio.wait({reply_task}, timeout=1.0)
    if reply_task not in done:
        filler = pick_filler()
        call_store.add_turn(call_id, "nexus", filler)
        telephony.speak_text(ccid, filler, language=lang, call_id=call_id)
    reply = await reply_task
    sess.turn.mark("llm_done")
    call_store.add_turn(call_id, "nexus", reply)
    payload, ptype = sanitize_ssml(reply)
    telephony.speak_text(ccid, payload, language=lang, call_id=call_id, payload_type=ptype)
    sess.turn.mark("speak")
    logger.info("[call %s] %s", call_id, sess.turn.summary_line())


# ── Telnyx Call Control webhook — single event dispatcher ───────────────────────

@router.post("/api/calls/webhook")
async def api_calls_webhook(request: Request, background_tasks: BackgroundTasks):
    body = (await request.body()).decode()

    try:
        event = telephony.verify_webhook(body, dict(request.headers))
    except Exception as exc:
        logger.warning("Telnyx webhook verification failed: %s", exc)
        return Response("Forbidden", status_code=403)

    data       = event.data
    etype      = data.event_type
    payload    = data.payload
    ccid       = payload.call_control_id
    state_id   = telephony.decode_client_state(getattr(payload, "client_state", ""))
    direction  = getattr(payload, "direction", "")
    is_inbound = direction in ("incoming", "inbound")

    # Resolve our internal call_id: client_state → ccid map → (inbound) ccid itself
    call_id = state_id or call_store.resolve_call_id(ccid) or (ccid if is_inbound else "")

    # Issuing Call Control commands can fail (e.g. a transient Telnyx error). Never
    # let that bubble to a 500 — Telnyx retries non-2xx webhooks, which re-triggers
    # the whole handler (e.g. re-playing the opening). Always ack with 200.
    try:
        if etype == "call.initiated":
            if is_inbound:
                caller = getattr(payload, "from_", "") or "unknown"
                call_store.create_session(
                    call_id=ccid, direction="inbound", number=caller,
                    goal="inbound call", language="en", speaker=config.BARK_SPEAKER,
                )
                call_store.bind_call_control_id(ccid, ccid)
                telephony.answer_call(ccid, call_id=ccid)
            return Response(status_code=200)

        if etype == "call.answered":
            sess = call_store.get_session(call_id)
            if sess and sess.direction == "outbound" and sess.script:
                entry = sess.script[0]
                entry.used = True
                sess.status = "connected"
                call_store.add_turn(call_id, "nexus", entry.answer)
                telephony.speak_text(ccid, entry.answer, language=sess.language, call_id=call_id)
            elif sess:  # inbound
                greeting = "Hi, this is NEXUS, your AI assistant. How can I help you today?"
                call_store.add_turn(call_id, "nexus", greeting)
                telephony.speak_text(ccid, greeting, language=sess.language, call_id=call_id)
            telephony.start_transcription(ccid, language=(sess.language if sess else "en"))
            return Response(status_code=200)

        if etype in ("call.speak.started", "call.playback.started"):
            sess = call_store.get_session(call_id)
            if sess:
                sess.is_speaking = True
            return Response(status_code=200)

        if etype in ("call.speak.ended", "call.playback.ended"):
            sess = call_store.get_session(call_id)
            if sess:
                sess.is_speaking = False
                # Reset turn dedup now that we've finished speaking, so a repeated
                # short answer ("yes"/"okay") in a LATER turn isn't dropped. The
                # trailing is_final for the just-handled turn already arrived while
                # is_speaking was True, so it was deduped before this reset.
                sess.responded_text = ""
                if sess.pending_caller_text:                 # deferred barge-in (Task 7)
                    pending = sess.pending_caller_text
                    sess.pending_caller_text = None
                    await _finalize_turn(call_id, ccid, pending)
            return Response(status_code=200)

        if etype == "call.transcription":
            td = getattr(payload, "transcription_data", None)
            if not td:
                return Response(status_code=200)
            text = (getattr(td, "transcript", "") or "").strip()
            is_final = bool(getattr(td, "is_final", False))
            sess = call_store.get_session(call_id)
            if not sess or not text:
                return Response(status_code=200)
            if not is_final:
                prev = sess.last_interim_text
                sess.last_interim_text = text
                sess.last_interim_at = time.monotonic()
                _arm_silence_timer(call_id, ccid)
                if (config.CALL_BACKCHANNEL and not sess.is_speaking
                        and len(text.split()) >= 8 and not getattr(sess, "_backchanneled", False)):
                    sess._backchanneled = True
                    telephony.speak_text(ccid, "mm-hmm", language=sess.language, call_id=call_id)
                if (text and _normalize(text) == _normalize(prev)
                        and sess.speculative_key != _normalize(text)):
                    sess.speculative_key = _normalize(text)
                    sess.speculative_text = ""
                    _asyncio.create_task(_speculate(call_id, text))
                return Response(status_code=200)
            sess.last_interim_text = text
            sess.last_interim_at = sess.last_interim_at or time.monotonic()
            await _finalize_turn(call_id, ccid, text)
            return Response(status_code=200)

        if etype == "call.hangup":
            if call_id and call_store.get_session(call_id):
                background_tasks.add_task(
                    call_store.end_session, call_id, "success", "Call ended.")
                background_tasks.add_task(cleanup_call_audio, call_id)
            return Response(status_code=200)
    except Exception:
        logger.exception("Error handling Telnyx event %s (ccid=%s)", etype, str(ccid)[:18])

    return Response(status_code=200)


# ── Call history + search ───────────────────────────────────────────────────────

@router.get("/api/calls/history")
async def api_calls_history(
    direction: str = "",
    outcome: str = "",
    number: str = "",
    limit: int = 50,
):
    return call_store.get_call_history(
        direction=direction, outcome=outcome,
        number_prefix=number, limit=limit,
    )


@router.get("/api/calls/search")
async def api_calls_search(q: str = "", limit: int = 20):
    if not q:
        return []
    return call_store.search_calls(q=q, limit=limit)


@router.get("/api/calls/active")
async def api_calls_active():
    """All in-progress calls (live dashboard auto-detects calls started anywhere)."""
    return call_store.list_active()


@router.get("/api/calls/{call_id}/live")
async def api_call_live(call_id: str):
    """Live status + transcript for an in-progress call (in-memory session).

    The dashboard polls this while a call is active. Once the call ends the
    session is gone, so we report status 'ended' and the UI falls back to history.
    """
    sess = call_store.get_session(call_id)
    if not sess:
        return {"call_id": call_id, "status": "ended", "transcript": []}
    return {
        "call_id":   sess.call_id,
        "status":    sess.status,
        "number":    sess.number,
        "goal":      sess.goal,
        "direction": sess.direction,
        "transcript": [
            {"speaker": t.speaker, "text": t.text, "timestamp": t.timestamp}
            for t in sess.transcript
        ],
    }


@router.get("/api/calls/{call_id}/transcript")
async def api_call_transcript(call_id: str):
    result = call_store.get_transcript(call_id)
    if result is None:
        return JSONResponse({"error": f"No call found: {call_id}"}, status_code=404)
    return result


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
