"""Centralised configuration — reads all env vars once at import time."""
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Bad int for %s=%r; using default %d", name, raw, default)
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Bad float for %s=%r; using default %s", name, raw, default)
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


# Workspace
WORK_DIR = Path(os.environ.get("WORK_DIR", Path(__file__).parent.parent))

# Claude CLI
CLAUDE_BIN    = os.environ.get("CLAUDE_BIN", "claude")
ALLOWED_TOOLS = os.environ.get(
    "CLAUDE_ALLOWED_TOOLS",
    "Bash,Read,Write,Edit,Glob,Grep,LS,WebFetch,WebSearch",
)

# tgpt binary
TGPT_BIN = str(WORK_DIR / "virtual-company" / "tgpt")
if not Path(TGPT_BIN).exists():
    TGPT_BIN = str(WORK_DIR / "tgpt")

# Model constants
DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "claude-sonnet-4-6")
HAIKU_MODEL   = os.environ.get("HAIKU_MODEL",   "claude-haiku-4-5-20251001")

# Gemini
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Jira Cloud
JIRA_URL   = os.environ.get("JIRA_URL",   "")
JIRA_EMAIL = os.environ.get("JIRA_EMAIL", "")
JIRA_TOKEN = os.environ.get("JIRA_TOKEN", "")

# Email / SMTP
SMTP_HOST     = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT_NUM = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER     = os.environ.get("SMTP_USER", "")
SMTP_PASS     = os.environ.get("SMTP_PASS", "")

# IMAP
IMAP_HOST     = os.environ.get("IMAP_HOST", "imap.gmail.com")
IMAP_PORT_NUM = int(os.environ.get("IMAP_PORT", "993"))
IMAP_USER     = os.environ.get("IMAP_USER", SMTP_USER)
IMAP_PASS     = os.environ.get("IMAP_PASS", SMTP_PASS)

# Runtime
USER_EMAIL  = os.environ.get("USER_EMAIL", "sauravsubaru@gmail.com")
MAX_STORAGE = float(os.environ.get("MAX_STORAGE_GB", "10"))
MAX_HISTORY      = _env_int("MAX_HISTORY", 30)
MAX_TOOL_OUTPUT_CHARS = _env_int("MAX_TOOL_OUTPUT_CHARS", 32000)  # agent tool-output truncation cap
ROUTINE_LOG_MAX_CHARS = _env_int("ROUTINE_LOG_MAX_CHARS", 10000)  # routine run-log output cap
ASK_TIMEOUT           = _env_float("ASK_TIMEOUT", 120.0)          # inter-agent ask timeout (s)
COMPACT_THRESHOLD = int(os.environ.get("COMPACT_THRESHOLD", "20"))   # messages before auto-compact
COMPACT_KEEP      = int(os.environ.get("COMPACT_KEEP",      "6"))    # recent messages to keep verbatim

# Paths
STATE_FILE     = WORK_DIR / "nexus_state.json"
PROJECTS_FILE  = WORK_DIR / "nexus_projects.json"
CHANGELOG_FILE = WORK_DIR / "nexus_changelog.json"
MEMORY_DB      = WORK_DIR / "nexus_memory.db"
SKILLS_DIR     = Path("/app/skills")


# Bark TTS sidecar
BARK_SVC_URL = os.environ.get("BARK_SVC_URL", "http://bark-svc:9001")

# Telnyx telephony (Call Control)
TELNYX_API_KEY       = os.environ.get("TELNYX_API_KEY",       "")
TELNYX_PUBLIC_KEY    = os.environ.get("TELNYX_PUBLIC_KEY",    "")  # webhook Ed25519 signing key
TELNYX_CONNECTION_ID = os.environ.get("TELNYX_CONNECTION_ID", "")  # Call Control Application id
TELNYX_PHONE_NUMBER  = os.environ.get("TELNYX_PHONE_NUMBER",  "")
TELNYX_VOICE         = os.environ.get("TELNYX_VOICE",         "female")  # Telnyx `speak` voice
# Transcription engine: "B" = Telnyx native (reliable, accurate, low-latency, cheaper, NO interims);
# "A"/"Google" = Google (interim_results but intermittently emits ZERO events on this account);
# "" = Telnyx default. Default to B for reliability after Google went silent mid-deployment (2026-06-16).
TELNYX_TRANSCRIPTION_ENGINE = os.environ.get("TELNYX_TRANSCRIPTION_ENGINE", "B")
BASE_URL             = os.environ.get("BASE_URL", "")  # public Cloudflare tunnel URL e.g. https://nexus.example.com
CALL_BACKCHANNEL     = os.environ.get("CALL_BACKCHANNEL", "") == "1"    # experimental: emit mm-hmm on long turns
# End-of-turn detection: how long the caller's interim transcript must stay unchanged
# before we treat the turn as finished. Too low (was 700) cut callers off mid-sentence
# on natural pauses, replying to a fragment. ~1.2s tolerates normal pauses.
CALL_SILENCE_MS      = _env_int("CALL_SILENCE_MS", 1200)

# Voice
BARK_SPEAKER = os.environ.get("BARK_SPEAKER", "en-US-GuyNeural")  # edge-tts voice name

# Browser automation sidecar
BROWSER_SVC_URL = os.environ.get("BROWSER_SVC_URL", "http://browser-svc:9002")
SIDECAR_URL = _env_str("SIDECAR_URL", "http://host.docker.internal:3030")  # SRE operations sidecar


def get_credential(name: str) -> str:
    """Resolve CRED_{NAME} from env. Agents use $CRED_NAME in WEB_TYPE args."""
    return os.environ.get(f"CRED_{name.upper().replace('-', '_')}", "")
