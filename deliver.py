"""Report delivery: file archive, ntfy.sh push, Facebook post, Zapier webhook."""

import json
import logging
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import config

logger = logging.getLogger(__name__)


def _http_post(
    url: str,
    data: bytes,
    headers: dict,
    channel: str,
    timeout: int = 15,
    success_statuses: tuple = (200,),
) -> bool:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status in success_statuses:
                return True
            logger.warning("%s returned unexpected status %s", channel, resp.status)
            return False
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("%s failed: %s", channel, e)
        return False


def save_to_file(report_text: str, date_str: str) -> str:
    """Save report to the archive directory. Returns the file path."""
    out_dir = Path(config.REPORT_OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"airpicture_{date_str}.txt"
    path.write_text(report_text, encoding="utf-8")
    logger.info("Report saved to %s", path)
    return str(path)


def push_ntfy(report_text: str, date_str: str) -> bool:
    """Send executive-summary push via ntfy.sh."""
    topic = config.NTFY_TOPIC
    if not topic:
        logger.debug("NTFY_TOPIC not configured, skipping")
        return False

    lines = [line.strip() for line in report_text.splitlines() if line.strip()]
    summary = lines[1] if len(lines) > 1 else lines[0] if lines else "Air picture ready."

    return _http_post(
        f"https://ntfy.sh/{urllib.parse.quote(topic)}",
        data=summary.encode("utf-8"),
        headers={"Title": f"Air Picture — {date_str}", "Priority": "default", "Tags": "airplane"},
        channel="ntfy",
        timeout=10,
    )


def post_facebook(report_text: str, date_str: str) -> bool:
    """Post report to Facebook page."""
    page_id = config.FB_PAGE_ID
    token = config.FB_ACCESS_TOKEN
    if not page_id or not token:
        logger.debug("Facebook credentials not configured, skipping")
        return False

    url = f"https://graph.facebook.com/v19.0/{page_id}/feed"
    message = f"✈️ AIR PICTURE — {date_str}\n\n{report_text}"
    data = urllib.parse.urlencode({"message": message, "access_token": token}).encode()
    return _http_post(url, data=data, headers={}, channel="Facebook")


def post_zapier_webhook(report_text: str, date_str: str) -> bool:
    """POST the report as JSON to the configured Zapier webhook."""
    url = config.ZAPIER_WEBHOOK_URL
    if not url:
        logger.debug("ZAPIER_WEBHOOK_URL not configured, skipping")
        return False

    if urllib.parse.urlparse(url).scheme != "https":
        logger.error("ZAPIER_WEBHOOK_URL must use HTTPS")
        return False

    payload = json.dumps({"date": date_str, "report": report_text}).encode("utf-8")
    return _http_post(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        channel="Zapier webhook",
        success_statuses=(200, 201),
    )


def deliver(report_text: str, date_str: str):
    """Run all configured delivery channels; network channels run concurrently."""
    file_path = save_to_file(report_text, date_str)
    logger.info("[deliver] Report archived: %s", file_path)

    channels = []
    if config.NTFY_TOPIC:
        channels.append(("ntfy", push_ntfy))
    if config.FB_PAGE_ID and config.FB_ACCESS_TOKEN:
        channels.append(("Facebook", post_facebook))
    if config.ZAPIER_WEBHOOK_URL:
        channels.append(("Zapier webhook", post_zapier_webhook))

    if not channels:
        return

    with ThreadPoolExecutor(max_workers=len(channels)) as pool:
        futures = {pool.submit(fn, report_text, date_str): name for name, fn in channels}
        for future in as_completed(futures):
            name = futures[future]
            ok = future.result()
            logger.info("[deliver] %s: %s", name, "OK" if ok else "FAILED")
