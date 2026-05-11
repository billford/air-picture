"""Generate the daily air picture briefing via Claude API."""

import logging
from datetime import datetime
from typing import Optional

import anthropic

import config
import db

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the air picture officer for Chagrin Falls, Ohio. You monitor all
aircraft that fly over the area and produce a daily intelligence-style
briefing for the base commander (who is a civilian with a sense of humor).

Write the briefing exactly as specified in the user message. Never invent
flight details not present in the data. If the data is thin, say so plainly."""

USER_TEMPLATE = """Today's date: {date}
Location: Chagrin Falls, Ohio (41.43°N, 81.40°W)

TODAY'S AIR TRAFFIC ({total_aircraft} total contacts, {unique_aircraft} unique aircraft):
{flight_summary}

ANOMALIES DETECTED ({anomaly_count} total):
{anomaly_summary}

COMPARISON TO {baseline_days}-DAY AVERAGE:
{baseline_comparison}

Write a daily air picture briefing that:
- Opens with a header: AIR PICTURE — CHAGRIN FALLS, OH — {date}
- Follows with a one-line EXECUTIVE SUMMARY (busy/quiet/unusual)
- Has a NOTABLE TRAFFIC section listing interesting flights with plain English descriptions
- Has an ANOMALIES section calling out flagged contacts with mild dramatic flair but factual
- Has a PATTERN NOTES section on traffic patterns, timing, regulars
- Closes with END OF DAILY AIR PICTURE

Tone: professional but not boring, like a good military briefing with the occasional dry observation.
Length: 300–400 words. Never make up flight details not in the data."""


def _format_flights(flights: list) -> str:
    if not flights:
        return "No flights logged today."

    lines = []
    seen_icaos = set()
    for f in flights:
        icao = f["icao_hex"]
        if icao in seen_icaos:
            continue
        seen_icaos.add(icao)

        cs = f["callsign"] or "(no callsign)"
        alt = f"{f['altitude_ft']:,} ft" if f["altitude_ft"] else "alt unknown"
        speed = f"{f['speed_kts']:.0f} kts" if f["speed_kts"] else ""
        hdg = f"hdg {f['heading_deg']:.0f}°" if f["heading_deg"] else ""
        parts = [f"  {cs} [{icao}]", alt]
        if speed:
            parts.append(speed)
        if hdg:
            parts.append(hdg)
        if f["lat"] and f["lon"]:
            parts.append(f"@ {f['lat']:.3f},{f['lon']:.3f}")
        lines.append(" — ".join(parts))

    return "\n".join(lines[:80])  # cap at 80 entries to keep prompt manageable


def _format_anomalies(anomalies: list) -> str:
    if not anomalies:
        return "No anomalies detected."

    lines = []
    for a in anomalies:
        cs = a["callsign"] or "(no callsign)"
        lines.append(f"  [{a['anomaly_type'].upper()}] {cs} [{a['icao_hex']}]: {a['description']}")
    return "\n".join(lines)


def _format_baseline(baseline: dict, today_count: int) -> str:
    avg = baseline.get("avg_daily", 0)
    days = baseline.get("days_sampled", 0)

    if days == 0:
        return "Insufficient history for baseline comparison (first week of operation)."

    deviation = ((today_count - avg) / avg * 100) if avg else 0
    direction = "above" if deviation >= 0 else "below"
    return (
        f"Today: {today_count} aircraft. "
        f"{days}-day average: {avg:.0f} aircraft/day. "
        f"Today is {abs(deviation):.0f}% {direction} average."
    )


def generate_report(date_str: Optional[str] = None) -> str:
    """Generate and return the daily air picture report text."""
    if date_str is None:
        date_str = datetime.utcnow().date().isoformat()

    flights = db.get_date_flights(date_str)
    anomalies = db.get_today_anomalies() if date_str == datetime.utcnow().date().isoformat() else []
    baseline = db.get_rolling_baseline(config.REPORT_DAYS)
    busiest_hour = db.get_busiest_hour_today()

    unique_icaos = {f["icao_hex"] for f in flights}
    total = len(flights)
    unique = len(unique_icaos)

    prompt = USER_TEMPLATE.format(
        date=date_str,
        total_aircraft=total,
        unique_aircraft=unique,
        flight_summary=_format_flights(flights),
        anomaly_count=len(anomalies),
        anomaly_summary=_format_anomalies(anomalies),
        baseline_days=config.REPORT_DAYS,
        baseline_comparison=_format_baseline(baseline, total),
    )

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    logger.info(f"Generating report for {date_str} ({total} flights, {len(anomalies)} anomalies)")

    response = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    report_text = response.content[0].text

    db.save_daily_summary(
        date_str=date_str,
        total=total,
        unique=unique,
        busiest_hour=busiest_hour,
        anomaly_count=len(anomalies),
        report_text=report_text,
    )

    return report_text
