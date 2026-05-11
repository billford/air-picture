# Air Picture — Aircraft Watch Agent

Monitors aircraft over Chagrin Falls, Ohio throughout the day. Logs all
ADS-B traffic to SQLite, detects anomalies, and generates a daily
intelligence-style briefing via Claude.

## Setup

```bash
cd ~/air-picture

# 1. Create venv and install deps
python3 -m venv .venv
.venv/bin/pip install anthropic
.venv/bin/pip install -e ~/Documents/mcp-sdr

# 2. Configure credentials
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY at minimum

# 3. Initialize database
.venv/bin/python agent.py --init

# 4. Test a scan (runs for SCAN_DURATION_MINUTES, default 5)
.venv/bin/python agent.py --scan

# 5. Check status
.venv/bin/python agent.py --status

# 6. Generate a report manually
.venv/bin/python agent.py --report
```

## Install crontab

```bash
crontab -l | cat - crontab.txt | crontab -
```

This installs:
- Scans every 30 min around the clock
- Scans every 15 min during peak hours (7–9 AM, 4–7 PM)
- Report generation at 8 PM daily

## Conflict management

The agent writes a PID lock file to `/tmp/sdr_adsb.lock` before accessing
the RTL-SDR dongle. If Claude Desktop is running an ADS-B session, the
cron job will detect the stale or active lock and skip the cycle cleanly.

## Delivery

| Channel | Config key | Notes |
|---------|-----------|-------|
| File archive | Always on | `~/air-picture/reports/airpicture_YYYY-MM-DD.txt` |
| ntfy.sh push | `NTFY_TOPIC` | Free, no account. Pick any topic name. |
| Facebook page | `FB_PAGE_ID` + `FB_ACCESS_TOKEN` | Reuses scanner-page token |

## File structure

```
air-picture/
├── agent.py        # CLI entry point (--scan / --report / --init / --status)
├── config.py       # All settings + .env loader
├── db.py           # SQLite operations
├── detect.py       # Anomaly detection engine
├── report.py       # Claude API briefing generation
├── deliver.py      # File / ntfy / Facebook delivery
├── air_picture.db  # SQLite database (created on --init)
├── reports/        # Daily report archive
├── crontab.txt     # Copy-paste crontab entries
└── .env            # Credentials (gitignored)
```
