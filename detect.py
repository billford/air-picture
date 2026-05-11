"""Anomaly detection for the Air Picture agent."""

import logging
from datetime import datetime, timedelta
from typing import List

import config
import db

logger = logging.getLogger(__name__)


def _hex_in_range(icao_hex: str, low: str, high: str) -> bool:
    try:
        val = int(icao_hex, 16)
        return int(low, 16) <= val <= int(high, 16)
    except ValueError:
        return False


def classify_hex(icao_hex: str) -> dict:
    """Return classification info for an ICAO hex address."""
    icao = icao_hex.upper()

    for low, high in config.MILITARY_RANGES:
        if _hex_in_range(icao, low, high):
            return {"type": "military", "country": "US Military"}

    for (low, high), country in config.FOREIGN_RANGES.items():
        if _hex_in_range(icao, low, high):
            return {"type": "foreign", "country": country}

    if _hex_in_range(icao, config.US_CIVIL_LOW, config.US_CIVIL_HIGH):
        return {"type": "us_civil", "country": "United States"}

    return {"type": "unknown", "country": "Unknown"}


def _is_interesting_callsign(callsign: str) -> bool:
    cs = callsign.upper()
    return any(cs.startswith(p) for p in config.INTERESTING_PREFIXES)


def run_anomaly_detection(aircraft_list: list) -> List[dict]:
    """
    Check a list of Aircraft objects against anomaly rules.
    Logs any detected anomalies to the database and returns them.
    """
    detected = []
    now = datetime.utcnow()

    for ac in aircraft_list:
        icao = ac.icao_hex.upper()
        alt = ac.altitude_ft
        speed = ac.speed_kts
        callsign = ac.callsign

        # Very high altitude
        if alt and alt > config.HIGH_ALTITUDE_THRESHOLD_FT:
            desc = (
                f"Contact at {alt:,} ft — above standard commercial ceiling "
                f"({config.HIGH_ALTITUDE_THRESHOLD_FT:,} ft). "
                f"Consistent with large business jet or military. Callsign: {callsign or 'none'}."
            )
            db.log_anomaly(icao, callsign, "very_high_altitude", desc, alt)
            detected.append({"icao_hex": icao, "callsign": callsign, "type": "very_high_altitude", "description": desc})

        # Very low and fast
        if alt and speed and alt < config.LOW_ALTITUDE_THRESHOLD_FT and speed > config.LOW_ALT_MIN_SPEED_KTS:
            desc = (
                f"Contact at {alt:,} ft moving {speed:.0f} kts. "
                f"Low and fast — may indicate military low-level, approach gone wide, "
                f"or misreported altitude."
            )
            db.log_anomaly(icao, callsign, "low_and_fast", desc, alt)
            detected.append({"icao_hex": icao, "callsign": callsign, "type": "low_and_fast", "description": desc})

        # No callsign at cruise altitude
        if not callsign and alt and alt > 20000:
            desc = (
                f"Contact {icao} at {alt:,} ft transmitting no callsign. "
                f"Mode S transponder active but no flight ID broadcast."
            )
            db.log_anomaly(icao, callsign, "no_callsign_high", desc, alt)
            detected.append({"icao_hex": icao, "callsign": callsign, "type": "no_callsign_high", "description": desc})

        # Hex code classification
        classification = classify_hex(icao)
        if classification["type"] == "military":
            desc = f"ICAO {icao} falls within US military hex range. Callsign: {callsign or 'none'}."
            db.log_anomaly(icao, callsign, "military_hex", desc, alt)
            detected.append({"icao_hex": icao, "callsign": callsign, "type": "military_hex", "description": desc})

        elif classification["type"] == "foreign":
            country = classification["country"]
            desc = f"ICAO {icao} is registered to {country}. Callsign: {callsign or 'none'}. Altitude: {alt or 'unknown'} ft."
            db.log_anomaly(icao, callsign, "foreign_registration", desc, alt)
            detected.append({"icao_hex": icao, "callsign": callsign, "type": "foreign_registration", "description": desc})

        elif classification["type"] == "unknown":
            desc = f"ICAO {icao} does not fall within any known national allocation range."
            db.log_anomaly(icao, callsign, "unknown_hex", desc, alt)
            detected.append({"icao_hex": icao, "callsign": callsign, "type": "unknown_hex", "description": desc})

        # Interesting callsign prefixes
        if callsign and _is_interesting_callsign(callsign):
            desc = f"Callsign {callsign} matches government/military prefix list. ICAO: {icao}. Altitude: {alt or 'unknown'} ft."
            db.log_anomaly(icao, callsign, "interesting_callsign", desc, alt)
            detected.append({"icao_hex": icao, "callsign": callsign, "type": "interesting_callsign", "description": desc})

    return detected


def check_traffic_deviation(baseline: dict) -> List[dict]:
    """Compare today's traffic count to rolling baseline. Returns anomaly list."""
    anomalies = []
    today_flights = db.get_today_flights()
    today_count = len(today_flights)
    avg = baseline.get("avg_daily", 0)

    if avg == 0:
        return anomalies

    deviation = (today_count - avg) / avg

    if abs(deviation) > config.TRAFFIC_DEVIATION_THRESHOLD:
        direction = "above" if deviation > 0 else "below"
        pct = abs(deviation) * 100
        desc = (
            f"Today's traffic ({today_count} aircraft) is {pct:.0f}% {direction} "
            f"the {baseline.get('days_sampled', 7)}-day average of {avg:.0f}."
        )
        db.log_anomaly("N/A", None, "traffic_deviation", desc)
        anomalies.append({"icao_hex": "N/A", "callsign": None, "type": "traffic_deviation", "description": desc})

    return anomalies


def check_missing_regulars(baseline_days: int = 7) -> List[dict]:
    """Flag callsigns that appeared on recent days at similar times but are absent today."""
    anomalies = []
    now = datetime.utcnow()
    window_start = now - timedelta(minutes=config.REGULAR_FLIGHT_WINDOW_MINUTES)
    window_end = now + timedelta(minutes=config.REGULAR_FLIGHT_WINDOW_MINUTES)

    # Build set of callsigns seen in this time window over past N days
    cutoff = (now - timedelta(days=baseline_days)).isoformat()
    today_str = now.date().isoformat()

    try:
        import sqlite3
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row

        rows = conn.execute(
            """SELECT callsign, strftime('%H:%M', scan_time) as t
               FROM flights
               WHERE callsign IS NOT NULL
                 AND date(scan_time) != ?
                 AND scan_time >= ?
                 AND strftime('%H:%M', scan_time) BETWEEN ? AND ?
               GROUP BY callsign
               HAVING COUNT(DISTINCT date(scan_time)) >= 3""",
            (today_str, cutoff,
             window_start.strftime("%H:%M"),
             window_end.strftime("%H:%M")),
        ).fetchall()

        regular_callsigns = {r["callsign"] for r in rows}

        # Check which ones haven't shown up today
        today_rows = conn.execute(
            "SELECT DISTINCT callsign FROM flights WHERE date(scan_time) = ? AND callsign IS NOT NULL",
            (today_str,),
        ).fetchall()
        today_callsigns = {r["callsign"] for r in today_rows}

        conn.close()

        for cs in regular_callsigns:
            if cs not in today_callsigns:
                desc = f"Regular flight {cs} (seen 3+ times at this hour in past {baseline_days} days) has not appeared today."
                db.log_anomaly("N/A", cs, "missing_regular", desc)
                anomalies.append({"icao_hex": "N/A", "callsign": cs, "type": "missing_regular", "description": desc})

    except Exception as e:
        logger.warning(f"check_missing_regulars error: {e}")

    return anomalies
