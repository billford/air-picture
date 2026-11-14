"""Generate the daily air picture briefing via Claude API."""

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import anthropic

import config
import context
import db

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the air picture officer for Chagrin Falls, Ohio. You monitor all
aircraft that fly over the area and produce a daily intelligence-style
briefing for the base commander (who is a civilian with a sense of humor).

Write the briefing exactly as specified in the user message. Never invent
flight details not present in the data. If the data is thin, say so plainly.

When traffic is unusual, explain it only from what the data shows. The FAA
airspace status and the national traffic comparison are there for exactly
this: if they account for it, say so and cite them. If local traffic is down
but national traffic is normal and the FAA reports nothing, say the cause is
local or a data problem, and don't guess at weather or system-wide events."""

USER_TEMPLATE = """Today's date: {date}
Location: Chagrin Falls, Ohio (41.43°N, 81.40°W)
Period covered: the 24 hours from {window_start} to {window_end}

AIR TRAFFIC THIS PERIOD ({total_aircraft} total contacts, {unique_aircraft} unique aircraft):
{flight_summary}

ANOMALIES DETECTED ({anomaly_count} total):
{anomaly_summary}

COMPARISON TO THE SAME 24 HOURS ON THE PREVIOUS {baseline_days} DAYS:
{baseline_comparison}

NATIONAL AIRSPACE STATUS (FAA, nasstatus.faa.gov):
{nas_status}

NATIONAL TRAFFIC (OpenSky, continental US):
{national_traffic}

Write a daily air picture briefing that:
- Opens with a header: AIR PICTURE — CHAGRIN FALLS, OH — {date}
- Follows with a one-line EXECUTIVE SUMMARY (busy/quiet/unusual)
- Has a NOTABLE TRAFFIC section listing interesting flights with plain English descriptions
- Has an ANOMALIES section calling out flagged contacts with mild dramatic flair but factual
- Has a PATTERN NOTES section on traffic patterns, timing, regulars
- Has a NATIONAL PICTURE section, one to three sentences, on FAA ground stops,
  delay programs or national traffic that bear on today's numbers. If nothing
  notable happened nationally, say so in one line.
- Closes with END OF DAILY AIR PICTURE

Tone: professional but not boring, like a good military briefing with the occasional dry observation.
Length: 300–450 words. Never make up flight details not in the data."""


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

    # The per-scan checks (missing regulars, traffic deviation) log the same
    # anomaly again every scan: ~1,300 rows a day, mostly repeats. Keep the
    # latest of each, in order of first appearance.
    latest = {}
    for a in anomalies:
        key = (a["anomaly_type"], a["icao_hex"], a["callsign"])
        latest.pop(key, None)
        latest[key] = a

    # Missing regulars scale with how quiet the day is, not with anything
    # notable: on a grounding day there are ~700, one line each, which was
    # most of a 100k-character prompt. Summarise them by operator prefix.
    missing = [a for a in latest.values() if a["anomaly_type"] == "missing_regular"]
    lines = []
    if missing:
        ops = Counter((a["callsign"] or "?")[:3] for a in missing)
        top = ", ".join(f"{op} {n}" for op, n in ops.most_common(15))
        sample = ", ".join(sorted({a["callsign"] for a in missing if a["callsign"]})[:20])
        lines.append(f"  [MISSING_REGULAR] {len(missing)} regular flights absent. "
                     f"By operator: {top}. Examples: {sample}")

    for a in latest.values():
        if a["anomaly_type"] == "missing_regular":
            continue
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
        f"This period: {today_count} aircraft. "
        f"Same 24 hours, {days}-day average: {avg:.0f} aircraft. "
        f"This period is {abs(deviation):.0f}% {direction} average."
    )


def _local(ts: datetime) -> str:
    return ts.astimezone(ZoneInfo("America/New_York")).strftime("%a %b %d %I:%M %p %Z")


def report_window(date_str: Optional[str], now: Optional[datetime] = None) -> tuple:
    """(start, end) the report covers.

    Today's report covers the 24 hours before it runs. A report for a past
    date (agent.py --report --date) covers that UTC calendar day, which is
    the only window it can sensibly mean.
    """
    now = now or datetime.now(timezone.utc)
    if date_str is None or date_str == now.date().isoformat():
        return now - timedelta(hours=24), now
    start = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def generate_report(date_str: Optional[str] = None) -> str:
    """Generate and return the daily air picture report text."""
    if date_str is None:
        date_str = datetime.now(timezone.utc).date().isoformat()

    start, end = report_window(date_str)
    flights = db.get_window_flights(start, end)
    anomalies = db.get_window_anomalies(start, end)
    baseline = db.get_window_baseline(end, config.REPORT_DAYS)
    busiest_hour = db.get_window_busiest_hour(start, end)

    unique_icaos = {f["icao_hex"] for f in flights}
    total = len(flights)
    unique = len(unique_icaos)

    prompt = USER_TEMPLATE.format(
        date=date_str,
        window_start=_local(start),
        window_end=_local(end),
        total_aircraft=total,
        unique_aircraft=unique,
        flight_summary=_format_flights(flights),
        anomaly_count=len(anomalies),
        anomaly_summary=_format_anomalies(anomalies),
        baseline_days=config.REPORT_DAYS,
        baseline_comparison=_format_baseline(baseline, total),
        nas_status=context.summarize_nas(start, end),
        national_traffic=context.summarize_national(start, end, config.REPORT_DAYS),
    )

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    logger.info("Generating report for %s (%s flights, %s anomalies)", date_str, total, len(anomalies))

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
