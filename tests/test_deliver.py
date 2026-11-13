# pylint: disable=missing-function-docstring,missing-class-docstring,protected-access
"""Tests for report delivery functions."""

import base64
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import deliver


def _mock_response(status: int, body: bytes = b"ok") -> MagicMock:
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


class TestHttpPost(unittest.TestCase):
    @patch("deliver.urllib.request.urlopen")
    def test_success_200(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(200)
        ok = deliver.http_post("https://example.com", b"data", {}, "test")
        self.assertTrue(ok)

    @patch("deliver.urllib.request.urlopen")
    def test_success_custom_status(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(201)
        ok = deliver.http_post("https://example.com", b"data", {}, "test", success_statuses=(200, 201))
        self.assertTrue(ok)

    @patch("deliver.urllib.request.urlopen")
    def test_unexpected_status_returns_false(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(500)
        ok = deliver.http_post("https://example.com", b"data", {}, "test")
        self.assertFalse(ok)

    @patch("deliver.urllib.request.urlopen", side_effect=OSError("connection refused"))
    def test_exception_returns_false(self, _mock_urlopen):
        ok = deliver.http_post("https://example.com", b"data", {}, "test")
        self.assertFalse(ok)


class TestSaveToFile(unittest.TestCase):
    def test_creates_file_with_correct_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(deliver.config, "REPORT_OUTPUT_DIR", tmpdir):
                path = deliver.save_to_file("REPORT TEXT", "2026-05-14")
                self.assertTrue(Path(path).exists())
                self.assertEqual(Path(path).read_text(encoding="utf-8"), "REPORT TEXT")

    def test_filename_includes_date(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(deliver.config, "REPORT_OUTPUT_DIR", tmpdir):
                path = deliver.save_to_file("x", "2026-05-14")
                self.assertIn("2026-05-14", path)


class TestPushNtfy(unittest.TestCase):
    @patch.object(deliver.config, "NTFY_TOPIC", "")
    def test_no_topic_returns_false(self):
        self.assertFalse(deliver.push_ntfy("report", "2026-05-14"))

    @patch.object(deliver.config, "NTFY_TOPIC", "test-topic")
    @patch("deliver.http_post", return_value=True)
    def test_sends_summary_line(self, mock_post):
        deliver.push_ntfy("HEADER\nExecutive summary line.\nMore stuff.", "2026-05-14")
        self.assertEqual(mock_post.call_args[1]["data"], b"Executive summary line.")

    @patch.object(deliver.config, "NTFY_TOPIC", "test-topic")
    @patch("deliver.http_post", return_value=False)
    def test_propagates_failure(self, _mock_post):
        self.assertFalse(deliver.push_ntfy("HEADER\nSummary.", "2026-05-14"))


class TestPostFacebook(unittest.TestCase):
    @patch.object(deliver.config, "FB_PAGE_ID", "")
    @patch.object(deliver.config, "FB_ACCESS_TOKEN", "")
    def test_no_creds_returns_false(self):
        self.assertFalse(deliver.post_facebook("report", "2026-05-14"))

    @patch.object(deliver.config, "FB_PAGE_ID", "123")
    @patch.object(deliver.config, "FB_ACCESS_TOKEN", "")
    def test_missing_token_returns_false(self):
        self.assertFalse(deliver.post_facebook("report", "2026-05-14"))

    @patch.object(deliver.config, "FB_PAGE_ID", "123")
    @patch.object(deliver.config, "FB_ACCESS_TOKEN", "tok")
    @patch("deliver.http_post", return_value=True)
    def test_posts_to_correct_url(self, mock_post):
        deliver.post_facebook("report", "2026-05-14")
        url = mock_post.call_args[0][0]
        self.assertIn("123", url)
        self.assertIn("graph.facebook.com", url)


class TestPostZapierWebhook(unittest.TestCase):
    @patch.object(deliver.config, "ZAPIER_WEBHOOK_URL", "")
    def test_no_url_returns_false(self):
        self.assertFalse(deliver.post_zapier_webhook("report", "2026-05-14"))

    @patch.object(deliver.config, "ZAPIER_WEBHOOK_URL", "http://hooks.zapier.com/catch/123")
    def test_http_url_rejected(self):
        self.assertFalse(deliver.post_zapier_webhook("report", "2026-05-14"))

    @patch.object(deliver.config, "ZAPIER_WEBHOOK_URL", "https://hooks.zapier.com/catch/123")
    @patch("deliver.http_post", return_value=True)
    def test_sends_json_payload(self, mock_post):
        deliver.post_zapier_webhook("MY REPORT", "2026-05-14")
        payload_bytes = mock_post.call_args[1]["data"]
        payload = json.loads(payload_bytes.decode("utf-8"))
        self.assertEqual(payload["date"], "2026-05-14")
        self.assertEqual(payload["report"], "MY REPORT")

    @patch.object(deliver.config, "ZAPIER_WEBHOOK_URL", "https://hooks.zapier.com/catch/123")
    @patch("deliver.http_post", return_value=True)
    def test_uses_201_success_status(self, mock_post):
        deliver.post_zapier_webhook("report", "2026-05-14")
        self.assertIn(201, mock_post.call_args[1].get("success_statuses", ()))


class TestNtfyPost(unittest.TestCase):
    @patch.object(deliver.config, "NTFY_TOPIC", "")
    @patch("deliver.http_post")
    def test_no_topic_is_a_noop(self, mock_http):
        self.assertFalse(deliver.ntfy_post("title", "message"))
        mock_http.assert_not_called()

    @patch.object(deliver.config, "NTFY_TOPIC", "airpicture")
    @patch.object(deliver.config, "NTFY_URL", "https://ntfy.example.com")
    @patch.object(deliver.config, "NTFY_USER", "user")
    @patch.object(deliver.config, "NTFY_PASS", "pass")
    @patch("deliver.http_post", return_value=True)
    def test_sends_basic_auth_to_self_hosted(self, mock_http):
        # The self-hosted server 403s anonymous pushes, so a missing
        # Authorization header is a silent no-delivery.
        self.assertTrue(deliver.ntfy_post("title", "message"))
        url = mock_http.call_args[0][0]
        headers = mock_http.call_args[1]["headers"]
        self.assertEqual(url, "https://ntfy.example.com/airpicture")
        expected = base64.b64encode(b"user:pass").decode("ascii")
        self.assertEqual(headers["Authorization"], f"Basic {expected}")

    @patch.object(deliver.config, "NTFY_TOPIC", "airpicture")
    @patch.object(deliver.config, "NTFY_URL", "https://ntfy.sh")
    @patch.object(deliver.config, "NTFY_USER", "")
    @patch.object(deliver.config, "NTFY_PASS", "")
    @patch("deliver.http_post", return_value=True)
    def test_public_ntfy_sends_unauthenticated(self, mock_http):
        self.assertTrue(deliver.ntfy_post("title", "message"))
        self.assertNotIn("Authorization", mock_http.call_args[1]["headers"])


class TestDeliver(unittest.TestCase):
    # PUBLISH_SITE defaults to true, so every one of these must turn it off
    # explicitly. It went unpatched while the site channel was a git no-op;
    # once publishing moved to Cloudflare Pages that made the test suite deploy
    # to production. Anything that leaves the machine gets patched here.
    def setUp(self):
        # deliver() now raises pipeline alerts; keep them off the desktop and
        # out of the real .alert_state.json.
        patcher = patch("deliver._alert_channel")
        self.mock_alert = patcher.start()
        self.addCleanup(patcher.stop)

    @patch("deliver.save_to_file", return_value="/tmp/report.txt")
    @patch.object(deliver.config, "NTFY_TOPIC", "topic")
    @patch.object(deliver.config, "FB_PAGE_ID", "")
    @patch.object(deliver.config, "FB_ACCESS_TOKEN", "")
    @patch.object(deliver.config, "ZAPIER_WEBHOOK_URL", "https://hooks.zapier.com/test")
    @patch.object(deliver.config, "PUBLISH_SITE", False)
    @patch("deliver.push_ntfy", return_value=True)
    @patch("deliver.post_zapier_webhook", return_value=False)
    def test_alerts_with_each_channel_result(self, _mock_zapier, _mock_ntfy, _mock_save):
        deliver.deliver("report", "2026-05-14")
        calls = {c.args[0]: c.args[1] for c in self.mock_alert.call_args_list}
        self.assertEqual(calls, {"ntfy": True, "Zapier webhook": False})

    @patch("deliver.save_to_file", return_value="/tmp/report.txt")
    @patch.object(deliver.config, "NTFY_TOPIC", "topic")
    @patch.object(deliver.config, "FB_PAGE_ID", "")
    @patch.object(deliver.config, "FB_ACCESS_TOKEN", "")
    @patch.object(deliver.config, "ZAPIER_WEBHOOK_URL", "https://hooks.zapier.com/test")
    @patch.object(deliver.config, "PUBLISH_SITE", False)
    @patch("deliver.push_ntfy", return_value=True)
    @patch("deliver.post_zapier_webhook", return_value=True)
    def test_calls_configured_channels(self, mock_zapier, mock_ntfy, _mock_save):
        deliver.deliver("report", "2026-05-14")
        mock_ntfy.assert_called_once_with("report", "2026-05-14")
        mock_zapier.assert_called_once_with("report", "2026-05-14")

    @patch("deliver.save_to_file", return_value="/tmp/report.txt")
    @patch.object(deliver.config, "NTFY_TOPIC", "")
    @patch.object(deliver.config, "FB_PAGE_ID", "")
    @patch.object(deliver.config, "FB_ACCESS_TOKEN", "")
    @patch.object(deliver.config, "ZAPIER_WEBHOOK_URL", "")
    @patch.object(deliver.config, "PUBLISH_SITE", False)
    def test_no_channels_configured(self, _mock_save):
        deliver.deliver("report", "2026-05-14")
        _mock_save.assert_called_once()

    @patch("deliver.save_to_file", return_value="/tmp/report.txt")
    @patch.object(deliver.config, "NTFY_TOPIC", "")
    @patch.object(deliver.config, "FB_PAGE_ID", "")
    @patch.object(deliver.config, "FB_ACCESS_TOKEN", "")
    @patch.object(deliver.config, "ZAPIER_WEBHOOK_URL", "")
    @patch.object(deliver.config, "PUBLISH_SITE", True)
    @patch("deliver.publish_site", return_value=True)
    def test_site_channel_runs_when_enabled(self, mock_publish, _mock_save):
        deliver.deliver("report", "2026-05-14")
        mock_publish.assert_called_once_with("2026-05-14")


class TestPublishSite(unittest.TestCase):
    @patch("deliver.subprocess.run")
    def test_delegates_to_build_and_push(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        self.assertTrue(deliver.publish_site("2026-05-14"))
        argv = mock_run.call_args[0][0]
        self.assertEqual(argv[0], "/bin/bash")
        self.assertTrue(argv[1].endswith("build_and_push.sh"))

    @patch("deliver.subprocess.run")
    def test_reports_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="boom")
        self.assertFalse(deliver.publish_site("2026-05-14"))

    @patch("deliver.subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 300))
    def test_reports_timeout(self, _mock_run):
        self.assertFalse(deliver.publish_site("2026-05-14"))


if __name__ == "__main__":
    unittest.main()


class TestAlertChannel(unittest.TestCase):
    @patch("alerts.notify_failure")
    def test_failure_raises_alert(self, mock_fail):
        deliver._alert_channel("ntfy", False, "/tmp/r.txt")
        component, detail = mock_fail.call_args.args
        self.assertEqual(component, "report via ntfy")
        self.assertIn("/tmp/r.txt", detail)

    @patch("alerts.notify_recovery")
    def test_success_clears_alert(self, mock_recover):
        deliver._alert_channel("Zapier webhook", True, "/tmp/r.txt")
        self.assertEqual(mock_recover.call_args.args[0], "report via Zapier webhook")

    @patch("alerts.notify_failure")
    @patch("alerts.notify_recovery")
    def test_site_publish_left_to_build_and_push(self, mock_recover, mock_fail):
        deliver._alert_channel("site publish", False, "/tmp/r.txt")
        mock_fail.assert_not_called()
        mock_recover.assert_not_called()

    @patch("alerts.notify_failure", side_effect=RuntimeError("boom"))
    def test_alert_error_does_not_propagate(self, _mock_fail):
        deliver._alert_channel("ntfy", False, "/tmp/r.txt")


class TestSendEmail(unittest.TestCase):
    def setUp(self):
        for key, val in {
            "EMAIL_TO": "a@example.com, b@example.com", "EMAIL_FROM": "air@example.org",
            "SMTP_HOST": "smtp.example.org", "SMTP_PORT": 465,
            "SMTP_USER": "api_token", "SMTP_PASS": "secret",
        }.items():
            p = patch.object(deliver.config, key, val)
            p.start()
            self.addCleanup(p.stop)

    @patch.object(deliver.config, "SMTP_PASS", "")
    def test_unconfigured_skips(self):
        self.assertFalse(deliver.send_email("r", "2026-11-13"))

    @patch("deliver.smtplib.SMTP_SSL")
    def test_sends_report_over_implicit_tls(self, mock_ssl):
        server = mock_ssl.return_value
        self.assertTrue(deliver.send_email("FULL REPORT", "2026-11-13"))
        server.login.assert_called_once_with("api_token", "secret")
        msg = server.send_message.call_args.args[0]
        self.assertEqual(msg["Subject"], "Air Picture — 2026-11-13")
        self.assertIn("FULL REPORT", msg.get_content())
        self.assertEqual(server.send_message.call_args.kwargs["to_addrs"],
                         ["a@example.com", "b@example.com"])

    @patch.object(deliver.config, "SMTP_PORT", 587)
    @patch("deliver.smtplib.SMTP")
    def test_other_ports_use_starttls(self, mock_smtp):
        self.assertTrue(deliver.send_email("r", "2026-11-13"))
        mock_smtp.return_value.starttls.assert_called_once()

    @patch("deliver.smtplib.SMTP_SSL", side_effect=OSError("refused"))
    def test_connection_error_returns_false(self, _mock_ssl):
        self.assertFalse(deliver.send_email("r", "2026-11-13"))
