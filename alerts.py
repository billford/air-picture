"""Operational alerts for the pipeline itself, as opposed to the aircraft it watches.

deliver.py pushes the daily report. This pushes the thing nobody asked for: news
that the pipeline is broken. It exists because two failures ran unnoticed for a
long time - launchd's PATH lacking npx, which killed 105 consecutive deploys in
a day, and a stale sdr_mcp path that sent 518 scans to the OpenSky fallback.
Both wrote to the log every time. Nobody reads a log that is fine 99% of the
time, so the log was the wrong channel.

The hard part is not sending the alert, it's sending few enough of them to stay
readable. build_and_push.sh runs after every scan - roughly 96 times a day - so
a persistent failure naively wired to ntfy is 96 push notifications, which is
just a louder way of being ignored. So:

  - the first failure notifies immediately: that is the transition worth knowing
  - continued failure re-notifies at most once every ALERT_REPEAT_HOURS, and
    says how long it has been broken and how many attempts have failed
  - recovery notifies once, so a fixed thing stops nagging and you know it
    actually recovered rather than just going quiet

State lives in a small JSON file - see config.ALERT_STATE_FILE. It is keyed by
component so the site deploy and the SDR can fail independently without
suppressing each other's alerts.
"""

import json
import logging
import subprocess
import time
from pathlib import Path

import config
import deliver

logger = logging.getLogger(__name__)


def _load_state() -> dict:
    """Read the alert state file. Any problem reading it means 'nothing known'."""
    path = Path(config.ALERT_STATE_FILE)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as e:
        # A corrupt state file must not stop the alert. Losing the throttle is a
        # far better failure than losing the notification.
        logger.warning("Alert state unreadable (%s); treating as empty", e)
        return {}


def _save_state(state: dict) -> None:
    path = Path(config.ALERT_STATE_FILE)
    try:
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("Could not write alert state: %s", e)


def _escape_applescript(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", ", ")


def _mac_notification(title: str, message: str) -> None:
    """Post a local macOS notification. Same approach as waterguru/alerts.py.

    This is the fallback that survives the network being the thing that broke.
    ntfy lives on a Tailscale host, so 'Tailscale is down' and 'the alert cannot
    be delivered' are the same event - and a deploy failure during it would
    otherwise be recorded as notified and never mentioned again.
    """
    script = (
        f'display notification "{_escape_applescript(message)}" '
        f'with title "{_escape_applescript(title)}" sound name "Basso"'
    )
    try:
        subprocess.run(["osascript", "-e", script], check=False, timeout=10)
    except (OSError, subprocess.SubprocessError) as e:
        logger.debug("macOS notification failed: %s", e)


def _push(title: str, message: str, priority: str, tags: str) -> bool:
    """Send one alert over every channel. Local first, since it cannot fail on network."""
    _mac_notification(title, message)
    return deliver.ntfy_post(title, message, priority=priority, tags=tags)


def _humanise(seconds: float) -> str:
    """'3h 20m' / '45m' / '30s' - enough precision to judge how stale something is."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    hours, minutes = divmod(seconds // 60, 60)
    return f"{hours}h {minutes}m" if minutes else f"{hours}h"


def notify_failure(component: str, detail: str) -> bool:
    """Record a failure and push, unless an identical one was pushed recently.

    Returns True if a notification was actually sent.
    """
    state = _load_state()
    now = time.time()
    entry = state.get(component)
    repeat_seconds = config.ALERT_REPEAT_HOURS * 3600

    if entry and entry.get("failing"):
        entry["count"] = entry.get("count", 1) + 1
        since = now - entry.get("first", now)
        due = now - entry.get("last_notified", 0) >= repeat_seconds
        if not due:
            # Still broken, already told them. Keep counting silently.
            state[component] = entry
            _save_state(state)
            logger.info(
                "%s still failing (%s attempts over %s); alert throttled",
                component, entry["count"], _humanise(since),
            )
            return False
        entry["last_notified"] = now
        state[component] = entry
        _save_state(state)
        return _push(
            f"Air Picture — {component} still failing",
            f"Broken for {_humanise(since)}, {entry['count']} failed attempts.\n\n{detail}",
            priority="high",
            tags="rotating_light",
        )

    state[component] = {"failing": True, "first": now, "last_notified": now, "count": 1}
    _save_state(state)
    return _push(
        f"Air Picture — {component} FAILED",
        detail,
        priority="high",
        tags="warning",
    )


def notify_recovery(component: str, detail: str = "") -> bool:
    """Clear a failure and push a recovery note, but only if it was actually failing.

    Called on every success, so the 'was it failing' check is what keeps this
    from notifying on all ~96 healthy runs a day.
    """
    state = _load_state()
    entry = state.get(component)
    if not entry or not entry.get("failing"):
        return False

    down_for = _humanise(time.time() - entry.get("first", time.time()))
    attempts = entry.get("count", 1)
    state.pop(component, None)
    _save_state(state)

    message = f"Recovered after {down_for} and {attempts} failed attempts."
    if detail:
        message += f"\n\n{detail}"
    return _push(
        f"Air Picture — {component} recovered",
        message,
        priority="default",
        tags="white_check_mark",
    )


def report_channels(results: dict, file_path: str) -> None:
    """Raise or clear an alert for each report delivery channel.

    Until this existed, a failing channel was only ever logged. ntfy went 401
    and the Zapier hook went 404 in late October 2026, and the reports quietly
    stopped arriving for two weeks while the log said FAILED every morning.

    _push always posts a local macOS notification before trying ntfy, so this
    still gets through when ntfy is the broken channel. With one report a day
    and ALERT_REPEAT_HOURS at 6, a persistent failure nags once per report.

    The site channel is skipped: build_and_push.sh already alerts as
    "site deploy", and alerting here too would double every notification.
    """
    for name, ok in results.items():
        if name == "site publish":
            continue
        component = f"report via {name}"
        try:
            if ok:
                notify_recovery(component, "Daily reports are arriving again.")
            else:
                notify_failure(
                    component,
                    f"Today's report was saved to {file_path} but did not reach {name}. "
                    "See air_picture.log for the error.",
                )
        except Exception as e:  # pylint: disable=broad-exception-caught
            # A broken notifier must never break delivery.
            logger.warning("Alert for %s failed: %s", name, e)


def main(argv=None) -> int:
    """Shell entry point, so build_and_push.sh can alert without embedding Python.

    Usage: python -m alerts {failure|recovery} <component> [detail]
    """
    import argparse  # pylint: disable=import-outside-toplevel

    parser = argparse.ArgumentParser(description="Send a pipeline alert via ntfy.")
    parser.add_argument("kind", choices=("failure", "recovery"))
    parser.add_argument("component")
    parser.add_argument("detail", nargs="?", default="")
    args = parser.parse_args(argv)

    if args.kind == "failure":
        notify_failure(args.component, args.detail)
    else:
        notify_recovery(args.component, args.detail)
    # Always succeed: a failing alert must never be the reason a caller fails.
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")
    raise SystemExit(main())
