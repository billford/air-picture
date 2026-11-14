#!/usr/bin/env python3
"""
Air Picture Agent — main entry point.

Usage:
    python agent.py --scan       Run one scan cycle
    python agent.py --report     Generate and deliver today's report
    python agent.py --init       Initialize the database
    python agent.py --status     Print today's stats
"""

import argparse
import logging
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# pylint: disable=wrong-import-position
import config

# sdr_mcp lives in the mcp-sdr checkout, not this venv. config resolves where
# that actually is - this used to repeat the path literal, so the two drifted
# apart and both went stale when the checkout moved.
sys.path.insert(0, config.SDR_MCP_PATH)

import alerts
import context
import db
import detect
import logs
import deliver
import opensky
# pylint: enable=wrong-import-position

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("air_picture")


# ---------------------------------------------------------------------------
# Lock file management (prevents conflict with Claude Desktop MCP)
# ---------------------------------------------------------------------------

class LockError(Exception):
    """Raised when the SDR hardware lock cannot be acquired."""


def acquire_lock() -> bool:
    """Atomically create the lock file. Returns False if the lock is already held."""
    lock = Path(config.LOCK_FILE)

    # Atomic create: O_CREAT|O_EXCL fails if the file already exists,
    # with no window between the check and the write.
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        # Lock exists — check whether the owning PID is still alive
        try:
            pid = int(lock.read_text(encoding="utf-8").strip())
            os.kill(pid, 0)
            logger.warning("SDR lock held by PID %s, skipping scan", pid)
            return False
        except (ValueError, ProcessLookupError, PermissionError):
            # Stale lock — remove and try once more atomically
            lock.unlink(missing_ok=True)
            try:
                fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
            except FileExistsError:
                logger.warning("SDR lock contested after stale removal, skipping scan")
                return False

    # Secondary check: hardware state within this process.
    # dongle_connected=True is fine — that just means the device is reachable.
    # Block only if mode is not idle (another monitor is actively running).
    try:
        from sdr_mcp.hardware import get_device, HardwareState  # pylint: disable=import-outside-toplevel
        dev = get_device()
        if dev.state != HardwareState.IDLE:
            logger.warning("SDR hardware not idle (mode=%s), skipping scan", dev.state.value)
            lock.unlink(missing_ok=True)
            return False
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.debug("Could not check hardware state: %s", e)

    return True


def release_lock():
    """Remove the SDR lock file."""
    Path(config.LOCK_FILE).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Scan cycle
# ---------------------------------------------------------------------------

def _check_traffic_baseline(baseline):
    """Print traffic deviation and missing-regular alerts if enough history exists."""
    if baseline.get("days_sampled", 0) < 3:
        return
    for a in detect.check_traffic_deviation(baseline):
        print(f"[scan] TRAFFIC: {a['description']}")

    # Summarised rather than one line each. A missing regular is both normal and
    # numerous - it fires for every routine flight that hasn't shown up yet
    # today, so it scales with the size of the baseline rather than with
    # anything having happened, and printing each one drowned the scan output it
    # sat in. Every anomaly is still recorded individually by
    # check_missing_regulars(); this changes only what reaches the log.
    missing = detect.check_missing_regulars()
    if missing:
        callsigns = sorted({a["callsign"] for a in missing if a.get("callsign")})
        shown = ", ".join(callsigns[:12])
        if len(callsigns) > 12:
            shown += f", +{len(callsigns) - 12} more"
        print(f"[scan] MISSING REGULAR: {len(missing)} absent — {shown}")


# How often to read the receiver's aircraft list during a scan. It only lists
# aircraft heard in the last 60 seconds (sdr_mcp's STALE_TIMEOUT_SECONDS), so
# anything under that catches every aircraft heard at any point in the scan.
SDR_POLL_SECONDS = 15


def _collect_sdr(monitor, duration_seconds: float, sleep=time.sleep, clock=time.monotonic) -> dict:
    """Every aircraft the receiver heard during the scan, keyed by ICAO hex.

    Reading the list once at the end, as this used to, kept only the last
    minute of a five-minute scan: 0-4 aircraft from scans that heard far more.
    Later reads win, so each aircraft keeps its most recent position.
    """
    heard = {}
    deadline = clock() + duration_seconds
    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            break
        sleep(min(SDR_POLL_SECONDS, remaining))
        for ac in monitor.get_aircraft():
            heard[ac.icao_hex.upper()] = ac
    return heard


def _merge_sources(sdr: dict, opensky_list: list) -> list:
    """Union of receiver and OpenSky aircraft. The receiver wins on overlap.

    OpenSky used to be a fallback, fetched only when the receiver returned
    nothing. With a weak receiver that inverted the data: a scan that heard
    two aircraft skipped OpenSky's 30-40, so the better the receiver behaved,
    the emptier the sky looked. Nearly all history was collected via OpenSky,
    so taking it every scan also keeps today comparable with the baseline.
    """
    merged = {ac.icao_hex.upper(): ac for ac in opensky_list}
    merged.update(sdr)
    return list(merged.values())


def run_scan():
    """Run a single ADS-B scan cycle."""
    # Before anything writes to it. launchd owns this file's descriptor, so the
    # trim is in place rather than a rename - see logs.py.
    logs.trim_in_place()

    if not acquire_lock():
        print("[scan] SDR busy (lock file present). Skipping this cycle.")
        return

    duration_seconds = config.SCAN_DURATION_MINUTES * 60
    session_id = str(uuid.uuid4())[:8]

    logger.info("Starting scan [%s] for %s min", session_id, config.SCAN_DURATION_MINUTES)
    print(f"[scan] Session {session_id} — scanning for {config.SCAN_DURATION_MINUTES} min…")

    sdr = {}
    try:
        from sdr_mcp.adsb import get_adsb_monitor  # pylint: disable=import-outside-toplevel

        monitor = get_adsb_monitor()
        monitor.start()
        try:
            sdr = _collect_sdr(monitor, duration_seconds)
        finally:
            stats = monitor.stop()
        # stats["total_aircraft"] over-counts: sdr_mcp re-counts an aircraft
        # every second it sits in dump1090's output past its own 60s expiry.
        logger.info("Scan complete: %s aircraft heard (receiver stats %s)", len(sdr), stats)

    except ImportError as e:
        # Not a hardware fault: sdr_mcp isn't importable at all, so no scan will
        # ever succeed until someone fixes the path or the install. That is a
        # different problem from "the dongle is busy", and reporting it as a
        # generic SDR error is what let a stale path hide behind the fallback
        # for weeks. Name the path we actually tried.
        logger.error(
            "sdr_mcp not importable from %s (%s) — SDR disabled, OpenSky only. "
            "Check config.SDR_MCP_PATH or set $SDR_MCP_PATH.",
            config.SDR_MCP_PATH, e,
        )
        print(f"[scan] SDR UNAVAILABLE: sdr_mcp not importable from {config.SDR_MCP_PATH}")

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Scan failed: %s — OpenSky only this cycle", e)
        print(f"[scan] SDR error ({e}) — OpenSky only this cycle")
    finally:
        release_lock()

    osky = opensky.fetch_aircraft()
    aircraft_list = _merge_sources(sdr, osky)
    logger.info("Sources: receiver %s, OpenSky %s, combined %s",
                len(sdr), len(osky), len(aircraft_list))
    print(f"[scan] receiver {len(sdr)}, OpenSky {len(osky)}, combined {len(aircraft_list)}")

    # FAA airspace status and national traffic, for the report. Before the
    # early return: a sky with nothing in it is exactly when this matters.
    context.collect()

    if not aircraft_list:
        print("[scan] No aircraft detected this cycle.")
        return

    # Log to database
    new_count = db.log_aircraft(aircraft_list, session_id)
    print(f"[scan] {len(aircraft_list)} aircraft seen, {new_count} new flights logged.")

    # Run anomaly detection
    anomalies = detect.run_anomaly_detection(aircraft_list)
    if anomalies:
        print(f"[scan] {len(anomalies)} anomalies detected:")
        for a in anomalies:
            print(f"       [{a['type']}] {a['icao_hex']} {a['callsign'] or ''}")

    # Check traffic against the same 24 hours on previous days
    baseline = db.get_window_baseline(datetime.now(timezone.utc), config.REPORT_DAYS)
    _check_traffic_baseline(baseline)

    # Rebuild and publish the site immediately when there's new data to
    # show, rather than waiting for the hourly build-site timer — keeps
    # incidents from sitting unpublished for up to an hour.
    if new_count or anomalies:
        _trigger_site_build()


def _trigger_site_build():
    """Rebuild the site and publish it, mirroring build_and_push.sh's cadence job."""
    script = Path(__file__).parent / "build_and_push.sh"
    try:
        result = subprocess.run(
            ["/bin/bash", str(script)],
            cwd=str(script.parent),
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if result.returncode != 0:
            # The script's own EXIT trap raises the alert - it has the full log
            # tail and the throttle state, and alerting here too would double
            # every notification.
            logger.error("Site build/push failed (exit %s): %s", result.returncode, result.stderr.strip())
        else:
            logger.info("Site build/push triggered after scan.")
    except subprocess.TimeoutExpired:
        # The one path the script cannot report on: we killed it, so its EXIT
        # trap never ran. Alert from here instead.
        logger.error("Site build/push timed out.")
        alerts.notify_failure(
            "site deploy",
            "Timed out after 300s and was killed; no deploy happened.",
        )


# ---------------------------------------------------------------------------
# Report generation and delivery
# ---------------------------------------------------------------------------

def run_report(date_str=None):
    """Generate today's air picture report and deliver it."""
    if not config.ANTHROPIC_API_KEY:
        print("[report] ERROR: ANTHROPIC_API_KEY not set in .env")
        sys.exit(1)

    import report as report_module  # pylint: disable=import-outside-toplevel

    date_str = date_str or datetime.now(timezone.utc).date().isoformat()
    print(f"[report] Generating air picture for {date_str}…")

    text = report_module.generate_report(date_str)
    print("\n" + "=" * 70)
    print(text)
    print("=" * 70 + "\n")

    file_path, results = deliver.deliver(text, date_str)
    alerts.report_channels(results, file_path)


# ---------------------------------------------------------------------------
# Status summary
# ---------------------------------------------------------------------------

def run_status():
    """Print today's operational stats to stdout."""
    today = datetime.now(timezone.utc).date().isoformat()
    flights = db.get_date_flights(today)
    anomalies = db.get_today_anomalies()
    baseline = db.get_rolling_baseline()
    busiest = db.get_busiest_hour_today()

    unique = len({f["icao_hex"] for f in flights})
    avg = baseline.get("avg_daily", 0)

    print(f"\nAIR PICTURE STATUS — {today}")
    print(f"  Flights logged today : {len(flights)} ({unique} unique aircraft)")
    print(f"  Anomalies flagged    : {len(anomalies)}")
    print(f"  Busiest hour         : {busiest:02d}:00" if busiest is not None else "  Busiest hour         : n/a")
    print(f"  7-day avg            : {avg:.0f}/day ({baseline.get('days_sampled', 0)} days sampled)")

    if anomalies:
        print("\n  Recent anomalies:")
        for a in anomalies[-5:]:
            print(f"    [{a['anomaly_type']}] {a['icao_hex']} — {a['description'][:80]}")
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Parse CLI arguments and dispatch to the appropriate command."""
    parser = argparse.ArgumentParser(description="Air Picture Agent")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--scan", action="store_true", help="Run one scan cycle")
    group.add_argument("--report", action="store_true", help="Generate and deliver today's report")
    group.add_argument("--init", action="store_true", help="Initialize the database")
    group.add_argument("--status", action="store_true", help="Print today's stats")
    parser.add_argument("--date", help="Date for --report (YYYY-MM-DD, default: today)")

    args = parser.parse_args()

    if args.init:
        db.init_db()
        print("[init] Database initialized.")

    elif args.scan:
        db.init_db()
        run_scan()

    elif args.report:
        run_report(args.date)

    elif args.status:
        run_status()


if __name__ == "__main__":
    main()
