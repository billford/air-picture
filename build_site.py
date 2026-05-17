#!/usr/bin/env python3
"""Build the GitHub Pages static site from local report .txt files."""

import html as html_mod
import re
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent
REPORTS_DIR = REPO_ROOT / "reports"
OUT_DIR = REPO_ROOT / "docs"

# ---------------------------------------------------------------------------
# Markdown → HTML
# ---------------------------------------------------------------------------

def _inline(text: str) -> str:
    text = html_mod.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    return text


def md_to_html(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    para: list[str] = []

    def flush():
        if para:
            out.append(f'<p>{_inline(" ".join(para))}</p>')
            para.clear()

    for line in lines:
        s = line.strip()
        if s.startswith("## "):
            flush(); out.append(f"<h2>{_inline(s[3:])}</h2>")
        elif s.startswith("# "):
            flush(); out.append(f"<h1>{_inline(s[2:])}</h1>")
        elif s == "---":
            flush(); out.append("<hr>")
        elif not s:
            flush()
        else:
            para.append(s)
    flush()
    return "\n".join(out)


def extract_summary(text: str) -> str:
    for line in text.splitlines():
        if "EXECUTIVE SUMMARY" in line:
            clean = re.sub(r"\*\*(.+?)\*\*", r"\1", line.strip())
            clean = re.sub(r"^#+\s*", "", clean)
            return clean
    return "No summary available."


# ---------------------------------------------------------------------------
# CSS (single embedded stylesheet)
# ---------------------------------------------------------------------------

CSS = """
:root {
    --bg:           #0d1117;
    --surface:      #161b22;
    --border:       #21262d;
    --accent:       #3fb950;
    --text:         #c9d1d9;
    --text-muted:   #6e7681;
    --text-heading: #e6edf3;
    --link:         #58a6ff;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    font-size: 15px;
    line-height: 1.6;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
}
a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; }

/* Header */
header {
    border-bottom: 1px solid var(--border);
    padding: 12px 24px;
}
.site-title {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    text-decoration: none;
}
.callsign {
    color: var(--accent);
    font-family: "SF Mono", "Fira Code", Consolas, monospace;
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.08em;
}
.sep { color: var(--text-muted); }
.location {
    color: var(--text-muted);
    font-family: "SF Mono", "Fira Code", Consolas, monospace;
    font-size: 12px;
    letter-spacing: 0.04em;
}

/* Main */
main {
    flex: 1;
    max-width: 820px;
    margin: 0 auto;
    padding: 32px 24px;
    width: 100%;
}

/* Index page */
.page-header { margin-bottom: 24px; }
.page-header h1 { font-size: 18px; color: var(--text-heading); font-weight: 600; }
.page-header p  { color: var(--text-muted); font-size: 13px; margin-top: 4px; }

.report-list {
    list-style: none;
    border: 1px solid var(--border);
    border-radius: 6px;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    gap: 1px;
    background: var(--border);
}
.report-item {
    background: var(--surface);
    padding: 14px 18px;
    display: flex;
    align-items: baseline;
    gap: 16px;
    transition: background 0.1s;
}
.report-item:hover { background: #1c2129; }
.report-date {
    color: var(--accent);
    font-family: "SF Mono", "Fira Code", Consolas, monospace;
    font-size: 12px;
    white-space: nowrap;
    min-width: 96px;
}
.report-summary { flex: 1; font-size: 14px; color: var(--text); }
.report-link    { font-size: 12px; white-space: nowrap; }

/* Report page */
.report-nav {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
    font-size: 13px;
    color: var(--text-muted);
}
.report-content {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 26px 30px;
    font-family: "SF Mono", "Fira Code", Consolas, monospace;
    font-size: 13px;
    line-height: 1.8;
}
.report-content h1 {
    color: var(--accent);
    font-size: 14px;
    letter-spacing: 0.06em;
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--border);
}
.report-content h2 {
    color: var(--text-heading);
    font-size: 11px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin: 22px 0 8px;
}
.report-content hr {
    border: none;
    border-top: 1px solid var(--border);
    margin: 14px 0;
}
.report-content p         { margin-bottom: 10px; }
.report-content strong    { color: var(--text-heading); }
.report-pager {
    display: flex;
    justify-content: space-between;
    margin-top: 18px;
    font-size: 13px;
    color: var(--text-muted);
}

/* Footer */
footer {
    border-top: 1px solid var(--border);
    padding: 12px 24px;
    text-align: center;
    color: var(--text-muted);
    font-size: 12px;
    font-family: "SF Mono", "Fira Code", Consolas, monospace;
}

@media (max-width: 600px) {
    .report-item  { flex-direction: column; gap: 4px; }
    .report-content { padding: 16px 14px; font-size: 12px; }
}
"""

# ---------------------------------------------------------------------------
# Page template
# ---------------------------------------------------------------------------

HEADER = """<header>
  <a href="index.html" class="site-title">
    <span class="callsign">AIR PICTURE</span>
    <span class="sep">·</span>
    <span class="location">CHAGRIN FALLS, OH · 41.43°N 81.40°W</span>
  </a>
</header>"""

FOOTER = """<footer>
  <p>ADS-B ground station &mdash; Chagrin Falls, Ohio</p>
</footer>"""


def page_wrap(title: str, body: str) -> str:
    safe_title = html_mod.escape(title)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{safe_title}</title>
  <style>{CSS}</style>
</head>
<body>
{HEADER}
<main>{body}</main>
{FOOTER}
</body>
</html>"""


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def load_reports() -> list[dict]:
    """Return list of report dicts sorted newest-first."""
    reports = []
    for path in sorted(REPORTS_DIR.glob("airpicture_*.txt"), reverse=True):
        m = re.search(r"airpicture_(\d{4}-\d{2}-\d{2})\.txt$", path.name)
        if not m:
            continue
        date_str = m.group(1)
        text = path.read_text(encoding="utf-8")
        reports.append({
            "date": date_str,
            "slug": date_str,
            "text": text,
            "summary": extract_summary(text),
        })
    return reports


def build_index(reports: list[dict]) -> str:
    count = len(reports)
    noun = "briefing" if count == 1 else "briefings"
    items = []
    for r in reports:
        dt = datetime.fromisoformat(r["date"])
        label = dt.strftime("%b %-d, %Y")
        summary = html_mod.escape(r["summary"])
        items.append(
            f'<li class="report-item">'
            f'<span class="report-date">{html_mod.escape(label)}</span>'
            f'<span class="report-summary">{summary}</span>'
            f'<a class="report-link" href="{r["slug"]}.html">Read &rarr;</a>'
            f"</li>"
        )

    list_html = f'<ul class="report-list">{"".join(items)}</ul>' if items else "<p>No briefings yet.</p>"

    body = f"""
<div class="page-header">
  <h1>Daily Briefings</h1>
  <p>{count} {noun} on record</p>
</div>
{list_html}"""
    return page_wrap("Air Picture — Chagrin Falls, OH", body)


def build_report_page(report: dict, prev_slug: str | None, next_slug: str | None) -> str:
    content_html = md_to_html(report["text"])

    prev_link = f'<a href="{prev_slug}.html">&larr; {prev_slug}</a>' if prev_slug else "<span></span>"
    next_link = f'<a href="{next_slug}.html">{next_slug} &rarr;</a>' if next_slug else "<span></span>"

    body = f"""
<div class="report-nav">
  <a href="index.html">&larr; All briefings</a>
  <span>{html_mod.escape(report["date"])}</span>
</div>
<div class="report-content">{content_html}</div>
<div class="report-pager">{prev_link}{next_link}</div>"""

    return page_wrap(f"Air Picture — {report['date']}", body)


def build():
    if not REPORTS_DIR.exists():
        print(f"[build_site] No reports directory at {REPORTS_DIR}", file=sys.stderr)
        sys.exit(1)

    reports = load_reports()
    if not reports:
        print("[build_site] No report files found.", file=sys.stderr)
        sys.exit(1)

    OUT_DIR.mkdir(exist_ok=True)

    # Index
    (OUT_DIR / "index.html").write_text(build_index(reports), encoding="utf-8")

    # Individual pages (reports are newest-first; prev = older, next = newer)
    for i, report in enumerate(reports):
        prev_slug = reports[i + 1]["slug"] if i + 1 < len(reports) else None
        next_slug = reports[i - 1]["slug"] if i > 0 else None
        html = build_report_page(report, prev_slug, next_slug)
        (OUT_DIR / f"{report['slug']}.html").write_text(html, encoding="utf-8")

    print(f"[build_site] Built {len(reports)} pages → {OUT_DIR}/")


if __name__ == "__main__":
    build()
