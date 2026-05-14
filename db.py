import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime, timedelta
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
    logger.info("Database initialized at %s", config.DB_PATH)


def log_aircraft(aircraft_list: list, session_id: str) -> int:
    """Insert or update aircraft records. Returns count of new flights logged."""
    now = datetime.utcnow()
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
    now = datetime.utcnow()
    with transaction() as conn:
        conn.execute(
            """INSERT INTO anomalies
               (icao_hex, callsign, anomaly_type, description, detected_at, altitude_ft, scan_time)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (icao_hex.upper(), callsign, anomaly_type, description,
             now.isoformat(), altitude_ft, now.isoformat()),
        )
    logger.info("Anomaly logged: [%s] %s — %s", anomaly_type, icao_hex, description)


def get_today_flights() -> list:
    """Return all flight records logged today (UTC)."""
    today = datetime.utcnow().date().isoformat()
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
    today = datetime.utcnow().date().isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM anomalies WHERE date(detected_at) = ? ORDER BY detected_at""",
            (today,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_rolling_baseline(days: int = 7) -> dict:
    """Returns average daily stats over the last N days (excluding today)."""
    today = datetime.utcnow().date()
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
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM flights WHERE callsign = ? AND scan_time >= ?
               ORDER BY scan_time DESC""",
            (callsign, cutoff),
        ).fetchall()
    return [dict(r) for r in rows]


def get_busiest_hour_today() -> Optional[int]:
    """Return the UTC hour (0-23) with the most flight contacts today, or None."""
    today = datetime.utcnow().date().isoformat()
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
    now = datetime.utcnow()
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
