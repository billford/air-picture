# pylint: disable=missing-function-docstring,missing-class-docstring,protected-access
"""Tests for outside context (FAA status, national traffic), 24h windows, and scan merging."""

import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import agent
import context
import db
import report

NOW = datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)

FAA_XML = """<AIRPORT_STATUS_INFORMATION><Update_Time>Sat Nov 14 15:08:59 2026 GMT</Update_Time>
<Delay_type><Name>Ground Stop Programs</Name><Ground_Stop_List>
  <Program><ARPT>EWR</ARPT><Reason>equipment outage</Reason><End_Time>3:30 pm EST</End_Time></Program>
  <Program><ARPT>CLE</ARPT><Reason>equipment outage</Reason><End_Time>4:00 pm EST</End_Time></Program>
</Ground_Stop_List></Delay_type>
<Delay_type><Name>General Arrival/Departure Delay Info</Name><Arrival_Departure_Delay_List>
  <Delay><ARPT>ORD</ARPT><Reason>WX:Thunderstorms</Reason>
    <Arrival_Departure Type="Departure"><Min>31 minutes</Min><Max>45 minutes</Max><Trend>Increasing</Trend></Arrival_Departure>
  </Delay>
</Arrival_Departure_Delay_List></Delay_type>
<Delay_type><Name>Airport Closures</Name><Airport_Closure_List>
  <Airport><ARPT>LAX</ARPT><Reason>!LAX 05/277 LAX AD AP CLSD TO NON SKED TRANSIENT GA ACFT EXC 24HR PPR</Reason></Airport>
</Airport_Closure_List></Delay_type>
</AIRPORT_STATUS_INFORMATION>"""


def _ac(icao, callsign=None):
    return SimpleNamespace(icao_hex=icao, callsign=callsign, altitude_ft=30000,
                           speed_kts=450.0, heading_deg=90.0, lat=41.4, lon=-81.4)


class DbTestCase(unittest.TestCase):
    """conftest points DB_PATH at a fresh temp file; create the schema in it."""

    def setUp(self):
        db.init_db()

    def _flight_at(self, icao, when):
        with db.transaction() as conn:
            conn.execute(
                """INSERT INTO flights (icao_hex, callsign, altitude_ft, speed_kts,
                   heading_deg, lat, lon, scan_time, first_seen, last_seen, session_id)
                   VALUES (?, NULL, NULL, NULL, NULL, NULL, NULL, ?, ?, ?, 's')""",
                (icao, when.isoformat(), when.isoformat(), when.isoformat()),
            )


class TestParseNasStatus(unittest.TestCase):
    def test_parses_each_type_and_skips_routine_closures(self):
        events = context.parse_nas_status(FAA_XML)
        by_airport = {e["airport"]: e for e in events}
        self.assertEqual(set(by_airport), {"EWR", "CLE", "ORD"})
        self.assertEqual(by_airport["EWR"]["delay_type"], "Ground Stop Programs")
        details = json.loads(by_airport["ORD"]["details"])
        self.assertEqual(details["Max"], "45 minutes")
        self.assertEqual(details["Arrival_Departure_Type"], "Departure")

    def test_key_is_stable_across_polls(self):
        first = {e["airport"]: e["key"] for e in context.parse_nas_status(FAA_XML)}
        again = {e["airport"]: e["key"] for e in context.parse_nas_status(FAA_XML)}
        self.assertEqual(first, again)

    def test_empty_feed(self):
        xml = "<AIRPORT_STATUS_INFORMATION><Update_Time>x</Update_Time></AIRPORT_STATUS_INFORMATION>"
        self.assertEqual(context.parse_nas_status(xml), [])


class TestCollect(DbTestCase):
    @patch("context.opensky.count_airborne", return_value=4200)
    @patch("context.fetch_nas_status")
    def test_records_events_and_national(self, mock_faa, _mock_count):
        mock_faa.return_value = context.parse_nas_status(FAA_XML)
        context.collect(NOW)
        self.assertEqual(len(db.get_nas_events(NOW - timedelta(hours=1), NOW + timedelta(hours=1))), 3)
        polls = db.get_context_polls(context.NATIONAL_SOURCE, NOW - timedelta(hours=1), NOW + timedelta(hours=1))
        self.assertEqual([p["value"] for p in polls], [4200])

    @patch("context.opensky.count_airborne", return_value=4200)
    @patch("context.fetch_nas_status", return_value=[])
    def test_national_throttled_to_hourly(self, _mock_faa, mock_count):
        context.collect(NOW)
        context.collect(NOW + timedelta(minutes=15))
        context.collect(NOW + timedelta(minutes=60))
        self.assertEqual(mock_count.call_count, 2)

    @patch("context.opensky.count_airborne", side_effect=RuntimeError("boom"))
    @patch("context.fetch_nas_status", side_effect=RuntimeError("boom"))
    def test_never_raises(self, _mock_faa, _mock_count):
        context.collect(NOW)

    @patch("context.opensky.count_airborne", return_value=None)
    @patch("context.fetch_nas_status", return_value=None)
    def test_failures_recorded_not_mistaken_for_zero(self, _mock_faa, _mock_count):
        context.collect(NOW)
        text = context.summarize_nas(NOW - timedelta(hours=1), NOW + timedelta(hours=1))
        self.assertIn("could not be reached", text)
        self.assertIn("No national traffic samples",
                      context.summarize_national(NOW - timedelta(hours=1), NOW + timedelta(hours=1)))


class TestSummaries(DbTestCase):
    def test_nas_events_listed_with_type(self):
        db.log_context_poll(context.FAA_SOURCE, True, 3, when=NOW - timedelta(hours=2))
        db.upsert_nas_events(context.parse_nas_status(FAA_XML), when=NOW - timedelta(hours=2))
        text = context.summarize_nas(NOW - timedelta(hours=24), NOW)
        self.assertIn("Ground Stop Programs (2)", text)
        self.assertIn("EWR: equipment outage", text)

    def test_no_events_says_so(self):
        db.log_context_poll(context.FAA_SOURCE, True, 0, when=NOW - timedelta(hours=2))
        self.assertIn("No ground stops", context.summarize_nas(NOW - timedelta(hours=24), NOW))

    def test_events_outside_window_excluded(self):
        db.log_context_poll(context.FAA_SOURCE, True, 3, when=NOW - timedelta(hours=2))
        db.upsert_nas_events(context.parse_nas_status(FAA_XML), when=NOW - timedelta(days=3))
        self.assertIn("No ground stops", context.summarize_nas(NOW - timedelta(hours=24), NOW))

    def test_national_compares_same_hours(self):
        for k in range(1, 4):
            db.log_context_poll(context.NATIONAL_SOURCE, True, 5000, when=NOW - timedelta(days=k, hours=3))
        db.log_context_poll(context.NATIONAL_SOURCE, True, 1000, when=NOW - timedelta(hours=3))
        text = context.summarize_national(NOW - timedelta(hours=24), NOW)
        self.assertIn("80% below normal", text)

    def test_national_short_history(self):
        db.log_context_poll(context.NATIONAL_SOURCE, True, 5000, when=NOW - timedelta(hours=3))
        self.assertIn("Too little history", context.summarize_national(NOW - timedelta(hours=24), NOW))


class TestWindowBaseline(DbTestCase):
    def test_compares_same_24_hours(self):
        # 3 flights in each of the previous 3 windows, plus one just outside each.
        for k in range(1, 4):
            for m in range(3):
                self._flight_at(f"A{k}{m}", NOW - timedelta(days=k, hours=1 + m))
            self._flight_at(f"B{k}", NOW - timedelta(days=k) + timedelta(minutes=5))
        base = db.get_window_baseline(NOW - timedelta(days=0), days=7)
        # Window k ends at NOW-k days; the "+5 min" flight of day k falls in
        # window k-1 instead, so windows 1 and 2 gain one each.
        self.assertEqual(base["days_sampled"], 3)
        self.assertAlmostEqual(base["avg_daily"], (4 + 4 + 3) / 3)

    def test_window_flights_half_open(self):
        self._flight_at("C1", NOW - timedelta(hours=24))
        self._flight_at("C2", NOW)
        got = [f["icao_hex"] for f in db.get_window_flights(NOW - timedelta(hours=24), NOW)]
        self.assertEqual(got, ["C1"])


class TestReportWindow(unittest.TestCase):
    def test_today_is_last_24_hours(self):
        start, end = report.report_window(None, now=NOW)
        self.assertEqual((start, end), (NOW - timedelta(hours=24), NOW))

    def test_past_date_is_calendar_day(self):
        start, end = report.report_window("2026-11-10", now=NOW)
        self.assertEqual(start, datetime(2026, 11, 10, tzinfo=timezone.utc))
        self.assertEqual(end - start, timedelta(days=1))


class TestDedupeAnomalies(unittest.TestCase):
    def test_repeats_collapsed_to_latest(self):
        rows = [
            {"anomaly_type": "no_callsign_high", "icao_hex": "AC1", "callsign": "DAL1", "description": "old"},
            {"anomaly_type": "no_callsign_high", "icao_hex": "AC1", "callsign": "DAL1", "description": "new"},
            {"anomaly_type": "low_altitude", "icao_hex": "A1", "callsign": "FDX361", "description": "low"},
        ]
        text = report._format_anomalies(rows)
        self.assertEqual(text.count("DAL1"), 1)
        self.assertIn("new", text)
        self.assertNotIn("old", text)


    def test_missing_regulars_summarised_by_operator(self):
        rows = [{"anomaly_type": "missing_regular", "icao_hex": "N/A", "callsign": cs,
                 "description": f"{cs} absent"} for cs in ("DAL1", "DAL2", "UAL3")]
        text = report._format_anomalies(rows)
        self.assertEqual(text.count("\n"), 0)
        self.assertIn("3 regular flights absent", text)
        self.assertIn("DAL 2", text)


class TestScanCollection(unittest.TestCase):
    def test_polls_throughout_scan(self):
        # The receiver forgets aircraft after 60s; reading only at the end
        # would keep just the last batch.
        batches = iter([[_ac("AAA")], [_ac("BBB")], [], [_ac("aaa", "UAL1")]])
        monitor = SimpleNamespace(get_aircraft=lambda: next(batches))
        t = [0.0]

        def clock():
            return t[0]

        def sleep(s):
            t[0] += s

        heard = agent._collect_sdr(monitor, 60, sleep=sleep, clock=clock)
        self.assertEqual(set(heard), {"AAA", "BBB"})
        self.assertEqual(heard["AAA"].callsign, "UAL1")  # latest read wins

    def test_merge_unions_and_prefers_receiver(self):
        sdr = {"AAA": _ac("AAA", "FROM_SDR")}
        osky = [_ac("aaa", "FROM_OSKY"), _ac("CCC")]
        merged = {a.icao_hex.upper(): a for a in agent._merge_sources(sdr, osky)}
        self.assertEqual(set(merged), {"AAA", "CCC"})
        self.assertEqual(merged["AAA"].callsign, "FROM_SDR")

    def test_merge_with_no_receiver(self):
        self.assertEqual(len(agent._merge_sources({}, [_ac("X"), _ac("Y")])), 2)


if __name__ == "__main__":
    unittest.main()
