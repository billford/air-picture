import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

import config

logger = logging.getLogger(__name__)


def get_conn() -> sqlite3.Connection:
    """Open and return a configured database connection."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def transaction():
    """Context manager that commits on success and rolls back on exception."""
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create tables and indexes if they do not already exist."""
    with transaction() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS flights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                icao_hex TEXT NOT NULL,
                callsign TEXT,
                altitude_ft INTEGER,
                speed_kts REAL,
                heading_deg REAL,
                lat REAL,
                lon REAL,
                scan_time TIMESTAMP NOT NULL,
                first_seen TIMESTAMP NOT NULL,
                last_seen TIMESTAMP NOT NULL,
                session_id TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_flights_icao ON flights(icao_hex);
            CREATE INDEX IF NOT EXISTS idx_flights_scan_time ON flights(scan_time);
            CREATE INDEX IF NOT EXISTS idx_flights_callsign ON flights(callsign);

            CREATE TABLE IF NOT EXISTS anomalies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                icao_hex TEXT NOT NULL,
                callsign TEXT,
                anomaly_type TEXT NOT NULL,
                description TEXT,
                detected_at TIMESTAMP NOT NULL,
                altitude_ft INTEGER,
                scan_time TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_anomalies_detected ON anomalies(detected_at);

            CREATE TABLE IF NOT EXISTS daily_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE NOT NULL UNIQUE,
                total_aircraft INTEGER,
                unique_aircraft INTEGER,
                busiest_hour INTEGER,
                anomaly_count INTEGER,
                report_text TEXT,
                generated_at TIMESTAMP
            );
        """)
        _ensure_context_schema(conn)
    logger.info("Database initialized at %s", config.DB_PATH)


def _ensure_context_schema(conn: sqlite3.Connection) -> None:
    """Tables for outside context: FAA airspace events and national traffic.

    Created on demand as well as in init_db(), because existing installs never
    re-run --init.

    context_polls records every attempt, successful or not, so the report can
    tell "the FAA reported nothing" apart from "we couldn't reach the FAA".
    nas_events holds one row per distinct FAA event, widened (last_seen) each
    time a poll sees it again; the FAA feed only shows the present moment.
    """
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS context_polls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            polled_at TIMESTAMP NOT NULL,
            ok INTEGER NOT NULL,
            value REAL
        );
        CREATE INDEX IF NOT EXISTS idx_context_polls ON context_polls(source, polled_at);

        CREATE TABLE IF NOT EXISTS nas_events (
            key TEXT PRIMARY KEY,
            delay_type TEXT NOT NULL,
            airport TEXT,
            reason TEXT,
            details TEXT,
            first_seen TIMESTAMP NOT NULL,
            last_seen TIMESTAMP NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_nas_events_seen ON nas_events(last_seen);
    """)


def log_aircraft(aircraft_list: list, session_id: str) -> int:
    """Insert or update aircraft records. Returns count of new flights logged."""
    now = datetime.now(timezone.utc)
    merge_cutoff = now - timedelta(hours=config.FLIGHT_MERGE_WINDOW_HOURS)
    new_count = 0

    with transaction() as conn:
        for ac in aircraft_list:
            icao = ac.icao_hex.upper()
            callsign = ac.callsign
            alt = ac.altitude_ft
            speed = ac.speed_kts
            heading = ac.heading_deg
            lat = ac.lat
            lon = ac.lon

            # Check for recent record with same ICAO
            existing = conn.execute(
                """SELECT id, last_seen FROM flights
                   WHERE icao_hex = ? AND last_seen >= ?
                   ORDER BY last_seen DESC LIMIT 1""",
                (icao, merge_cutoff.isoformat()),
            ).fetchone()

            if existing:
                conn.execute(
                    """UPDATE flights SET
                        callsign = COALESCE(?, callsign),
                        altitude_ft = COALESCE(?, altitude_ft),
                        speed_kts = COALESCE(?, speed_kts),
                        heading_deg = COALESCE(?, heading_deg),
                        lat = COALESCE(?, lat),
                        lon = COALESCE(?, lon),
                        last_seen = ?
                       WHERE id = ?""",
                    (callsign, alt, speed, heading, lat, lon, now.isoformat(), existing["id"]),
                )
            else:
                conn.execute(
                    """INSERT INTO flights
                       (icao_hex, callsign, altitude_ft, speed_kts, heading_deg,
                        lat, lon, scan_time, first_seen, last_seen, session_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (icao, callsign, alt, speed, heading, lat, lon,
                     now.isoformat(), now.isoformat(), now.isoformat(), session_id),
                )
                new_count += 1

    return new_count


def log_anomaly(icao_hex: str, callsign: Optional[str], anomaly_type: str,
                description: str, altitude_ft: Optional[int] = None):
    """Persist a detected anomaly record to the database."""
    now = datetime.now(timezone.utc)
    with transaction() as conn:
        conn.execute(
            """INSERT INTO anomalies
               (icao_hex, callsign, anomaly_type, description, detected_at, altitude_ft, scan_time)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (icao_hex.upper(), callsign, anomaly_type, description,
             now.isoformat(), altitude_ft, now.isoformat()),
        )
    # DEBUG, not INFO: this fires once per detected anomaly, and every caller
    # already reports what it found. At INFO it duplicated each `[scan]` line,
    # and with missing_regular alone accounting for 79% of all anomalies the
    # pair built a 44MB log in 87 days. The row itself is still written above -
    # the visualisations read the table, not the log.
    logger.debug("Anomaly logged: [%s] %s — %s", anomaly_type, icao_hex, description)


def get_today_flights() -> list:
    """Return all flight records logged today (UTC)."""
    today = datetime.now(timezone.utc).date().isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM flights WHERE date(scan_time) = ? ORDER BY first_seen""",
            (today,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_date_flights(date_str: str) -> list:
    """Return all flight records for a given date string (YYYY-MM-DD)."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM flights WHERE date(scan_time) = ? ORDER BY first_seen""",
            (date_str,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_today_anomalies() -> list:
    """Return all anomaly records detected today (UTC)."""
    today = datetime.now(timezone.utc).date().isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM anomalies WHERE date(detected_at) = ? ORDER BY detected_at""",
            (today,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_rolling_baseline(days: int = 7) -> dict:
    """Returns average daily stats over the last N days (excluding today)."""
    today = datetime.now(timezone.utc).date()
    start = (today - timedelta(days=days)).isoformat()
    end = (today - timedelta(days=1)).isoformat()

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT date(scan_time) as day, COUNT(*) as cnt
               FROM flights WHERE date(scan_time) BETWEEN ? AND ?
               GROUP BY day""",
            (start, end),
        ).fetchall()

    if not rows:
        return {"avg_daily": 0, "days_sampled": 0}

    counts = [r["cnt"] for r in rows]
    return {
        "avg_daily": sum(counts) / len(counts),
        "days_sampled": len(counts),
        "daily_counts": {r["day"]: r["cnt"] for r in rows},
    }


def get_callsign_history(callsign: str, days: int = 7) -> list:
    """Return recent records for a given callsign."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM flights WHERE callsign = ? AND scan_time >= ?
               ORDER BY scan_time DESC""",
            (callsign, cutoff),
        ).fetchall()
    return [dict(r) for r in rows]


def get_busiest_hour_today() -> Optional[int]:
    """Return the UTC hour (0-23) with the most flight contacts today, or None."""
    today = datetime.now(timezone.utc).date().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            """SELECT strftime('%H', scan_time) as hr, COUNT(*) as cnt
               FROM flights WHERE date(scan_time) = ?
               GROUP BY hr ORDER BY cnt DESC LIMIT 1""",
            (today,),
        ).fetchone()
    return int(row["hr"]) if row else None


def save_daily_summary(date_str: str, total: int, unique: int,
                       busiest_hour: Optional[int], anomaly_count: int, report_text: str):
    """Upsert the daily summary record for date_str."""
    now = datetime.now(timezone.utc)
    with transaction() as conn:
        conn.execute(
            """INSERT INTO daily_summaries
               (date, total_aircraft, unique_aircraft, busiest_hour,
                anomaly_count, report_text, generated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
                 total_aircraft=excluded.total_aircraft,
                 unique_aircraft=excluded.unique_aircraft,
                 busiest_hour=excluded.busiest_hour,
                 anomaly_count=excluded.anomaly_count,
                 report_text=excluded.report_text,
                 generated_at=excluded.generated_at""",
            (date_str, total, unique, busiest_hour, anomaly_count, report_text, now.isoformat()),
        )


# ---------------------------------------------------------------------------
# Time windows
#
# The report covers the 24 hours before it runs, not the UTC calendar day. It
# runs at 10:00 local (15:00 UTC), so "today, UTC" was a 15-hour partial day
# compared against full-day averages, and 15:00-24:00 UTC never appeared in
# any report at all.
#
# Timestamps are stored as UTC isoformat strings with a +00:00 suffix, so
# comparing them as strings against other UTC isoformat values is a correct
# time comparison and can use the indexes.
# ---------------------------------------------------------------------------

def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).isoformat()


def get_window_flights(start: datetime, end: datetime) -> list:
    """Flight records with scan_time in [start, end)."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM flights WHERE scan_time >= ? AND scan_time < ?
               ORDER BY first_seen""",
            (_iso(start), _iso(end)),
        ).fetchall()
    return [dict(r) for r in rows]


def count_window_flights(start: datetime, end: datetime) -> int:
    """Number of flight records with scan_time in [start, end)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM flights WHERE scan_time >= ? AND scan_time < ?",
            (_iso(start), _iso(end)),
        ).fetchone()
    return row["n"]


def get_window_anomalies(start: datetime, end: datetime) -> list:
    """Anomaly records with detected_at in [start, end)."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM anomalies WHERE detected_at >= ? AND detected_at < ?
               ORDER BY detected_at""",
            (_iso(start), _iso(end)),
        ).fetchall()
    return [dict(r) for r in rows]


def get_window_busiest_hour(start: datetime, end: datetime) -> Optional[int]:
    """UTC hour (0-23) with the most flight contacts in [start, end), or None."""
    with get_conn() as conn:
        row = conn.execute(
            """SELECT strftime('%H', scan_time) AS hr, COUNT(*) AS cnt
               FROM flights WHERE scan_time >= ? AND scan_time < ?
               GROUP BY hr ORDER BY cnt DESC LIMIT 1""",
            (_iso(start), _iso(end)),
        ).fetchone()
    return int(row["hr"]) if row else None


def get_window_baseline(end: datetime, days: int = 7, hours: float = 24) -> dict:
    """Average flight count over the same window on each of the previous `days` days.

    For end = 10:00 today and hours = 24, that is 10:00-10:00 one day back,
    two days back, and so on. Windows with no flights at all are left out,
    as the calendar-day baseline did, so days the pipeline was down don't
    read as quiet days.

    Returns the same keys as get_rolling_baseline, so callers can swap.
    """
    length = timedelta(hours=hours)
    counts = {}
    for k in range(1, days + 1):
        w_end = end - timedelta(days=k)
        n = count_window_flights(w_end - length, w_end)
        if n:
            counts[(w_end - length).date().isoformat()] = n
    if not counts:
        return {"avg_daily": 0, "days_sampled": 0}
    return {
        "avg_daily": sum(counts.values()) / len(counts),
        "days_sampled": len(counts),
        "daily_counts": counts,
    }


# ---------------------------------------------------------------------------
# Outside context (see context.py)
# ---------------------------------------------------------------------------

def log_context_poll(source: str, ok: bool, value: Optional[float] = None,
                     when: Optional[datetime] = None) -> None:
    """Record one poll of an outside source, successful or not."""
    when = when or datetime.now(timezone.utc)
    with transaction() as conn:
        _ensure_context_schema(conn)
        conn.execute(
            "INSERT INTO context_polls (source, polled_at, ok, value) VALUES (?, ?, ?, ?)",
            (source, _iso(when), int(ok), value),
        )


def get_context_polls(source: str, start: datetime, end: datetime) -> list:
    """Polls of `source` in [start, end), oldest first."""
    with transaction() as conn:
        _ensure_context_schema(conn)
        rows = conn.execute(
            """SELECT polled_at, ok, value FROM context_polls
               WHERE source = ? AND polled_at >= ? AND polled_at < ?
               ORDER BY polled_at""",
            (source, _iso(start), _iso(end)),
        ).fetchall()
    return [dict(r) for r in rows]


def last_ok_context_poll(source: str) -> Optional[datetime]:
    """Time of the most recent successful poll of `source`, or None."""
    with transaction() as conn:
        _ensure_context_schema(conn)
        row = conn.execute(
            """SELECT MAX(polled_at) AS t FROM context_polls
               WHERE source = ? AND ok = 1""",
            (source,),
        ).fetchone()
    return datetime.fromisoformat(row["t"]) if row and row["t"] else None


def upsert_nas_events(events: list, when: Optional[datetime] = None) -> None:
    """Record FAA events seen in one poll: new ones inserted, known ones extended."""
    when = _iso(when or datetime.now(timezone.utc))
    with transaction() as conn:
        _ensure_context_schema(conn)
        for e in events:
            conn.execute(
                """INSERT INTO nas_events
                   (key, delay_type, airport, reason, details, first_seen, last_seen)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET
                     details = excluded.details, last_seen = excluded.last_seen""",
                (e["key"], e["delay_type"], e.get("airport"), e.get("reason"),
                 e.get("details"), when, when),
            )


def get_nas_events(start: datetime, end: datetime) -> list:
    """FAA events observed at any point in [start, end), earliest first."""
    with transaction() as conn:
        _ensure_context_schema(conn)
        rows = conn.execute(
            """SELECT * FROM nas_events
               WHERE first_seen < ? AND last_seen >= ?
               ORDER BY first_seen""",
            (_iso(end), _iso(start)),
        ).fetchall()
    return [dict(r) for r in rows]
