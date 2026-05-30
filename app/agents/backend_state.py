"""
backend_state.py — 3-tier backend switching: Claude CLI → Gemini API → tgpt.

Claude Sonnet is preferred. On quota exhaustion, falls to Gemini API.
On Gemini error, falls to tgpt. Each tier has its own retry window.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

CLAUDE_RETRY_MINUTES: int = 30
GEMINI_RETRY_SECONDS: int = 5

_quota_exhausted_at:  Optional[datetime] = None
_gemini_failed_at:    Optional[datetime] = None
_current_backend:     str = "claude"   # "claude" | "gemini" | "tgpt"

QUOTA_KEYWORDS = [
    "quota exceeded", "out of tokens", "session limit",
    "too many requests", "rate limit", "token limit",
]


def get_current_backend() -> str:
    return _current_backend


def should_use_claude() -> bool:
    if _quota_exhausted_at is None:
        return True
    return datetime.now() >= _quota_exhausted_at + timedelta(minutes=CLAUDE_RETRY_MINUTES)


def should_use_gemini() -> bool:
    """True when Claude is exhausted but Gemini is still healthy (or retry window passed)."""
    if should_use_claude():
        return False
    if _gemini_failed_at is None:
        return True
    return datetime.now() >= _gemini_failed_at + timedelta(seconds=GEMINI_RETRY_SECONDS)


def gemini_available() -> bool:
    """True when Gemini API key is configured and hasn't hit an error recently.
    Unlike should_use_gemini(), this is independent of Claude quota state —
    used for proactive task-type routing."""
    from app import config as _cfg
    if not _cfg.GEMINI_API_KEY:
        return False
    if _gemini_failed_at is None:
        return True
    return datetime.now() >= _gemini_failed_at + timedelta(seconds=GEMINI_RETRY_SECONDS)


def retry_due_at() -> Optional[datetime]:
    if _quota_exhausted_at is None:
        return None
    return _quota_exhausted_at + timedelta(minutes=CLAUDE_RETRY_MINUTES)


def mark_quota_exhausted() -> bool:
    global _quota_exhausted_at, _current_backend
    _quota_exhausted_at = datetime.now()
    changed = _current_backend != "gemini"
    _current_backend = "gemini"
    if changed:
        logger.warning("Claude quota exhausted — switching to Gemini.")
    return changed


def mark_gemini_failed() -> bool:
    global _gemini_failed_at, _current_backend
    _gemini_failed_at = datetime.now()
    changed = _current_backend != "tgpt"
    _current_backend = "tgpt"
    if changed:
        logger.warning("Gemini API failed — switching to tgpt.")
    return changed


def mark_claude_recovered() -> bool:
    global _quota_exhausted_at, _gemini_failed_at, _current_backend
    _quota_exhausted_at = None
    _gemini_failed_at   = None
    changed = _current_backend != "claude"
    _current_backend = "claude"
    if changed:
        logger.info("Claude recovered — switching back from fallback.")
    return changed


def is_quota_error(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in QUOTA_KEYWORDS)


def status_dict() -> dict:
    due = retry_due_at()
    return {
        "backend":      _current_backend,
        "quota_ok":     _quota_exhausted_at is None,
        "gemini_ok":    _gemini_failed_at is None,
        "retry_at":     due.strftime("%H:%M") if due else None,
        "exhausted_at": _quota_exhausted_at.isoformat() if _quota_exhausted_at else None,
    }
