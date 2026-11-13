"""Report delivery: file archive, email, ntfy push, Facebook post, Zapier webhook."""

import base64
import json
import logging
import smtplib
import ssl
import subprocess
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

import config

logger = logging.getLogger(__name__)


def http_post(
    url: str,
    data: bytes,
    headers: dict,
    channel: str,
    timeout: int = 15,
    success_statuses: tuple = (200,),
) -> bool:
    """POST and report success as a bool. Shared with alerts.py, hence public."""
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


def _header_safe(text: str) -> str:
    """Fold a title down to something an HTTP header can legally carry.

    urllib encodes headers as latin-1, so the em dash in "Air Picture — 2026-08-07"
    raises UnicodeEncodeError and loses the notification entirely. The message
    body is unaffected: that travels as UTF-8 bytes, not a header.
    """
    swaps = {"—": "-", "–": "-", "’": "'", "‘": "'", "“": '"', "”": '"', "…": "..."}
    for bad, good in swaps.items():
        text = text.replace(bad, good)
    # Anything still outside latin-1 is dropped rather than allowed to raise.
    return text.encode("latin-1", "ignore").decode("latin-1")


def ntfy_post(title: str, message: str, priority: str = "default", tags: str = "airplane") -> bool:
    """Push one ntfy notification. The single ntfy path — reports and alerts both use it.

    Auth matters here: NTFY_URL names a self-hosted server that refuses
    anonymous requests, so a push without NTFY_USER/NTFY_PASS returns 403.
    Unset, it falls back to public ntfy.sh and sends unauthenticated.
    """
    if not config.NTFY_TOPIC:
        logger.debug("NTFY_TOPIC not configured, not sending: %s", title)
        return False

    headers = {"Title": _header_safe(title), "Priority": priority, "Tags": tags}
    if config.NTFY_USER and config.NTFY_PASS:
        token = base64.b64encode(
            f"{config.NTFY_USER}:{config.NTFY_PASS}".encode("utf-8")
        ).decode("ascii")
        headers["Authorization"] = f"Basic {token}"

    return http_post(
        f"{config.NTFY_URL}/{urllib.parse.quote(config.NTFY_TOPIC)}",
        data=message.encode("utf-8"),
        headers=headers,
        channel="ntfy",
        timeout=10,
    )


def save_to_file(report_text: str, date_str: str) -> str:
    """Save report to the archive directory. Returns the file path."""
    out_dir = Path(config.REPORT_OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"airpicture_{date_str}.txt"
    path.write_text(report_text, encoding="utf-8")
    logger.info("Report saved to %s", path)
    return str(path)


def push_ntfy(report_text: str, date_str: str) -> bool:
    """Send executive-summary push via ntfy."""
    lines = [line.strip() for line in report_text.splitlines() if line.strip()]
    summary = lines[1] if len(lines) > 1 else lines[0] if lines else "Air picture ready."
    return ntfy_post(f"Air Picture — {date_str}", summary)


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
    return http_post(url, data=data, headers={}, channel="Facebook")


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
    return http_post(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        channel="Zapier webhook",
        success_statuses=(200, 201),
    )


def email_configured() -> bool:
    """True when every setting send_email needs is present."""
    return all((config.EMAIL_TO, config.EMAIL_FROM, config.SMTP_HOST,
                config.SMTP_USER, config.SMTP_PASS))


def send_email(report_text: str, date_str: str) -> bool:
    """Email the full report as plain text over SMTP.

    EMAIL_TO may hold several comma-separated addresses.
    """
    if not email_configured():
        logger.debug("Email not configured, skipping")
        return False

    recipients = [a.strip() for a in config.EMAIL_TO.split(",") if a.strip()]
    msg = EmailMessage()
    msg["Subject"] = f"Air Picture — {date_str}"
    msg["From"] = formataddr(("Air Picture", config.EMAIL_FROM))
    msg["To"] = ", ".join(recipients)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=config.EMAIL_FROM.rsplit("@", 1)[-1])
    msg.set_content(report_text)

    context = ssl.create_default_context()
    try:
        if config.SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT,
                                      timeout=30, context=context)
        else:
            server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30)
            server.starttls(context=context)
        with server:
            server.login(config.SMTP_USER, config.SMTP_PASS)
            server.send_message(msg, to_addrs=recipients)
    except (smtplib.SMTPException, OSError) as e:
        logger.error("Email failed: %s", e)
        return False
    return True


def publish_site(_date_str: str) -> bool:
    """Rebuild the static site and publish it to Cloudflare Pages.

    This used to build docs/ and then git add / commit / push it, back when
    GitHub Actions served the site. Publishing moved to Cloudflare Pages and
    docs/ became gitignored, which quietly turned this into a no-op that still
    reported success: `git add docs/` staged nothing, so the `--cached --quiet`
    check saw no diff, logged "docs/ unchanged, skipping commit" and returned
    True on every daily report.

    Delegating to build_and_push.sh keeps one publish path instead of two, and
    means the deploy alerting in that script covers this caller too.
    """
    script = Path(__file__).parent / "build_and_push.sh"
    try:
        result = subprocess.run(
            ["/bin/bash", str(script)],
            cwd=str(script.parent), capture_output=True, text=True,
            timeout=300, check=False,
        )
    except subprocess.TimeoutExpired:
        logger.error("Site publish timed out")
        return False

    if result.returncode != 0:
        logger.error("Site publish failed (exit %s): %s", result.returncode, result.stderr.strip())
        return False
    logger.info("Site published to Cloudflare Pages")
    return True


def deliver(report_text: str, date_str: str) -> tuple[str, dict[str, bool]]:
    """Run all configured delivery channels; network channels run concurrently.

    Returns the archive path and {channel name: succeeded}, so the caller can
    raise alerts. Alerting lives in agent.py, not here, because alerts.py
    imports this module for ntfy_post.
    """
    file_path = save_to_file(report_text, date_str)
    logger.info("[deliver] Report archived: %s", file_path)

    channels = []
    if email_configured():
        channels.append(("email", send_email))
    if config.NTFY_TOPIC:
        channels.append(("ntfy", push_ntfy))
    if config.FB_PAGE_ID and config.FB_ACCESS_TOKEN:
        channels.append(("Facebook", post_facebook))
    if config.ZAPIER_WEBHOOK_URL:
        channels.append(("Zapier webhook", post_zapier_webhook))
    if config.PUBLISH_SITE:
        channels.append(("site publish", lambda _rt, d: publish_site(d)))

    results: dict[str, bool] = {}
    if not channels:
        return file_path, results

    with ThreadPoolExecutor(max_workers=len(channels)) as pool:
        futures = {pool.submit(fn, report_text, date_str): name for name, fn in channels}
        for future in as_completed(futures):
            name = futures[future]
            ok = future.result()
            logger.info("[deliver] %s: %s", name, "OK" if ok else "FAILED")
            results[name] = ok
    return file_path, results
