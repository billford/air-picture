"""Outside context for the daily report: FAA airspace status and national traffic.

The local receiver can say traffic was light. It cannot say why. On a day the
FAA grounds flights nationally, the report used to guess at "system-wide or
weather-related suppression", or worse, blame nothing in particular. These two
sources let it say what happened instead of guessing:

  - FAA NAS status (nasstatus.faa.gov): ground stops, ground delay programs,
    delays and closures by airport. Public, no key. It shows only the present
    moment, so each scan stores a snapshot and the report reads the history.
  - A national airborne count from OpenSky over the continental US. If local
    traffic falls and national traffic falls with it, something happened to
    the air system. If only local traffic falls, suspect the receiver or the
    data, not the sky.

collect() runs once per scan and never raises: outside context is a nice to
have, and a failing FAA endpoint must never cost a scan its data.
"""

import hashlib
import json
import logging
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Optional

import db
import opensky

logger = logging.getLogger(__name__)

FAA_URL = "https://nasstatus.faa.gov/api/airport-status-information"
FAA_SOURCE = "faa_nas"
NATIONAL_SOURCE = "national_airborne"

# Continental US. At this size an anonymous OpenSky query costs 4 of the
# 400 daily credits, so it runs at most hourly: ~96 credits a day, next to
# ~62 for the one-credit local query each scan makes.
CONUS_BBOX = (24.5, -125.0, 49.5, -66.9)  # lat_min, lon_min, lat_max, lon_max
NATIONAL_MIN_INTERVAL = timedelta(minutes=55)

# Standing NOTAM closures, e.g. "AD AP CLSD TO NON SKED TRANSIENT GA ACFT EXC
# PPR" at LAX, SAN and LAS, which stay listed for months and say nothing about
# today's traffic.
_ROUTINE_REASONS = ("NON SKED TRANSIENT GA",)


# ---------------------------------------------------------------------------
# FAA NAS status
# ---------------------------------------------------------------------------

def _flatten(elem: ET.Element) -> dict:
    """Leaf tags (and attributes) under elem as {tag: text}, first value wins."""
    out = {}
    for node in elem.iter():
        for attr, val in node.attrib.items():
            out.setdefault(f"{node.tag}_{attr}", val)
        if node is not elem and len(node) == 0 and (node.text or "").strip():
            out.setdefault(node.tag, node.text.strip())
    return out


def parse_nas_status(xml_text: str) -> list:
    """Turn the FAA airport-status XML into a list of event dicts.

    Parsed generically: each <Delay_type> has a <Name> and one list element of
    records. The record shapes differ by type (ground stops carry End_Time,
    delay programs Avg/Max, airspace flow programs CTL_Element), so every leaf
    is kept in `details` rather than picking fields per type.
    """
    root = ET.fromstring(xml_text)
    events = []
    for delay_type in root.iter("Delay_type"):
        name = (delay_type.findtext("Name") or "Unknown").strip()
        for listing in delay_type:
            if listing.tag == "Name":
                continue
            for record in listing:
                details = _flatten(record)
                airport = details.get("ARPT") or details.get("CTL_Element")
                reason = details.get("Reason", "")
                if any(r in reason for r in _ROUTINE_REASONS):
                    continue
                key = hashlib.sha1(f"{name}|{airport}|{reason}".encode()).hexdigest()
                events.append({
                    "key": key,
                    "delay_type": name,
                    "airport": airport,
                    "reason": reason,
                    "details": json.dumps(details, sort_keys=True),
                })
    return events


def fetch_nas_status() -> Optional[list]:
    """Current FAA events, or None if the feed couldn't be read."""
    req = urllib.request.Request(FAA_URL, headers={"User-Agent": "air-picture/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return parse_nas_status(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ET.ParseError) as e:
        logger.warning("FAA NAS status unavailable: %s", e)
        return None


# ---------------------------------------------------------------------------
# National traffic
# ---------------------------------------------------------------------------

def _national_due(now: datetime) -> bool:
    last = db.last_ok_context_poll(NATIONAL_SOURCE)
    return last is None or now - last >= NATIONAL_MIN_INTERVAL


# ---------------------------------------------------------------------------
# Collection (once per scan)
# ---------------------------------------------------------------------------

def collect(now: Optional[datetime] = None) -> None:
    """Snapshot FAA status every scan and national traffic hourly. Never raises."""
    now = now or datetime.now(timezone.utc)
    try:
        events = fetch_nas_status()
        db.log_context_poll(FAA_SOURCE, events is not None,
                            len(events) if events is not None else None, when=now)
        if events:
            db.upsert_nas_events(events, when=now)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning("FAA context collection failed: %s", e)

    try:
        if _national_due(now):
            count = opensky.count_airborne(CONUS_BBOX)
            db.log_context_poll(NATIONAL_SOURCE, count is not None, count, when=now)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning("National traffic collection failed: %s", e)


# ---------------------------------------------------------------------------
# Report text
# ---------------------------------------------------------------------------

def _hhmm(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%d %b %H:%MZ")


def _event_line(e: dict) -> str:
    details = json.loads(e["details"] or "{}")
    extra = ", ".join(
        f"{k}={v}" for k, v in details.items()
        if k not in ("ARPT", "CTL_Element", "Reason")
    )
    seen = f"seen {_hhmm(e['first_seen'])}-{_hhmm(e['last_seen'])}"
    line = f"    {e['airport'] or '?'}: {e['reason'] or 'no reason given'} [{seen}]"
    return f"{line} ({extra})" if extra else line


def summarize_nas(start: datetime, end: datetime, limit: int = 40) -> str:
    """FAA events during the window, as plain lines for the report prompt."""
    polls = db.get_context_polls(FAA_SOURCE, start, end)
    ok = [p for p in polls if p["ok"]]
    if not polls:
        return "FAA status was not checked during this period."
    if not ok:
        return f"FAA status could not be reached ({len(polls)} attempts); airspace status unknown."

    events = db.get_nas_events(start, end)
    coverage = f"FAA status checked {len(ok)} time{'s' if len(ok) != 1 else ''}"
    if len(ok) < len(polls):
        coverage += f" ({len(polls) - len(ok)} attempts failed)"
    if not events:
        return f"{coverage}. No ground stops, delay programs, delays or closures reported."

    by_type = {}
    for e in events:
        by_type.setdefault(e["delay_type"], []).append(e)
    lines = [f"{coverage}. {len(events)} events:"]
    for name, items in by_type.items():
        lines.append(f"  {name} ({len(items)}):")
        lines.extend(_event_line(e) for e in items[:limit])
        if len(items) > limit:
            lines.append(f"    …and {len(items) - limit} more")
    return "\n".join(lines)


def summarize_national(start: datetime, end: datetime, days: int = 7) -> str:
    """Mean national airborne count in the window vs the same window on prior days."""
    def window_mean(s, e):
        vals = [p["value"] for p in db.get_context_polls(NATIONAL_SOURCE, s, e)
                if p["ok"] and p["value"] is not None]
        return (mean(vals), len(vals)) if vals else (None, 0)

    today, n = window_mean(start, end)
    if today is None:
        return "No national traffic samples for this period."

    prior = []
    for k in range(1, days + 1):
        m, _ = window_mean(start - timedelta(days=k), end - timedelta(days=k))
        if m is not None:
            prior.append(m)

    text = f"Continental US, mean airborne aircraft: {today:.0f} ({n} hourly samples)."
    if len(prior) < 2:
        return text + " Too little history for comparison yet (collection began 2026-11-14)."
    base = mean(prior)
    pct = (today - base) / base * 100 if base else 0
    direction = "above" if pct >= 0 else "below"
    return (text + f" Same hours over the previous {len(prior)} days: {base:.0f}."
            f" National traffic is {abs(pct):.0f}% {direction} normal.")
