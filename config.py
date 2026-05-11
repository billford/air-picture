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
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")
FB_PAGE_ID = os.getenv("FB_PAGE_ID", "")
FB_ACCESS_TOKEN = os.getenv("FB_ACCESS_TOKEN", "")

# Lock file to avoid conflict with Claude Desktop MCP
LOCK_FILE = "/tmp/sdr_adsb.lock"

# Database
DB_PATH = str(Path(__file__).parent / "air_picture.db")

# SDR MCP package path (installed in mcp-sdr venv)
SDR_MCP_PATH = os.path.expanduser("~/Documents/mcp-sdr")
