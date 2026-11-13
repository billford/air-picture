# pylint: disable=missing-function-docstring,missing-class-docstring,protected-access
"""Tests for pipeline alerting — mostly about how often it stays quiet."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import alerts


class AlertTestCase(unittest.TestCase):
    """Gives each test a private state file so throttling can't leak between them."""

    def setUp(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())  # pylint: disable=consider-using-with
        state_path = str(Path(tmp) / "alert_state.json")

        patcher = patch.object(alerts.config, "ALERT_STATE_FILE", state_path)
        patcher.start()
        self.addCleanup(patcher.stop)

        topic = patch.object(alerts.config, "NTFY_TOPIC", "test-topic")
        topic.start()
        self.addCleanup(topic.stop)

        repeat = patch.object(alerts.config, "ALERT_REPEAT_HOURS", 6)
        repeat.start()
        self.addCleanup(repeat.stop)

        # Otherwise the suite posts real desktop notifications.
        mac = patch("alerts._mac_notification")
        self.mock_mac = mac.start()
        self.addCleanup(mac.stop)

        self.state_path = Path(state_path)


class TestNotifyFailure(AlertTestCase):
    @patch("alerts.deliver.ntfy_post", return_value=True)
    def test_first_failure_notifies(self, mock_post):
        self.assertTrue(alerts.notify_failure("site deploy", "exit 127"))
        mock_post.assert_called_once()
        self.assertIn("FAILED", mock_post.call_args[0][0])

    @patch("alerts.deliver.ntfy_post", return_value=True)
    def test_repeat_failure_is_throttled(self, mock_post):
        alerts.notify_failure("site deploy", "exit 127")
        mock_post.reset_mock()
        # The scenario this exists for: 96 failing runs in a day.
        for _ in range(96):
            self.assertFalse(alerts.notify_failure("site deploy", "exit 127"))
        mock_post.assert_not_called()

    @patch("alerts.deliver.ntfy_post", return_value=True)
    def test_repeat_notifies_again_after_interval(self, mock_post):
        alerts.notify_failure("site deploy", "exit 127")
        mock_post.reset_mock()

        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        state["site deploy"]["last_notified"] -= 7 * 3600  # older than the 6h window
        self.state_path.write_text(json.dumps(state), encoding="utf-8")

        self.assertTrue(alerts.notify_failure("site deploy", "exit 127"))
        self.assertIn("still failing", mock_post.call_args[0][0])

    @patch("alerts.deliver.ntfy_post", return_value=True)
    def test_failure_counts_accumulate_while_quiet(self, _mock_post):
        for _ in range(5):
            alerts.notify_failure("site deploy", "exit 127")
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["site deploy"]["count"], 5)

    @patch("alerts.deliver.ntfy_post", return_value=True)
    def test_components_do_not_suppress_each_other(self, mock_post):
        self.assertTrue(alerts.notify_failure("site deploy", "exit 127"))
        self.assertTrue(alerts.notify_failure("sdr", "no device"))
        self.assertEqual(mock_post.call_count, 2)

    @patch.object(alerts.config, "NTFY_TOPIC", "")
    @patch("deliver.http_post")
    def test_no_topic_sends_nothing(self, mock_http):
        # Not mocking ntfy_post here: the topic gate lives inside it, so this
        # goes through the real function and asserts nothing hits the network.
        self.assertFalse(alerts.notify_failure("site deploy", "exit 127"))
        mock_http.assert_not_called()

    @patch("alerts.deliver.ntfy_post", return_value=True)
    def test_corrupt_state_still_alerts(self, mock_post):
        self.state_path.write_text("{not json", encoding="utf-8")
        self.assertTrue(alerts.notify_failure("site deploy", "exit 127"))
        mock_post.assert_called_once()


class TestNotifyRecovery(AlertTestCase):
    @patch("alerts.deliver.ntfy_post", return_value=True)
    def test_recovery_is_silent_when_not_failing(self, mock_post):
        # The common case by far: every healthy run calls this.
        self.assertFalse(alerts.notify_recovery("site deploy"))
        mock_post.assert_not_called()

    @patch("alerts.deliver.ntfy_post", return_value=True)
    def test_recovery_notifies_after_failure(self, mock_post):
        alerts.notify_failure("site deploy", "exit 127")
        mock_post.reset_mock()
        self.assertTrue(alerts.notify_recovery("site deploy"))
        self.assertIn("recovered", mock_post.call_args[0][0])

    @patch("alerts.deliver.ntfy_post", return_value=True)
    def test_recovery_clears_state_so_it_only_fires_once(self, mock_post):
        alerts.notify_failure("site deploy", "exit 127")
        alerts.notify_recovery("site deploy")
        mock_post.reset_mock()
        self.assertFalse(alerts.notify_recovery("site deploy"))
        mock_post.assert_not_called()

    @patch("alerts.deliver.ntfy_post", return_value=True)
    def test_recovery_after_clearing_alerts_fresh(self, mock_post):
        alerts.notify_failure("site deploy", "exit 127")
        alerts.notify_recovery("site deploy")
        mock_post.reset_mock()
        # A new outage is news again, not a throttled repeat.
        self.assertTrue(alerts.notify_failure("site deploy", "exit 127"))
        self.assertIn("FAILED", mock_post.call_args[0][0])


class TestLocalFallback(AlertTestCase):
    @patch.object(alerts.config, "NTFY_TOPIC", "")
    @patch("deliver.http_post")
    def test_local_notification_fires_even_with_no_ntfy(self, mock_http):
        # The Tailscale-is-down case: ntfy cannot deliver, but the alert must
        # still reach the machine it happened on.
        alerts.notify_failure("site deploy", "exit 127")
        mock_http.assert_not_called()
        self.mock_mac.assert_called_once()

    @patch("alerts.deliver.ntfy_post", return_value=True)
    def test_local_notification_carries_the_detail(self, _mock_post):
        alerts.notify_failure("site deploy", "exit 127")
        title, message = self.mock_mac.call_args[0]
        self.assertIn("site deploy", title)
        self.assertIn("exit 127", message)


class TestEscapeApplescript(unittest.TestCase):
    def test_escapes_quotes_and_newlines(self):
        out = alerts._escape_applescript('say "hi"\nagain')
        self.assertNotIn("\n", out)
        self.assertIn('\\"hi\\"', out)

    def test_escapes_backslashes_first(self):
        self.assertEqual(alerts._escape_applescript("a\\b"), "a\\\\b")


class TestHumanise(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(alerts._humanise(30), "30s")
        self.assertEqual(alerts._humanise(45 * 60), "45m")
        self.assertEqual(alerts._humanise(3 * 3600), "3h")
        self.assertEqual(alerts._humanise(3 * 3600 + 20 * 60), "3h 20m")


class TestMain(AlertTestCase):
    @patch("alerts.deliver.ntfy_post", return_value=True)
    def test_cli_failure(self, mock_post):
        self.assertEqual(alerts.main(["failure", "site deploy", "exit 127"]), 0)
        mock_post.assert_called_once()

    @patch("alerts.deliver.ntfy_post", return_value=True)
    def test_cli_recovery_is_quiet_when_healthy(self, mock_post):
        self.assertEqual(alerts.main(["recovery", "site deploy"]), 0)
        mock_post.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class TestReportChannels(unittest.TestCase):
    @patch("alerts.notify_recovery")
    @patch("alerts.notify_failure")
    def test_failure_alerts_and_success_recovers(self, mock_fail, mock_recover):
        alerts.report_channels({"ntfy": False, "email": True}, "/tmp/r.txt")
        component, detail = mock_fail.call_args.args
        self.assertEqual(component, "report via ntfy")
        self.assertIn("/tmp/r.txt", detail)
        self.assertEqual(mock_recover.call_args.args[0], "report via email")

    @patch("alerts.notify_recovery")
    @patch("alerts.notify_failure")
    def test_site_publish_left_to_build_and_push(self, mock_fail, mock_recover):
        alerts.report_channels({"site publish": False}, "/tmp/r.txt")
        mock_fail.assert_not_called()
        mock_recover.assert_not_called()

    @patch("alerts.notify_failure", side_effect=RuntimeError("boom"))
    def test_alert_error_does_not_propagate(self, _mock_fail):
        alerts.report_channels({"ntfy": False}, "/tmp/r.txt")
