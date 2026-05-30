"""
Self-Healing Phoenix — zone-based source file protection.

Zone model:
  immutable:  cannot be modified by any agent (core infrastructure)
  protected:  requires email approval before writing (executor, router, etc.)
  surface:    auto-applied (static HTML/CSS/JS — visually reversible)
  learning:   auto-applied after passing pytest (services, skills, etc.)
"""
import difflib
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from app import config

logger = logging.getLogger(__name__)

APPROVALS_FILE = config.WORK_DIR / "nexus_pending_approvals.json"

# ── Zone definitions ───────────────────────────────────────────────────────────

# Relative-to-/app/ path segments that are NEVER modifiable
_IMMUTABLE = (
    "app/main.py",
    "skills/loader.py",
    "skills/core/",
)

# Relative-to-/app/ exact paths that require email approval
_PROTECTED = frozenset([
    "app/agents/executor.py",
    "app/agents/definitions.py",
    "app/api/router.py",
    "app/api/websocket.py",
    "requirements.txt",
    "Dockerfile",
    "docker-compose.yml",
    "entrypoint.sh",
])

# Relative-to-/app/ prefix for auto-applied surface changes
_SURFACE_PREFIX = "app/static/"


def _normalise(raw: str) -> str:
    """Strip container/host path prefixes to get a path relative to /app/."""
    p = raw.strip()
    for prefix in (
        "/workspace/virtual-company/",
        "virtual-company/",
        "/app/",
    ):
        if p.startswith(prefix):
            p = p[len(prefix):]
            break
    return p


def classify_path(file_path: str) -> str:
    """Return 'immutable' | 'protected' | 'surface' | 'learning'."""
    p = _normalise(file_path)
    for seg in _IMMUTABLE:
        if p == seg or p.startswith(seg):
            return "immutable"
    if p in _PROTECTED:
        return "protected"
    if p.startswith(_SURFACE_PREFIX):
        return "surface"
    return "learning"


# ── Approval state ─────────────────────────────────────────────────────────────

def load_approvals() -> dict:
    if not APPROVALS_FILE.exists():
        return {}
    try:
        return json.loads(APPROVALS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_approvals(approvals: dict) -> None:
    APPROVALS_FILE.write_text(json.dumps(approvals, indent=2), encoding="utf-8")


def create_approval(
    file_path: str,
    new_content: str,
    requesting_agent: str,
    resolved_path: Path,
) -> str:
    """Store a pending approval and return the approval ID."""
    approval_id = str(uuid.uuid4())[:8].upper()

    old_lines: list[str] = []
    if resolved_path.exists():
        old_lines = resolved_path.read_text(encoding="utf-8", errors="replace").splitlines()
    new_lines = new_content.splitlines()

    diff = "\n".join(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
        lineterm="",
    ))[:4000]

    approvals = load_approvals()
    approvals[approval_id] = {
        "id":            approval_id,
        "file_path":     file_path,
        "resolved_path": str(resolved_path),
        "new_content":   new_content,
        "agent":         requesting_agent,
        "status":        "pending",
        "created_at":    datetime.now().isoformat(),
        "diff":          diff,
    }
    save_approvals(approvals)
    logger.info("Created approval %s for %s by %s", approval_id, file_path, requesting_agent)
    return approval_id


def apply_approval(approval_id: str) -> tuple[bool, str]:
    """Write the file and mark approval as applied. Returns (success, message)."""
    approvals = load_approvals()
    entry = approvals.get(approval_id)
    if not entry:
        return False, f"Approval ID {approval_id!r} not found"
    if entry["status"] != "pending":
        return False, f"Approval {approval_id} is already {entry['status']}"
    try:
        path = Path(entry["resolved_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(entry["new_content"], encoding="utf-8")
        entry["status"]     = "applied"
        entry["applied_at"] = datetime.now().isoformat()
        save_approvals(approvals)
        logger.info("Applied approval %s → %s", approval_id, entry["file_path"])
        return True, f"Applied: {entry['file_path']}"
    except Exception as exc:
        return False, f"Apply failed: {exc}"


def deny_approval(approval_id: str) -> tuple[bool, str]:
    """Mark approval as denied without writing the file."""
    approvals = load_approvals()
    entry = approvals.get(approval_id)
    if not entry:
        return False, f"Approval ID {approval_id!r} not found"
    entry["status"]    = "denied"
    entry["denied_at"] = datetime.now().isoformat()
    save_approvals(approvals)
    logger.info("Denied approval %s for %s", approval_id, entry["file_path"])
    return True, f"Denied: {entry['file_path']}"


def build_approval_email(approval_id: str, file_path: str, agent: str, diff: str) -> tuple[str, str]:
    """Return (subject, body) for the approval request email."""
    subject = f"[Subaru] Approval needed: modify {Path(file_path).name} (ID: {approval_id})"
    body    = f"""Subaru agent '{agent}' wants to modify a protected file.

FILE: {file_path}
APPROVAL ID: {approval_id}

To approve: reply with: APPROVE {approval_id}
To deny:    reply with: DENY {approval_id}

Or use the API:
  POST http://localhost:3030/api/approvals/{approval_id}/apply
  POST http://localhost:3030/api/approvals/{approval_id}/deny

--- DIFF ---
{diff or "(new file — no previous content)"}
"""
    return subject, body
