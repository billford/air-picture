# pylint: disable=missing-function-docstring,missing-class-docstring,protected-access,too-many-arguments,too-many-positional-arguments
"""Tests for report formatting helpers."""

import unittest

import report


def _flight(icao_hex, callsign=None, altitude_ft=None, speed_kts=None,
            heading_deg=None, lat=None, lon=None):  # pylint: disable=too-many-arguments,too-many-positional-arguments
    return {
        "icao_hex": icao_hex,
        "callsign": callsign,
        "altitude_ft": altitude_ft,
        "speed_kts": speed_kts,
        "heading_deg": heading_deg,
        "lat": lat,
        "lon": lon,
    }


def _anomaly(icao_hex, callsign, anomaly_type, description):
    return {
        "icao_hex": icao_hex,
        "callsign": callsign,
        "anomaly_type": anomaly_type,
        "description": description,
    }


class TestFormatFlights(unittest.TestCase):
    def test_empty_returns_placeholder(self):
        result = report._format_flights([])
        self.assertEqual(result, "No flights logged today.")

    def test_single_flight_included(self):
        f = _flight("A12345", callsign="UAL1", altitude_ft=35000, speed_kts=450, heading_deg=270)
        result = report._format_flights([f])
        self.assertIn("UAL1", result)
        self.assertIn("A12345", result)
        self.assertIn("35,000 ft", result)
        self.assertIn("450 kts", result)
        self.assertIn("hdg 270", result)

    def test_no_callsign_shows_placeholder(self):
        f = _flight("A12345", callsign=None, altitude_ft=35000)
        result = report._format_flights([f])
        self.assertIn("(no callsign)", result)

    def test_no_altitude_shows_unknown(self):
        f = _flight("A12345", callsign="UAL1", altitude_ft=None)
        result = report._format_flights([f])
        self.assertIn("alt unknown", result)

    def test_coordinates_included_when_present(self):
        f = _flight("A12345", callsign="UAL1", altitude_ft=35000, lat=41.43, lon=-81.40)
        result = report._format_flights([f])
        self.assertIn("41.430", result)
        self.assertIn("-81.400", result)

    def test_duplicate_icao_deduplicated(self):
        f1 = _flight("A12345", callsign="UAL1", altitude_ft=35000)
        f2 = _flight("A12345", callsign="UAL1", altitude_ft=36000)
        result = report._format_flights([f1, f2])
        self.assertEqual(result.count("A12345"), 1)

    def test_multiple_distinct_flights(self):
        f1 = _flight("A11111", callsign="UAL1", altitude_ft=35000)
        f2 = _flight("A22222", callsign="DAL2", altitude_ft=32000)
        result = report._format_flights([f1, f2])
        self.assertIn("UAL1", result)
        self.assertIn("DAL2", result)

    def test_capped_at_80_entries(self):
        flights = [_flight(f"A{i:05d}", callsign=f"CS{i}", altitude_ft=35000) for i in range(100)]
        result = report._format_flights(flights)
        lines = [l for l in result.splitlines() if l.strip()]
        self.assertEqual(len(lines), 80)


class TestFormatAnomalies(unittest.TestCase):
    def test_empty_returns_placeholder(self):
        result = report._format_anomalies([])
        self.assertEqual(result, "No anomalies detected.")

    def test_anomaly_included(self):
        a = _anomaly("AE1234", "SWORD1", "military_hex", "Military aircraft detected.")
        result = report._format_anomalies([a])
        self.assertIn("MILITARY_HEX", result)
        self.assertIn("SWORD1", result)
        self.assertIn("AE1234", result)
        self.assertIn("Military aircraft detected.", result)

    def test_no_callsign_shows_placeholder(self):
        a = _anomaly("A12345", None, "no_callsign_high", "No callsign at cruise.")
        result = report._format_anomalies([a])
        self.assertIn("(no callsign)", result)

    def test_multiple_anomalies(self):
        anomalies = [
            _anomaly("AE1234", "SWORD1", "military_hex", "Military."),
            _anomaly("A12345", None, "no_callsign_high", "No callsign."),
        ]
        result = report._format_anomalies(anomalies)
        self.assertIn("MILITARY_HEX", result)
        self.assertIn("NO_CALLSIGN_HIGH", result)


class TestFormatBaseline(unittest.TestCase):
    def test_no_history(self):
        result = report._format_baseline({"avg_daily": 0, "days_sampled": 0}, 50)
        self.assertIn("Insufficient history", result)

    def test_above_average(self):
        result = report._format_baseline({"avg_daily": 50, "days_sampled": 7}, 75)
        self.assertIn("above", result)
        self.assertIn("50%", result)

    def test_below_average(self):
        result = report._format_baseline({"avg_daily": 100, "days_sampled": 7}, 50)
        self.assertIn("below", result)
        self.assertIn("50%", result)

    def test_at_average(self):
        result = report._format_baseline({"avg_daily": 50, "days_sampled": 7}, 50)
        self.assertIn("above", result)  # 0% above
        self.assertIn("0%", result)

    def test_includes_day_count(self):
        result = report._format_baseline({"avg_daily": 50, "days_sampled": 7}, 60)
        self.assertIn("7-day average", result)

    def test_includes_today_count(self):
        result = report._format_baseline({"avg_daily": 50, "days_sampled": 7}, 60)
        self.assertIn("Today: 60 aircraft", result)


if __name__ == "__main__":
    unittest.main()
