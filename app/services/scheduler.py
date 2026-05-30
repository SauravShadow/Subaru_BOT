"""
Cron-based routine scheduler.

Race-condition-safe: uses a per-minute fire key so a routine fires
at most once per scheduled minute, even when the 30-second loop
interval is shorter than the minimum 1-minute cron granularity.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pytz
from croniter import croniter

from app import config

logger = logging.getLogger(__name__)

ROUTINES_FILE     = config.WORK_DIR / "nexus_routines.json"
ROUTINE_LOGS_FILE = config.WORK_DIR / "nexus_routine_logs.json"


# ── Persistence helpers ────────────────────────────────────────────────────────

def load_routines() -> list[dict]:
    if not ROUTINES_FILE.exists():
        return []
    try:
        return json.loads(ROUTINES_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("load_routines failed: %s", exc)
        return []


def save_routines(routines: list[dict]) -> None:
    ROUTINES_FILE.write_text(json.dumps(routines, indent=2), encoding="utf-8")


def update_routine_run(routine_id: str, status: str, output: str) -> None:
    """Persist last_run, last_status, run_count to nexus_routines.json."""
    routines = load_routines()
    for r in routines:
        if r["id"] == routine_id:
            r["last_run"]    = datetime.now().isoformat()
            r["last_status"] = status
            r["run_count"]   = r.get("run_count", 0) + 1
            break
    save_routines(routines)
    _append_run_log(routine_id, status, output)


def _append_run_log(routine_id: str, status: str, output: str) -> None:
    logs: list[dict] = []
    if ROUTINE_LOGS_FILE.exists():
        try:
            logs = json.loads(ROUTINE_LOGS_FILE.read_text())
        except Exception:
            pass
    logs.append({
        "routine_id": routine_id,
        "status":     status,
        "output":     output[:2000],
        "timestamp":  datetime.now().isoformat(),
    })
    ROUTINE_LOGS_FILE.write_text(
        json.dumps(logs[-200:], indent=2), encoding="utf-8"
    )


def get_routine_logs(routine_id: str, limit: int = 10) -> list[dict]:
    if not ROUTINE_LOGS_FILE.exists():
        return []
    try:
        logs = json.loads(ROUTINE_LOGS_FILE.read_text())
        return [l for l in reversed(logs) if l["routine_id"] == routine_id][:limit]
    except Exception:
        return []


# ── Routine execution ──────────────────────────────────────────────────────────

async def run_routine(routine: dict) -> str:
    """Execute a routine: run the agent, store logs, broadcast completion."""
    from app.agents.executor import run_agent
    from app.api.websocket import broadcast_event

    routine_id    = routine["id"]
    output_acc: list[str] = []

    async def _collect(data: dict) -> None:
        if data.get("type") == "assistant":
            for blk in data.get("message", {}).get("content", []):
                if blk.get("type") == "text" and blk["text"]:
                    output_acc.append(blk["text"])

    logger.info("Running routine '%s'", routine_id)
    try:
        await run_agent(routine["agent"], routine["prompt"], _collect, model="claude")
        output = "".join(output_acc)
        status = "success"
    except Exception as exc:
        output = f"[Error: {exc}]"
        status = "error"
        logger.error("Routine '%s' failed: %s", routine_id, exc)

    update_routine_run(routine_id, status, output)

    await broadcast_event({
        "type":       "routine_completed",
        "routine_id": routine_id,
        "status":     status,
        "output":     output[:500],
        "timestamp":  datetime.now().isoformat(),
    })

    return output


# ── Scheduler loop ─────────────────────────────────────────────────────────────

async def start_scheduler_loop() -> None:
    """Check routines every 30 s; fire each at most once per scheduled minute."""
    logger.info("Subaru Scheduler started.")
    fired: dict[str, str] = {}   # fire_key → fired_at (ISO)

    while True:
        try:
            _tick(fired)
        except Exception as exc:
            logger.error("Scheduler tick error: %s", exc)
        await asyncio.sleep(30)


def _tick(fired: dict) -> None:
    """Evaluate all routines and schedule tasks for those due now."""
    for routine in load_routines():
        if not routine.get("enabled", True):
            continue
        try:
            _maybe_fire(routine, fired)
        except Exception as exc:
            logger.warning("Routine '%s' check error: %s", routine.get("id"), exc)

    # Prune fire keys older than 2 minutes
    cutoff = (datetime.utcnow() - timedelta(minutes=2)).isoformat()
    for k in [k for k, v in list(fired.items()) if v < cutoff]:
        fired.pop(k, None)


def _maybe_fire(routine: dict, fired: dict) -> None:
    """Schedule routine if the current minute is a scheduled minute and hasn't fired yet.

    Race-condition-safe: the fire_key is ``<id>:<YYYYMMDDHHMM>`` so a routine
    fires at most once per scheduled minute regardless of how many times the
    scheduler loop ticks within that minute.
    """
    if not routine.get("enabled", True):
        return

    tz_name = routine.get("timezone", "UTC")
    try:
        tz = pytz.timezone(tz_name)
    except Exception:
        tz = pytz.UTC

    now_local = datetime.now(tz)
    now_naive = now_local.replace(tzinfo=None)

    # Truncate to the current minute boundary and check if the schedule fires there.
    minute_start = now_naive.replace(second=0, microsecond=0)
    cron         = croniter(routine["schedule"], minute_start - timedelta(seconds=1))
    next_naive   = cron.get_next(datetime)

    if next_naive != minute_start:
        return   # current minute is not a scheduled minute

    fire_key = f"{routine['id']}:{minute_start.strftime('%Y%m%d%H%M')}"
    if fire_key in fired:
        return   # already fired this minute

    fired[fire_key] = datetime.utcnow().isoformat()
    asyncio.create_task(run_routine(routine))
    logger.info("Fired routine '%s' (schedule=%s)", routine["id"], routine["schedule"])
