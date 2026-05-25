# pylint: disable=missing-function-docstring,missing-class-docstring,protected-access
"""Tests for dashboard.py helper functions and HTML builders."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dashboard


class TestBadgeClass(unittest.TestCase):
    def test_military_returns_danger(self):
        self.assertEqual(dashboard._badge_class("military_hex"), "badge-danger")

    def test_restricted_returns_danger(self):
        self.assertEqual(dashboard._badge_class("restricted_zone"), "badge-danger")

    def test_low_returns_warn(self):
        self.assertEqual(dashboard._badge_class("low_and_fast"), "badge-warn")

    def test_unusual_returns_warn(self):
        self.assertEqual(dashboard._badge_class("unusual_flight"), "badge-warn")

    def test_default_returns_info(self):
        self.assertEqual(dashboard._badge_class("unknown_hex"), "badge-info")
        self.assertEqual(dashboard._badge_class("foreign_registration"), "badge-info")
        self.assertEqual(dashboard._badge_class("missing_regular"), "badge-info")


class TestInterpolateColors(unittest.TestCase):
    def test_empty_returns_empty(self):
        self.assertEqual(dashboard._interpolate_colors([]), [])

    def test_single_value(self):
        result = dashboard._interpolate_colors([42])
        self.assertEqual(len(result), 1)
        self.assertRegex(result[0], r"^rgb\(\d+,\d+,\d+\)")

    def test_length_matches_input(self):
        counts = [10, 20, 30, 40, 50]
        self.assertEqual(len(dashboard._interpolate_colors(counts)), 5)

    def test_all_same_value(self):
        result = dashboard._interpolate_colors([100, 100, 100])
        self.assertEqual(len(set(result)), 1)

    def test_returns_rgb_strings(self):
        for color in dashboard._interpolate_colors([0, 50, 100]):
            self.assertRegex(color, r"^rgb\(\d+,\d+,\d+\)$")


class TestFmtDate(unittest.TestCase):
    def test_iso_date_only(self):
        self.assertEqual(dashboard._fmt_date("2026-05-25"), "May 25")

    def test_iso_datetime(self):
        result = dashboard._fmt_date("2026-05-25T14:05:07+00:00")
        self.assertEqual(result, "May 25")

    def test_invalid_falls_back_to_slice(self):
        result = dashboard._fmt_date("2026-05-25-garbage")
        self.assertEqual(result, "2026-05-25")

    def test_none_like_input(self):
        result = dashboard._fmt_date("")
        self.assertIsInstance(result, str)


class TestFmtDateOnly(unittest.TestCase):
    def test_returns_first_ten_chars(self):
        self.assertEqual(dashboard._fmt_date_only("2026-05-25T14:00:00"), "2026-05-25")

    def test_date_only_string(self):
        self.assertEqual(dashboard._fmt_date_only("2026-05-25"), "2026-05-25")

    def test_none_returns_dash(self):
        self.assertEqual(dashboard._fmt_date_only(None), "—")


class TestFmtAlt(unittest.TestCase):
    def test_none_returns_dash(self):
        self.assertEqual(dashboard._fmt_alt(None), "—")

    def test_integer(self):
        self.assertEqual(dashboard._fmt_alt(35000), "35,000 ft")

    def test_float_truncated(self):
        self.assertEqual(dashboard._fmt_alt(35000.9), "35,000 ft")

    def test_zero(self):
        self.assertEqual(dashboard._fmt_alt(0), "0 ft")

    def test_non_numeric_returns_dash(self):
        self.assertEqual(dashboard._fmt_alt("bad"), "—")


class TestLoadNotableEvents(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        with patch.object(dashboard, "NOTABLE_EVENTS_PATH", Path("/nonexistent/path.json")):
            self.assertEqual(dashboard.load_notable_events(), [])

    def test_valid_json_loaded(self):
        events = [{"date": "2026-05-25", "event": "Test", "callsign": "TST1"}]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(events, f)
            tmp_path = Path(f.name)
        try:
            with patch.object(dashboard, "NOTABLE_EVENTS_PATH", tmp_path):
                result = dashboard.load_notable_events()
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["callsign"], "TST1")
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_sorted_newest_first(self):
        events = [
            {"date": "2026-05-01", "event": "A"},
            {"date": "2026-05-25", "event": "B"},
            {"date": "2026-05-10", "event": "C"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(events, f)
            tmp_path = Path(f.name)
        try:
            with patch.object(dashboard, "NOTABLE_EVENTS_PATH", tmp_path):
                result = dashboard.load_notable_events()
            self.assertEqual(result[0]["date"], "2026-05-25")
            self.assertEqual(result[-1]["date"], "2026-05-01")
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_malformed_json_returns_empty(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not json {{{")
            tmp_path = Path(f.name)
        try:
            with patch.object(dashboard, "NOTABLE_EVENTS_PATH", tmp_path):
                self.assertEqual(dashboard.load_notable_events(), [])
        finally:
            tmp_path.unlink(missing_ok=True)


class TestBuildStatsBar(unittest.TestCase):
    def _stats(self, **kwargs):
        base = {
            "total_flights": 1000,
            "unique_aircraft": 200,
            "anomaly_count": 50,
            "busiest_date": "2026-05-21",
            "busiest_count": 6851,
        }
        base.update(kwargs)
        return base

    def test_renders_all_tiles(self):
        html = dashboard.build_stats_bar(self._stats())
        self.assertIn("1,000", html)
        self.assertIn("200", html)
        self.assertIn("50", html)
        self.assertIn("6,851", html)

    def test_no_busiest_date_shows_dash(self):
        html = dashboard.build_stats_bar(self._stats(busiest_date=None, busiest_count=0))
        self.assertIn("—", html)

    def test_danger_class_when_high_anomaly_rate(self):
        # >500/day average triggers danger
        html = dashboard.build_stats_bar(self._stats(anomaly_count=99999))
        self.assertIn("danger", html)

    def test_no_danger_class_when_normal(self):
        html = dashboard.build_stats_bar(self._stats(anomaly_count=10))
        self.assertNotIn("stat-value danger", html)


class TestBuildNotableSection(unittest.TestCase):
    def test_empty_list_returns_empty_string(self):
        self.assertEqual(dashboard.build_notable_section([]), "")

    def test_event_name_rendered(self):
        events = [{"date": "2026-05-25", "event": "Memorial Day Flyover",
                   "callsign": "PITT24", "icao_hex": "AE07DB",
                   "altitude_ft": 3800, "speed_kts": 251, "heading_deg": 92,
                   "time_local": "10:05 AM EDT",
                   "notes": "Pennsylvania ANG F-16."}]
        html = dashboard.build_notable_section(events)
        self.assertIn("Memorial Day Flyover", html)
        self.assertIn("PITT24", html)
        self.assertIn("AE07DB", html)
        self.assertIn("3,800 ft", html)

    def test_missing_optional_fields_do_not_crash(self):
        events = [{"date": "2026-05-25", "event": "Sparse entry"}]
        html = dashboard.build_notable_section(events)
        self.assertIn("Sparse entry", html)

    def test_xss_escaped(self):
        events = [{"date": "2026-05-25", "event": "<script>alert(1)</script>",
                   "callsign": "TST", "notes": ""}]
        html = dashboard.build_notable_section(events)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)


class TestAnomalyDescriptions(unittest.TestCase):
    def test_all_known_types_have_descriptions(self):
        known = [
            "military_hex", "interesting_callsign", "low_and_fast",
            "very_high_altitude", "no_callsign_high", "foreign_registration",
            "unknown_hex", "traffic_deviation", "missing_regular",
        ]
        for t in known:
            self.assertIn(t, dashboard._ANOMALY_DESCRIPTIONS)
            self.assertTrue(len(dashboard._ANOMALY_DESCRIPTIONS[t]) > 10)


if __name__ == "__main__":
    unittest.main()
