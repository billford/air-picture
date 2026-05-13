"""Report delivery: file archive, ntfy.sh push, Facebook post."""

import json
import logging
import os
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

import config

logger = logging.getLogger(__name__)


def save_to_file(report_text: str, date_str: str) -> str:
    """Save report to the archive directory. Returns the file path."""
    out_dir = Path(config.REPORT_OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"airpicture_{date_str}.txt"
    path.write_text(report_text, encoding="utf-8")
    logger.info(f"Report saved to {path}")
    return str(path)


def push_ntfy(report_text: str, date_str: str) -> bool:
    """Send a summary push via ntfy.sh. Returns True on success."""
    topic = config.NTFY_TOPIC
    if not topic:
        logger.debug("NTFY_TOPIC not configured, skipping push")
        return False

    # Extract just the executive summary line (second non-blank line after the header)
    lines = [l.strip() for l in report_text.splitlines() if l.strip()]
    summary = lines[1] if len(lines) > 1 else lines[0] if lines else "Air picture ready."

    url = f"https://ntfy.sh/{urllib.parse.quote(topic)}"
    title = f"Air Picture — {date_str}"
    message = summary.encode("utf-8")

    req = urllib.request.Request(
        url,
        data=message,
        headers={
            "Title": title,
            "Priority": "default",
            "Tags": "airplane",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            success = resp.status == 200
            if success:
                logger.info(f"ntfy push sent to topic '{topic}'")
            else:
                logger.warning(f"ntfy push returned {resp.status}")
            return success
    except Exception as e:
        logger.error(f"ntfy push failed: {e}")
        return False


def post_facebook(report_text: str, date_str: str) -> bool:
    """Post report to Facebook page. Returns True on success."""
    page_id = config.FB_PAGE_ID
    token = config.FB_ACCESS_TOKEN

    if not page_id or not token:
        logger.debug("Facebook credentials not configured, skipping post")
        return False

    url = f"https://graph.facebook.com/v19.0/{page_id}/feed"
    message = f"✈️ AIR PICTURE — {date_str}\n\n{report_text}"
    data = urllib.parse.urlencode({"message": message, "access_token": token}).encode()

    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            success = resp.status == 200
            if success:
                logger.info("Report posted to Facebook page")
            else:
                logger.warning(f"Facebook post returned {resp.status}")
            return success
    except Exception as e:
        logger.error(f"Facebook post failed: {e}")
        return False


def post_zapier_webhook(report_text: str, date_str: str) -> bool:
    """POST the report to a Zapier webhook. Returns True on success."""
    url = config.ZAPIER_WEBHOOK_URL
    if not url:
        logger.debug("ZAPIER_WEBHOOK_URL not configured, skipping")
        return False

    payload = json.dumps({"date": date_str, "report": report_text}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            success = resp.status in (200, 201)
            if success:
                logger.info("Report sent to Zapier webhook")
            else:
                logger.warning(f"Zapier webhook returned {resp.status}")
            return success
    except Exception as e:
        logger.error(f"Zapier webhook failed: {e}")
        return False


def deliver(report_text: str, date_str: str):
    """Run all configured delivery channels."""
    file_path = save_to_file(report_text, date_str)
    print(f"[deliver] Report archived: {file_path}")

    if config.NTFY_TOPIC:
        ok = push_ntfy(report_text, date_str)
        print(f"[deliver] ntfy push: {'OK' if ok else 'FAILED'}")

    if config.FB_PAGE_ID and config.FB_ACCESS_TOKEN:
        ok = post_facebook(report_text, date_str)
        print(f"[deliver] Facebook post: {'OK' if ok else 'FAILED'}")

    if config.ZAPIER_WEBHOOK_URL:
        ok = post_zapier_webhook(report_text, date_str)
        print(f"[deliver] Zapier webhook: {'OK' if ok else 'FAILED'}")
