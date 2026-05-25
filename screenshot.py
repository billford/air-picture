#!/usr/bin/env python3
"""Take screenshots of the dashboard and index pages for the README."""

from pathlib import Path
from playwright.sync_api import sync_playwright  # pylint: disable=import-error

DOCS = Path(__file__).parent / "docs"
SCREENSHOTS = Path(__file__).parent / "screenshots"

PAGES = [
    ("dashboard.html", "dashboard.png", 1400),
    ("index.html",     "index.png",     1400),
]

# Wait long enough for Chart.js to finish rendering
CHART_SETTLE_MS = 1500


def take_screenshots() -> None:
    """Render each page in a headless browser and save a full-page PNG."""
    SCREENSHOTS.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900})

        for filename, out_name, _ in PAGES:
            src = DOCS / filename
            url = src.as_uri()
            print(f"[screenshot] {filename} → screenshots/{out_name}")
            page.goto(url, wait_until="networkidle")
            page.wait_for_timeout(CHART_SETTLE_MS)
            page.screenshot(
                path=str(SCREENSHOTS / out_name),
                full_page=True,
            )

        browser.close()

    print("[screenshot] Done.")


if __name__ == "__main__":
    take_screenshots()
