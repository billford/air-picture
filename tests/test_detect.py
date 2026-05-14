"""Tests for anomaly detection logic."""

import types
import unittest
from unittest.mock import patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import detect


def _aircraft(icao_hex, callsign=None, altitude_ft=None, speed_kts=None, heading_deg=None):
    ac = types.SimpleNamespace(
        icao_hex=icao_hex,
        callsign=callsign,
        altitude_ft=altitude_ft,
        speed_kts=speed_kts,
        heading_deg=heading_deg,
        lat=None,
        lon=None,
    )
    return ac


class TestHexInRange(unittest.TestCase):
    def test_within_range(self):
        self.assertTrue(detect._hex_in_range("AE1234", "AE0000", "AEFFFF"))

    def test_at_lower_bound(self):
        self.assertTrue(detect._hex_in_range("AE0000", "AE0000", "AEFFFF"))

    def test_at_upper_bound(self):
        self.assertTrue(detect._hex_in_range("AEFFFF", "AE0000", "AEFFFF"))

    def test_below_range(self):
        self.assertFalse(detect._hex_in_range("AD9999", "AE0000", "AEFFFF"))

    def test_above_range(self):
        self.assertFalse(detect._hex_in_range("AF0000", "AE0000", "AEFFFF"))

    def test_invalid_hex(self):
        self.assertFalse(detect._hex_in_range("ZZZZZZ", "AE0000", "AEFFFF"))


class TestClassifyHex(unittest.TestCase):
    def test_military(self):
        result = detect.classify_hex("AE1234")
        self.assertEqual(result["type"], "military")
        self.assertEqual(result["country"], "US Military")

    def test_us_civil(self):
        result = detect.classify_hex("A12345")
        self.assertEqual(result["type"], "us_civil")

    def test_foreign_canada(self):
        result = detect.classify_hex("C01234")
        self.assertEqual(result["type"], "foreign")
        self.assertEqual(result["country"], "Canada")

    def test_foreign_uk(self):
        result = detect.classify_hex("401234")
        self.assertEqual(result["type"], "foreign")
        self.assertEqual(result["country"], "United Kingdom")

    def test_unknown(self):
        result = detect.classify_hex("000001")
        self.assertEqual(result["type"], "unknown")

    def test_lowercase_input(self):
        result = detect.classify_hex("ae1234")
        self.assertEqual(result["type"], "military")


class TestIsInterestingCallsign(unittest.TestCase):
    def test_military_prefix(self):
        self.assertTrue(detect._is_interesting_callsign("AF123"))
        self.assertTrue(detect._is_interesting_callsign("SAM01"))
        self.assertTrue(detect._is_interesting_callsign("EXEC1"))

    def test_commercial_not_interesting(self):
        self.assertFalse(detect._is_interesting_callsign("UAL123"))
        self.assertFalse(detect._is_interesting_callsign("DAL456"))

    def test_lowercase_input(self):
        self.assertTrue(detect._is_interesting_callsign("af1"))


class TestRunAnomalyDetection(unittest.TestCase):
    def setUp(self):
        self.log_patcher = patch("detect.db.log_anomaly")
        self.mock_log = self.log_patcher.start()

    def tearDown(self):
        self.log_patcher.stop()

    def test_very_high_altitude(self):
        ac = _aircraft("A12345", callsign="UAL1", altitude_ft=50000)
        result = detect.run_anomaly_detection([ac])
        types_ = [r["type"] for r in result]
        self.assertIn("very_high_altitude", types_)

    def test_low_and_fast(self):
        ac = _aircraft("A12345", callsign="UAL1", altitude_ft=1000, speed_kts=350)
        result = detect.run_anomaly_detection([ac])
        types_ = [r["type"] for r in result]
        self.assertIn("low_and_fast", types_)

    def test_no_callsign_high(self):
        ac = _aircraft("A12345", callsign=None, altitude_ft=30000)
        result = detect.run_anomaly_detection([ac])
        types_ = [r["type"] for r in result]
        self.assertIn("no_callsign_high", types_)

    def test_military_hex(self):
        ac = _aircraft("AE1234", callsign="SWORD1", altitude_ft=20000)
        result = detect.run_anomaly_detection([ac])
        types_ = [r["type"] for r in result]
        self.assertIn("military_hex", types_)
        self.assertIn("interesting_callsign", types_)

    def test_foreign_registration(self):
        ac = _aircraft("C01234", callsign="ACA100", altitude_ft=35000)
        result = detect.run_anomaly_detection([ac])
        types_ = [r["type"] for r in result]
        self.assertIn("foreign_registration", types_)

    def test_unknown_hex(self):
        ac = _aircraft("000001", callsign=None, altitude_ft=10000)
        result = detect.run_anomaly_detection([ac])
        types_ = [r["type"] for r in result]
        self.assertIn("unknown_hex", types_)

    def test_normal_commercial_no_anomaly(self):
        ac = _aircraft("A12345", callsign="UAL123", altitude_ft=35000, speed_kts=450)
        result = detect.run_anomaly_detection([ac])
        types_ = [r["type"] for r in result]
        self.assertNotIn("very_high_altitude", types_)
        self.assertNotIn("low_and_fast", types_)
        self.assertNotIn("no_callsign_high", types_)

    def test_empty_list(self):
        result = detect.run_anomaly_detection([])
        self.assertEqual(result, [])

    def test_anomaly_dict_shape(self):
        ac = _aircraft("AE0001", callsign=None, altitude_ft=50000)
        result = detect.run_anomaly_detection([ac])
        for r in result:
            self.assertIn("icao_hex", r)
            self.assertIn("callsign", r)
            self.assertIn("type", r)
            self.assertIn("description", r)


class TestCheckTrafficDeviation(unittest.TestCase):
    @patch("detect.db.get_today_flights", return_value=[{}] * 100)
    @patch("detect.db.log_anomaly")
    def test_high_deviation_flagged(self, _mock_log, _mock_flights):
        baseline = {"avg_daily": 50, "days_sampled": 7}
        result = detect.check_traffic_deviation(baseline)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "traffic_deviation")

    @patch("detect.db.get_today_flights", return_value=[{}] * 52)
    @patch("detect.db.log_anomaly")
    def test_within_threshold_no_flag(self, _mock_log, _mock_flights):
        baseline = {"avg_daily": 50, "days_sampled": 7}
        result = detect.check_traffic_deviation(baseline)
        self.assertEqual(result, [])

    @patch("detect.db.get_today_flights", return_value=[])
    def test_no_baseline_returns_empty(self, _mock_flights):
        result = detect.check_traffic_deviation({"avg_daily": 0, "days_sampled": 0})
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
