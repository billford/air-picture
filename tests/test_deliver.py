"""Tests for report delivery functions."""

import io
import json
import tempfile
import unittest
from http.client import HTTPResponse
from pathlib import Path
from unittest.mock import MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
        ok = deliver._http_post("https://example.com", b"data", {}, "test")
        self.assertTrue(ok)

    @patch("deliver.urllib.request.urlopen")
    def test_success_custom_status(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(201)
        ok = deliver._http_post("https://example.com", b"data", {}, "test", success_statuses=(200, 201))
        self.assertTrue(ok)

    @patch("deliver.urllib.request.urlopen")
    def test_unexpected_status_returns_false(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(500)
        ok = deliver._http_post("https://example.com", b"data", {}, "test")
        self.assertFalse(ok)

    @patch("deliver.urllib.request.urlopen", side_effect=OSError("connection refused"))
    def test_exception_returns_false(self, _mock_urlopen):
        ok = deliver._http_post("https://example.com", b"data", {}, "test")
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
    @patch("deliver._http_post", return_value=True)
    def test_sends_summary_line(self, mock_post):
        report = "HEADER\nExecutive summary line.\nMore stuff."
        deliver.push_ntfy(report, "2026-05-14")
        self.assertEqual(mock_post.call_args[1]["data"], b"Executive summary line.")

    @patch.object(deliver.config, "NTFY_TOPIC", "test-topic")
    @patch("deliver._http_post", return_value=False)
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
    @patch("deliver._http_post", return_value=True)
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
    @patch("deliver._http_post", return_value=True)
    def test_sends_json_payload(self, mock_post):
        deliver.post_zapier_webhook("MY REPORT", "2026-05-14")
        payload_bytes = mock_post.call_args[1]["data"]
        payload = json.loads(payload_bytes.decode("utf-8"))
        self.assertEqual(payload["date"], "2026-05-14")
        self.assertEqual(payload["report"], "MY REPORT")

    @patch.object(deliver.config, "ZAPIER_WEBHOOK_URL", "https://hooks.zapier.com/catch/123")
    @patch("deliver._http_post", return_value=True)
    def test_uses_201_success_status(self, mock_post):
        deliver.post_zapier_webhook("report", "2026-05-14")
        kwargs = mock_post.call_args[1]
        self.assertIn(201, kwargs.get("success_statuses", ()))


class TestDeliver(unittest.TestCase):
    @patch("deliver.save_to_file", return_value="/tmp/report.txt")
    @patch.object(deliver.config, "NTFY_TOPIC", "topic")
    @patch.object(deliver.config, "FB_PAGE_ID", "")
    @patch.object(deliver.config, "FB_ACCESS_TOKEN", "")
    @patch.object(deliver.config, "ZAPIER_WEBHOOK_URL", "https://hooks.zapier.com/test")
    @patch("deliver.push_ntfy", return_value=True)
    @patch("deliver.post_zapier_webhook", return_value=True)
    def test_calls_configured_channels(self, mock_zapier, mock_ntfy, mock_save):
        deliver.deliver("report", "2026-05-14")
        mock_ntfy.assert_called_once_with("report", "2026-05-14")
        mock_zapier.assert_called_once_with("report", "2026-05-14")

    @patch("deliver.save_to_file", return_value="/tmp/report.txt")
    @patch.object(deliver.config, "NTFY_TOPIC", "")
    @patch.object(deliver.config, "FB_PAGE_ID", "")
    @patch.object(deliver.config, "FB_ACCESS_TOKEN", "")
    @patch.object(deliver.config, "ZAPIER_WEBHOOK_URL", "")
    def test_no_channels_configured(self, mock_save):
        # Should complete without error when no channels are active
        deliver.deliver("report", "2026-05-14")
        mock_save.assert_called_once()


if __name__ == "__main__":
    unittest.main()
