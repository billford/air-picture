"""Configuration for the Air Picture agent: location, thresholds, paths and credentials."""

import os
from pathlib import Path

_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

# Observer location — Chagrin Falls, OH
OBSERVER_LAT = 41.4270
OBSERVER_LON = -81.3990

# Scan loop
SCAN_INTERVAL_MINUTES = 30
SCAN_DURATION_MINUTES = 5
PEAK_HOURS = [(7, 9), (16, 19)]
PEAK_SCAN_INTERVAL_MINUTES = 15

# Deduplication: same ICAO within this window = same flight
FLIGHT_MERGE_WINDOW_HOURS = 2

# Reporting
REPORT_TIME = "20:00"
REPORT_DAYS = 7

# Anomaly thresholds
HIGH_ALTITUDE_THRESHOLD_FT = 45000
LOW_ALTITUDE_THRESHOLD_FT = 3000
LOW_ALT_MIN_SPEED_KTS = 200
TRAFFIC_DEVIATION_THRESHOLD = 0.30
REGULAR_FLIGHT_WINDOW_MINUTES = 30

# ICAO hex ranges
MILITARY_RANGES = [
    ("AE0000", "AEFFFF"),
]

FOREIGN_RANGES = {
    ("710000", "71FFFF"): "Saudi Arabia",
    ("700000", "70FFFF"): "Saudi Arabia",
    ("C00000", "C3FFFF"): "Canada",
    ("400000", "43FFFF"): "United Kingdom",
    ("380000", "3BFFFF"): "France",
    ("3C0000", "3FFFFF"): "Germany",
    ("780000", "7BFFFF"): "China",
    ("800000", "83FFFF"): "India",
    ("E00000", "E3FFFF"): "Australia",
    ("480000", "4BFFFF"): "Netherlands",
    ("500000", "53FFFF"): "Italy",
    ("340000", "37FFFF"): "Spain",
}

US_CIVIL_LOW = "A00001"
US_CIVIL_HIGH = "AFFFFF"

INTERESTING_PREFIXES = [
    "EXEC", "SAM", "AF", "USAF", "NAVY", "PAT", "RCH", "SWORD",
    "KNIFE", "VIPER", "HAWG", "REACH", "SCOTT", "TALON",
]

# Claude API
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-6"

# Delivery
REPORT_OUTPUT_DIR = os.path.expanduser("~/air-picture/reports")
# ntfy. NTFY_URL points at the self-hosted, access-controlled server the other
# projects (waterguru, rachio) use; unset, it falls back to public ntfy.sh. That
# server refuses anonymous requests, so NTFY_USER/NTFY_PASS are required there -
# without them every push comes back 403.
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")
NTFY_URL = os.getenv("NTFY_URL", "https://ntfy.sh").rstrip("/")
NTFY_USER = os.getenv("NTFY_USER", "")
NTFY_PASS = os.getenv("NTFY_PASS", "")
FB_PAGE_ID = os.getenv("FB_PAGE_ID", "")
FB_ACCESS_TOKEN = os.getenv("FB_ACCESS_TOKEN", "")
ZAPIER_WEBHOOK_URL = os.getenv("ZAPIER_WEBHOOK_URL", "")
# Email. Plain SMTP so any provider works. For Cloudflare Email Sending:
# SMTP_HOST=smtp.mx.cloudflare.net, SMTP_PORT=465, SMTP_USER=api_token,
# SMTP_PASS=<API token with Email Sending: Edit>, and EMAIL_FROM on a domain
# onboarded for Email Sending. Port 465 is implicit TLS; anything else STARTTLS.
EMAIL_TO = os.getenv("EMAIL_TO", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
# Publishing moved from GitHub Pages to Cloudflare Pages; GITHUB_PAGES is still
# honoured so an existing .env keeps working.
PUBLISH_SITE = os.getenv("PUBLISH_SITE", os.getenv("GITHUB_PAGES", "true")).lower() == "true"

# Lock file to avoid conflict with Claude Desktop MCP
LOCK_FILE = "/tmp/sdr_adsb.lock"

# Operational alerts (alerts.py) — pipeline breakage, not aircraft.
# Reuses NTFY_TOPIC: one more channel to configure is one more to forget.
# The repeat interval matters more than it looks: build_and_push.sh runs after
# every scan, so an unthrottled failure alert is ~96 pushes a day.
ALERT_STATE_FILE = str(Path(__file__).parent / ".alert_state.json")
ALERT_REPEAT_HOURS = float(os.getenv("ALERT_REPEAT_HOURS", "6"))

# Database
DB_PATH = str(Path(__file__).parent / "air_picture.db")

# SDR MCP package path (installed in mcp-sdr venv).
#
# This was a bare hardcoded path to ~/Documents/mcp-sdr. When the repo moved to
# ~/Projects, every scan lost the SDR and silently fell back to OpenSky - the
# import error read "No module named 'sdr_mcp'", which looks like a missing
# install rather than a stale path, so it went unnoticed for weeks.
#
# Resolve against the places it actually lives, newest layout first, and let
# the environment override. SDR_MCP_PATH stays a plain string so callers can
# keep doing sys.path.insert() with it.
_SDR_MCP_CANDIDATES = ("~/Projects/mcp-sdr", "~/Documents/mcp-sdr")

def _resolve_sdr_mcp_path() -> str:
    """First candidate that actually contains the sdr_mcp package."""
    override = os.getenv("SDR_MCP_PATH", "")
    candidates = (override,) + _SDR_MCP_CANDIDATES if override else _SDR_MCP_CANDIDATES
    for candidate in candidates:
        resolved = Path(candidate).expanduser()
        if (resolved / "sdr_mcp" / "__init__.py").exists():
            return str(resolved)
    # Nothing found: return the preferred location so the failure names a real
    # path instead of an empty string.
    return str(Path(_SDR_MCP_CANDIDATES[0]).expanduser())

SDR_MCP_PATH = _resolve_sdr_mcp_path()
