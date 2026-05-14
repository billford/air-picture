"""Tests for database operations using a temporary in-memory DB."""

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import config


def _make_aircraft(icao_hex, callsign=None, altitude_ft=None, speed_kts=None,
                   heading_deg=None, lat=None, lon=None):
    import types
    return types.SimpleNamespace(
        icao_hex=icao_hex, callsign=callsign, altitude_ft=altitude_ft,
        speed_kts=speed_kts, heading_deg=heading_deg, lat=lat, lon=lon,
    )


class TestDb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_patcher = patch.object(config, "DB_PATH", self.tmp.name)
        self.db_patcher.start()
        db.init_db()

    def tearDown(self):
        self.db_patcher.stop()
        Path(self.tmp.name).unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # init_db
    # ------------------------------------------------------------------

    def test_tables_created(self):
        conn = db.get_conn()
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        self.assertIn("flights", tables)
        self.assertIn("anomalies", tables)
        self.assertIn("daily_summaries", tables)

    # ------------------------------------------------------------------
    # log_aircraft
    # ------------------------------------------------------------------

    def test_log_aircraft_inserts_new(self):
        ac = _make_aircraft("A12345", callsign="UAL1", altitude_ft=35000, speed_kts=450)
        count = db.log_aircraft([ac], "sess1")
        self.assertEqual(count, 1)
        flights = db.get_today_flights()
        self.assertEqual(len(flights), 1)
        self.assertEqual(flights[0]["icao_hex"], "A12345")

    def test_log_aircraft_merges_duplicate(self):
        ac = _make_aircraft("A12345", callsign="UAL1", altitude_ft=35000)
        db.log_aircraft([ac], "sess1")
        count = db.log_aircraft([ac], "sess2")
        self.assertEqual(count, 0)
        self.assertEqual(len(db.get_today_flights()), 1)

    def test_log_aircraft_icao_uppercased(self):
        ac = _make_aircraft("a12345", callsign="UAL1")
        db.log_aircraft([ac], "sess1")
        flights = db.get_today_flights()
        self.assertEqual(flights[0]["icao_hex"], "A12345")

    def test_log_aircraft_multiple_distinct(self):
        ac1 = _make_aircraft("A11111", callsign="UAL1")
        ac2 = _make_aircraft("A22222", callsign="DAL2")
        count = db.log_aircraft([ac1, ac2], "sess1")
        self.assertEqual(count, 2)

    # ------------------------------------------------------------------
    # log_anomaly / get_today_anomalies
    # ------------------------------------------------------------------

    def test_log_anomaly_stored_and_retrieved(self):
        db.log_anomaly("AE1234", "SWORD1", "military_hex", "Test anomaly", 30000)
        anomalies = db.get_today_anomalies()
        self.assertEqual(len(anomalies), 1)
        self.assertEqual(anomalies[0]["icao_hex"], "AE1234")
        self.assertEqual(anomalies[0]["anomaly_type"], "military_hex")

    def test_log_anomaly_icao_uppercased(self):
        db.log_anomaly("ae1234", None, "test", "desc")
        anomaly = db.get_today_anomalies()[0]
        self.assertEqual(anomaly["icao_hex"], "AE1234")

    # ------------------------------------------------------------------
    # get_date_flights
    # ------------------------------------------------------------------

    def test_get_date_flights_filters_by_date(self):
        ac = _make_aircraft("A12345", callsign="UAL1")
        db.log_aircraft([ac], "sess1")
        today = datetime.utcnow().date().isoformat()
        flights = db.get_date_flights(today)
        self.assertEqual(len(flights), 1)
        flights_other = db.get_date_flights("2000-01-01")
        self.assertEqual(len(flights_other), 0)

    # ------------------------------------------------------------------
    # get_rolling_baseline
    # ------------------------------------------------------------------

    def test_baseline_empty_db(self):
        result = db.get_rolling_baseline(7)
        self.assertEqual(result["days_sampled"], 0)
        self.assertEqual(result["avg_daily"], 0)

    # ------------------------------------------------------------------
    # get_busiest_hour_today
    # ------------------------------------------------------------------

    def test_busiest_hour_no_flights(self):
        self.assertIsNone(db.get_busiest_hour_today())

    def test_busiest_hour_with_flights(self):
        ac = _make_aircraft("A12345", callsign="UAL1")
        db.log_aircraft([ac], "sess1")
        result = db.get_busiest_hour_today()
        self.assertIsInstance(result, int)
        self.assertGreaterEqual(result, 0)
        self.assertLessEqual(result, 23)

    # ------------------------------------------------------------------
    # save_daily_summary
    # ------------------------------------------------------------------

    def test_save_daily_summary_upserts(self):
        db.save_daily_summary("2026-05-14", 100, 80, 14, 3, "REPORT TEXT")
        db.save_daily_summary("2026-05-14", 110, 90, 15, 4, "UPDATED REPORT")
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT * FROM daily_summaries WHERE date = '2026-05-14'"
        ).fetchall()
        conn.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["total_aircraft"], 110)
        self.assertEqual(rows[0]["report_text"], "UPDATED REPORT")

    def test_save_daily_summary_persists_fields(self):
        db.save_daily_summary("2026-05-14", 50, 40, 10, 2, "DAILY REPORT")
        conn = db.get_conn()
        row = conn.execute(
            "SELECT * FROM daily_summaries WHERE date = '2026-05-14'"
        ).fetchone()
        conn.close()
        self.assertEqual(row["unique_aircraft"], 40)
        self.assertEqual(row["busiest_hour"], 10)
        self.assertEqual(row["anomaly_count"], 2)


if __name__ == "__main__":
    unittest.main()
