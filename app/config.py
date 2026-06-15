"""Centralised configuration — reads all env vars once at import time."""
import os
from pathlib import Path

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
MAX_HISTORY      = 30
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

# Twilio telephony
TWILIO_ACCOUNT_SID  = os.environ.get("TWILIO_ACCOUNT_SID",  "")
TWILIO_AUTH_TOKEN   = os.environ.get("TWILIO_AUTH_TOKEN",   "")
TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER", "")
BASE_URL            = os.environ.get("BASE_URL", "")  # public Cloudflare tunnel URL e.g. https://nexus.example.com

# Voice
BARK_SPEAKER = os.environ.get("BARK_SPEAKER", "en-US-GuyNeural")  # edge-tts voice name

# Browser automation sidecar
BROWSER_SVC_URL = os.environ.get("BROWSER_SVC_URL", "http://browser-svc:9002")


def get_credential(name: str) -> str:
    """Resolve CRED_{NAME} from env. Agents use $CRED_NAME in WEB_TYPE args."""
    return os.environ.get(f"CRED_{name.upper().replace('-', '_')}", "")
