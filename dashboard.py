#!/usr/bin/env python3
"""Build the Air Picture analytics dashboard page."""
# pylint: disable=duplicate-code  # CSS design tokens intentionally shared with build_site.py

import html as html_mod
import json
from datetime import datetime, timezone
from pathlib import Path

import db  # for get_conn() only

REPO_ROOT = Path(__file__).parent
OUT_DIR = REPO_ROOT / "docs"
LOOKBACK_DAYS = 14
ANOMALY_DISPLAY_LIMIT = 500

# ── Styles ─────────────────────────────────────────────────────────────────────

_CSS = """
:root {
    --bg:           #0d1117;
    --surface:      #161b22;
    --border:       #21262d;
    --accent:       #3fb950;
    --text:         #c9d1d9;
    --text-muted:   #6e7681;
    --text-heading: #e6edf3;
    --link:         #58a6ff;
    --warn:         #d29922;
    --danger:       #f85149;
    --chart-1:      #3fb950;
    --chart-2:      #58a6ff;
    --chart-3:      #d29922;
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

header {
    border-bottom: 1px solid var(--border);
    padding: 12px 24px;
    display: flex;
    justify-content: space-between;
    align-items: center;
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
.site-nav a {
    color: var(--text-muted);
    font-size: 13px;
}
.site-nav a:hover { color: var(--text); }

main {
    flex: 1;
    max-width: 960px;
    margin: 0 auto;
    padding: 32px 24px;
    width: 100%;
}

footer {
    border-top: 1px solid var(--border);
    padding: 12px 24px;
    text-align: center;
    color: var(--text-muted);
    font-size: 12px;
    font-family: "SF Mono", "Fira Code", Consolas, monospace;
}

/* Dashboard */
.page-header { margin-bottom: 28px; }
.page-header h1 { font-size: 18px; color: var(--text-heading); font-weight: 600; }
.page-header p  { color: var(--text-muted); font-size: 13px; margin-top: 4px; }

.stats-bar {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    margin-bottom: 32px;
}
.stat-tile {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 16px 18px;
}
.stat-value {
    font-family: "SF Mono", "Fira Code", Consolas, monospace;
    font-size: 22px;
    font-weight: 600;
    color: var(--accent);
    line-height: 1.2;
}
.stat-value.danger { color: var(--danger); }
.stat-label { color: var(--text-muted); font-size: 12px; margin-top: 4px; }
.stat-sub {
    color: var(--text-muted);
    font-size: 11px;
    font-family: "SF Mono", "Fira Code", Consolas, monospace;
    margin-top: 2px;
}

.dash-section { margin-bottom: 36px; }
.dash-section h2 {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-heading);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 12px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
}
.chart-wrap {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 16px;
}

.dash-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
}
.dash-table th {
    text-align: left;
    color: var(--text-muted);
    font-size: 11px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 8px 12px;
    border-bottom: 1px solid var(--border);
    cursor: pointer;
    user-select: none;
    white-space: nowrap;
}
.dash-table th:hover { color: var(--text); }
.dash-table th.sort-asc::after  { content: " \25B2"; }
.dash-table th.sort-desc::after { content: " \25BC"; }
.dash-table td {
    padding: 9px 12px;
    border-bottom: 1px solid var(--border);
    vertical-align: middle;
}
.dash-table tr:last-child td { border-bottom: none; }
.dash-table tr:nth-child(even) td { background: rgba(255,255,255,0.02); }
.dash-table .mono   { font-family: "SF Mono", "Fira Code", Consolas, monospace; }
.dash-table .muted  { color: var(--text-muted); }
.dash-table .accent { color: var(--accent); }
.dash-table .right  { text-align: right; }

.badge {
    display: inline-block;
    padding: 2px 7px;
    border-radius: 4px;
    font-size: 11px;
    font-family: "SF Mono", "Fira Code", Consolas, monospace;
    font-weight: 500;
}
.badge-danger { background: rgba(248,81,73,0.15);  color: var(--danger);  border: 1px solid rgba(248,81,73,0.3); }
.badge-warn   { background: rgba(210,153,34,0.15); color: var(--warn);    border: 1px solid rgba(210,153,34,0.3); }
.badge-info   { background: rgba(88,166,255,0.15); color: var(--chart-2); border: 1px solid rgba(88,166,255,0.3); }

.table-wrap {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    overflow: hidden;
    overflow-x: auto;
}
.no-data {
    color: var(--text-muted);
    font-size: 13px;
    padding: 24px;
    text-align: center;
    font-family: "SF Mono", "Fira Code", Consolas, monospace;
}

/* Two-column chart layout */
.chart-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    margin-bottom: 36px;
}
.chart-row .dash-section { margin-bottom: 0; }
.chart-row .chart-wrap { height: 220px; position: relative; }

/* Table controls */
.table-controls {
    display: flex;
    gap: 8px;
    margin-bottom: 8px;
    align-items: center;
}
.table-controls input,
.table-controls select {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--text);
    font-family: "SF Mono", "Fira Code", Consolas, monospace;
    font-size: 12px;
    padding: 5px 10px;
    outline: none;
    transition: border-color 0.15s;
}
.table-controls input { flex: 1; min-width: 0; }
.table-controls input::placeholder { color: var(--text-muted); }
.table-controls input:focus,
.table-controls select:focus { border-color: var(--accent); }
.table-controls select { cursor: pointer; }

/* Pagination */
.pagination {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    border-top: 1px solid var(--border);
    font-size: 12px;
    color: var(--text-muted);
    font-family: "SF Mono", "Fira Code", Consolas, monospace;
}
.pag-btn {
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--text);
    cursor: pointer;
    font-family: "SF Mono", "Fira Code", Consolas, monospace;
    font-size: 12px;
    padding: 3px 10px;
    transition: border-color 0.15s;
}
.pag-btn:hover:not(:disabled) { border-color: var(--text-muted); color: var(--text-heading); }
.pag-btn:disabled { opacity: 0.35; cursor: default; }
.pag-info { flex: 1; text-align: center; }

@media (max-width: 700px) {
    .chart-row { grid-template-columns: 1fr; }
}
@media (max-width: 600px) {
    .stats-bar { grid-template-columns: repeat(2, 1fr); }
}
"""

_HEADER = """<header>
  <a href="index.html" class="site-title">
    <span class="callsign">AIR PICTURE</span>
    <span class="sep">&middot;</span>
    <span class="location">CHAGRIN FALLS, OH &middot; 41.43&deg;N 81.40&deg;W</span>
  </a>
  <nav class="site-nav">
    <a href="dashboard.html">Dashboard</a>
  </nav>
</header>"""

_FOOTER = """<footer>
  <p>ADS-B ground station &mdash; Chagrin Falls, Ohio</p>
</footer>"""

# ── Helpers ────────────────────────────────────────────────────────────────────

def _badge_class(anomaly_type: str) -> str:
    t = anomaly_type.lower()
    if "military" in t or "restricted" in t:
        return "badge-danger"
    if "unusual" in t or "low" in t:
        return "badge-warn"
    return "badge-info"


def _interpolate_colors(counts: list) -> list:
    """Return per-bar color strings interpolated from chart-2 blue (low) to chart-1 green (high)."""
    if not counts:
        return []
    lo, hi = min(counts), max(counts)
    span = hi - lo or 1
    low_rgb, high_rgb = (88, 166, 255), (63, 185, 80)
    def _lerp(c):
        t = (c - lo) / span
        ch = tuple(int(a + t * (b - a)) for a, b in zip(low_rgb, high_rgb))
        return f"rgb({ch[0]},{ch[1]},{ch[2]})"
    return [_lerp(c) for c in counts]


def _fmt_date(iso: str) -> str:
    """Format an ISO timestamp or date string as 'May 7'."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%b %-d")
    except (ValueError, AttributeError):
        return iso[:10]


def _fmt_date_only(iso: str) -> str:
    """Return just the YYYY-MM-DD portion."""
    try:
        return iso[:10]
    except (TypeError, AttributeError):
        return "—"


def _fmt_alt(value) -> str:
    if value is None:
        return "—"
    try:
        return f"{int(value):,} ft"
    except (ValueError, TypeError):
        return "—"


def _page(title: str, body: str) -> str:
    safe_title = html_mod.escape(title)
    return (
        f'<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        f'  <meta charset="UTF-8">\n'
        f'  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'  <title>{safe_title}</title>\n'
        f'  <style>{_CSS}</style>\n'
        f'  <script src="chart.min.js"></script>\n'
        f'</head>\n<body>\n'
        f'{_HEADER}\n'
        f'<main>{body}</main>\n'
        f'{_FOOTER}\n'
        f'</body>\n</html>'
    )


def _no_data_page() -> str:
    body = '<div class="no-data" style="margin-top:60px;">No data available yet.</div>'
    return _page("Air Picture — Analytics Dashboard", body)


# ── Query functions ────────────────────────────────────────────────────────────

def query_summary_stats() -> dict:  # pylint: disable=too-many-locals
    """Return dict of top-level summary numbers."""
    lookback = f"-{LOOKBACK_DAYS} days"
    with db.get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) as n FROM flights WHERE scan_time >= date('now', ?)",
            (lookback,),
        ).fetchone()["n"]

        unique = conn.execute(
            "SELECT COUNT(DISTINCT icao_hex) as n FROM flights WHERE scan_time >= date('now', ?)",
            (lookback,),
        ).fetchone()["n"]

        anomaly_count = conn.execute(
            "SELECT COUNT(*) as n FROM anomalies WHERE detected_at >= date('now', ?)",
            (lookback,),
        ).fetchone()["n"]

        busiest = conn.execute(
            "SELECT date(scan_time) as day, COUNT(*) as cnt FROM flights "
            "GROUP BY day ORDER BY cnt DESC LIMIT 1",
        ).fetchone()

    return {
        "total_flights": total,
        "unique_aircraft": unique,
        "anomaly_count": anomaly_count,
        "busiest_date": busiest["day"] if busiest else None,
        "busiest_count": busiest["cnt"] if busiest else 0,
    }


def query_daily_traffic() -> tuple:
    """Return (date_labels, flight_counts, anomaly_counts_by_date)."""
    with db.get_conn() as conn:
        flight_rows = conn.execute(
            "SELECT date(scan_time) as day, COUNT(*) as cnt FROM flights "
            "WHERE scan_time >= date('now', ?) "
            "GROUP BY day ORDER BY day ASC",
            (f"-{LOOKBACK_DAYS} days",),
        ).fetchall()

        anomaly_rows = conn.execute(
            "SELECT date(detected_at) as day, COUNT(*) as cnt FROM anomalies "
            "WHERE detected_at >= date('now', ?) "
            "GROUP BY day ORDER BY day ASC",
            (f"-{LOOKBACK_DAYS} days",),
        ).fetchall()

    anomaly_by_day = {r["day"]: r["cnt"] for r in anomaly_rows}

    labels = []
    flight_counts = []
    anomaly_counts = []
    for row in flight_rows:
        day = row["day"]
        labels.append(_fmt_date(day))
        flight_counts.append(row["cnt"])
        anomaly_counts.append(anomaly_by_day.get(day, 0))

    return labels, flight_counts, anomaly_counts


def query_hourly_activity() -> tuple:
    """Return (hour_labels, counts) for hours 0–23."""
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT CAST(strftime('%H', scan_time) AS INTEGER) as hour, "
            "COUNT(*) as cnt FROM flights GROUP BY hour ORDER BY hour ASC",
        ).fetchall()

    by_hour = {r["hour"]: r["cnt"] for r in rows}
    labels = [f"{h:02d}" for h in range(24)]
    counts = [by_hour.get(h, 0) for h in range(24)]
    return labels, counts


def query_top_callsigns(limit: int = 25) -> list:
    """Return list of callsign stat dicts."""
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT callsign, COUNT(*) as appearances, "
            "MIN(scan_time) as first_seen, MAX(scan_time) as last_seen, "
            "AVG(altitude_ft) as avg_altitude "
            "FROM flights WHERE callsign IS NOT NULL AND callsign != '' "
            "GROUP BY callsign ORDER BY appearances DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def query_anomalies(days: int = LOOKBACK_DAYS, limit: int = ANOMALY_DISPLAY_LIMIT) -> list:
    """Return list of recent anomaly dicts, newest first, capped at limit."""
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT detected_at, callsign, icao_hex, anomaly_type, description, altitude_ft "
            "FROM anomalies WHERE detected_at >= date('now', ?) "
            "ORDER BY detected_at DESC LIMIT ?",
            (f"-{days} days", limit),
        ).fetchall()
    return [dict(r) for r in rows]


def query_anomaly_total(days: int = LOOKBACK_DAYS) -> int:
    """Return total anomaly count in the window (may exceed display limit)."""
    with db.get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) as n FROM anomalies WHERE detected_at >= date('now', ?)",
            (f"-{days} days",),
        ).fetchone()["n"]


def query_altitude_distribution() -> tuple:
    """Return (band_labels, counts) in ascending altitude order."""
    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT
                CASE
                    WHEN altitude_ft < 1000  THEN '0–1k'
                    WHEN altitude_ft < 5000  THEN '1k–5k'
                    WHEN altitude_ft < 10000 THEN '5k–10k'
                    WHEN altitude_ft < 18000 THEN '10k–18k'
                    WHEN altitude_ft < 30000 THEN '18k–30k'
                    WHEN altitude_ft < 45000 THEN '30k–45k'
                    ELSE '45k+'
                END as band,
                COUNT(*) as cnt,
                MIN(altitude_ft) as min_alt
            FROM flights WHERE altitude_ft IS NOT NULL
            GROUP BY band ORDER BY min_alt""",
        ).fetchall()
    labels = [r["band"] for r in rows]
    counts = [r["cnt"] for r in rows]
    return labels, counts


# ── HTML section builders ──────────────────────────────────────────────────────

def build_stats_bar(stats: dict) -> str:
    """Render the four top-level summary stat tiles."""
    anomaly_class = "danger" if stats["anomaly_count"] > 10 else ""
    busiest_label = "—"
    if stats["busiest_date"]:
        busiest_label = _fmt_date(stats["busiest_date"])
        busiest_sub = f'{stats["busiest_count"]:,} flights'

    def tile(value: str, label: str, sub: str = "", extra_class: str = "") -> str:
        cls = f'stat-value {extra_class}'.strip()
        sub_html = f'<div class="stat-sub">{html_mod.escape(sub)}</div>' if sub else ""
        return (
            f'<div class="stat-tile">'
            f'<div class="{cls}">{html_mod.escape(str(value))}</div>'
            f'<div class="stat-label">{html_mod.escape(label)}</div>'
            f'{sub_html}'
            f'</div>'
        )

    return (
        '<div class="stats-bar">'
        + tile(f'{stats["total_flights"]:,}', f"Total Flights ({LOOKBACK_DAYS}d)")
        + tile(f'{stats["unique_aircraft"]:,}', f"Unique Aircraft ({LOOKBACK_DAYS}d)")
        + tile(f'{stats["anomaly_count"]:,}', f"Total Anomalies ({LOOKBACK_DAYS}d)", extra_class=anomaly_class)
        + tile(busiest_label, "Busiest Day (all-time)", sub=busiest_sub)
        + "</div>"
    )


def build_daily_traffic_chart(labels: list, flights: list, anomalies: list) -> str:
    """Render the daily traffic bar chart with anomaly overlay."""
    labels_j = json.dumps(labels)
    flights_j = json.dumps(flights)
    anomalies_j = json.dumps(anomalies)
    return f"""<div class="dash-section">
  <h2>Daily Traffic &mdash; Last {LOOKBACK_DAYS} Days</h2>
  <div class="chart-wrap">
    <canvas id="dailyChart" height="220"></canvas>
  </div>
</div>
<script>
(function() {{
  var ctx = document.getElementById('dailyChart');
  new Chart(ctx, {{
    type: 'bar',
    data: {{
      labels: {labels_j},
      datasets: [
        {{
          label: 'Flights',
          data: {flights_j},
          backgroundColor: 'rgba(63,185,80,0.7)',
          borderColor: 'rgba(63,185,80,1)',
          borderWidth: 1,
          order: 2,
          yAxisID: 'y'
        }},
        {{
          label: 'Anomalies',
          type: 'line',
          data: {anomalies_j},
          borderColor: 'rgba(210,153,34,0.9)',
          backgroundColor: 'rgba(210,153,34,0.15)',
          pointBackgroundColor: 'rgba(210,153,34,1)',
          pointRadius: 4,
          borderWidth: 2,
          order: 1,
          yAxisID: 'y2'
        }}
      ]
    }},
    options: {{
      responsive: true,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ display: false }}
      }},
      scales: {{
        x: {{
          ticks: {{ color: '#6e7681', font: {{ family: '"SF Mono","Fira Code",Consolas,monospace', size: 11 }} }},
          grid: {{ color: '#21262d' }}
        }},
        y: {{
          position: 'left',
          ticks: {{ color: '#6e7681', font: {{ family: '"SF Mono","Fira Code",Consolas,monospace', size: 11 }} }},
          grid: {{ color: '#21262d' }}
        }},
        y2: {{
          position: 'right',
          ticks: {{ color: '#d29922', font: {{ family: '"SF Mono","Fira Code",Consolas,monospace', size: 11 }} }},
          grid: {{ drawOnChartArea: false }}
        }}
      }}
    }}
  }});
}})();
</script>"""


def build_hourly_chart(labels: list, counts: list) -> str:
    """Render the hourly activity bar chart with gradient coloring."""
    labels_j = json.dumps(labels)
    counts_j = json.dumps(counts)
    colors_j = json.dumps(_interpolate_colors(counts))
    return f"""<div class="dash-section">
  <h2>Activity by Hour of Day (all-time)</h2>
  <div class="chart-wrap">
    <canvas id="hourlyChart"></canvas>
  </div>
</div>
<script>
(function() {{
  var ctx = document.getElementById('hourlyChart');
  new Chart(ctx, {{
    type: 'bar',
    data: {{
      labels: {labels_j},
      datasets: [{{
        data: {counts_j},
        backgroundColor: {colors_j},
        borderWidth: 0
      }}]
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{ legend: {{ display: false }} }},
      scales: {{
        x: {{
          ticks: {{ color: '#6e7681', font: {{ family: '"SF Mono","Fira Code",Consolas,monospace', size: 11 }} }},
          grid: {{ color: '#21262d' }}
        }},
        y: {{
          ticks: {{ color: '#6e7681', font: {{ family: '"SF Mono","Fira Code",Consolas,monospace', size: 11 }} }},
          grid: {{ color: '#21262d' }}
        }}
      }}
    }}
  }});
}})();
</script>"""


def build_callsigns_table(rows: list) -> str:
    """Render the top-25 callsigns table with live search."""
    if not rows:
        return (
            '<div class="dash-section"><h2>Top Callsigns</h2>'
            '<div class="table-wrap"><div class="no-data">No callsign data available.</div></div></div>'
        )
    header = (
        '<tr>'
        '<th data-col="0">Callsign</th>'
        '<th data-col="1" class="right">Appearances</th>'
        '<th data-col="2">First Seen</th>'
        '<th data-col="3">Last Seen</th>'
        '<th data-col="4" class="right">Avg Altitude</th>'
        '</tr>'
    )
    body_rows = []
    for r in rows:
        cs = html_mod.escape(r["callsign"] or "—")
        appearances = r["appearances"]
        first = _fmt_date_only(r.get("first_seen") or "")
        last = _fmt_date_only(r.get("last_seen") or "")
        avg_alt = _fmt_alt(r.get("avg_altitude"))
        body_rows.append(
            f'<tr>'
            f'<td class="mono accent">{cs}</td>'
            f'<td class="right" data-num="{appearances}">{appearances:,}</td>'
            f'<td class="muted mono">{html_mod.escape(first)}</td>'
            f'<td class="muted mono">{html_mod.escape(last)}</td>'
            f'<td class="muted right" data-num="{r.get("avg_altitude") or 0}">'
            f'{html_mod.escape(avg_alt)}</td>'
            f'</tr>'
        )
    return (
        '<div class="dash-section"><h2>Top Callsigns (all-time, top 25)</h2>'
        '<div class="table-controls">'
        '<input type="text" id="csSearch" placeholder="Filter by callsign, date, or altitude…" autocomplete="off">'
        '</div>'
        '<div class="table-wrap">'
        f'<table class="dash-table" id="callsignsTable">'
        f'<thead>{header}</thead>'
        f'<tbody>{"".join(body_rows)}</tbody>'
        f'</table></div></div>'
    )


def _anomaly_row(r: dict) -> str:
    """Render a single anomaly table row."""
    ts_full = html_mod.escape((r.get("detected_at") or "")[:16].replace("T", " "))
    cs_raw = r.get("callsign") or ""
    cs = f'<span class="accent">{html_mod.escape(cs_raw)}</span>' if cs_raw else "&mdash;"
    icao = html_mod.escape(r.get("icao_hex") or "—")
    atype = r.get("anomaly_type") or ""
    badge = f'<span class="badge {_badge_class(atype)}">{html_mod.escape(atype)}</span>'
    desc = html_mod.escape(r.get("description") or "")
    alt = _fmt_alt(r.get("altitude_ft"))
    return (
        f'<tr data-atype="{html_mod.escape(atype)}">'
        f'<td class="muted mono">{ts_full}</td>'
        f'<td class="mono">{cs}</td>'
        f'<td class="muted mono">{icao}</td>'
        f'<td>{badge}</td>'
        f'<td style="max-width:320px;font-size:12px;">{desc}</td>'
        f'<td class="muted right" data-num="{r.get("altitude_ft") or 0}">{html_mod.escape(alt)}</td>'
        f'</tr>'
    )


def build_anomaly_table(rows: list, total: int = 0, unique_types: list = ()) -> str:
    """Render the anomaly log with search, type filter, and pagination."""
    if not rows:
        return (
            '<div class="dash-section"><h2>Anomaly Log</h2>'
            '<div class="table-wrap">'
            f'<div class="no-data">No anomalies detected in the last {LOOKBACK_DAYS} days.</div>'
            '</div></div>'
        )
    showing = len(rows)
    cap_note = (
        f' <span style="font-weight:400;color:var(--text-muted);font-size:11px;text-transform:none;'
        f'letter-spacing:0;">(latest {showing:,} of {total:,} total)</span>'
        if total > showing else ""
    )

    type_options = '<option value="">All types</option>'
    for t in sorted(unique_types):
        escaped = html_mod.escape(t)
        type_options += f'<option value="{escaped}">{escaped}</option>'

    header = (
        '<tr>'
        '<th data-col="0">Timestamp</th>'
        '<th data-col="1">Callsign</th>'
        '<th data-col="2">ICAO Hex</th>'
        '<th data-col="3">Type</th>'
        '<th data-col="4">Description</th>'
        '<th data-col="5" class="right">Altitude</th>'
        '</tr>'
    )
    body_rows = [_anomaly_row(r) for r in rows]
    return (
        f'<div class="dash-section">'
        f'<h2>Anomaly Log &mdash; Last {LOOKBACK_DAYS} Days{cap_note}</h2>'
        '<div class="table-controls">'
        '<input type="text" id="anomSearch" placeholder="Search callsign, ICAO, description…" autocomplete="off">'
        f'<select id="anomTypeFilter">{type_options}</select>'
        '</div>'
        '<div class="table-wrap">'
        f'<table class="dash-table" id="anomalyTable">'
        f'<thead>{header}</thead>'
        f'<tbody>{"".join(body_rows)}</tbody>'
        f'</table>'
        '<div id="anomPagination" class="pagination">'
        '<button class="pag-btn pag-prev" disabled>&larr; Prev</button>'
        '<span class="pag-info"></span>'
        '<button class="pag-btn pag-next">Next &rarr;</button>'
        '</div>'
        '</div></div>'
    )


def build_altitude_chart(labels: list, counts: list) -> str:
    """Render the horizontal altitude distribution bar chart."""
    if not labels:
        return (
            '<div class="dash-section"><h2>Altitude Distribution (all-time)</h2>'
            '<div class="table-wrap"><div class="no-data">No altitude data available.</div></div></div>'
        )
    labels_j = json.dumps(labels)
    counts_j = json.dumps(counts)
    return f"""<div class="dash-section">
  <h2>Altitude Distribution (all-time)</h2>
  <div class="chart-wrap">
    <canvas id="altChart"></canvas>
  </div>
</div>
<script>
(function() {{
  var ctx = document.getElementById('altChart');
  new Chart(ctx, {{
    type: 'bar',
    data: {{
      labels: {labels_j},
      datasets: [{{
        data: {counts_j},
        backgroundColor: 'rgba(88,166,255,0.7)',
        borderColor: 'rgba(88,166,255,1)',
        borderWidth: 1
      }}]
    }},
    options: {{
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{ legend: {{ display: false }} }},
      scales: {{
        x: {{
          ticks: {{ color: '#6e7681', font: {{ family: '"SF Mono","Fira Code",Consolas,monospace', size: 11 }} }},
          grid: {{ color: '#21262d' }}
        }},
        y: {{
          ticks: {{ color: '#6e7681', font: {{ family: '"SF Mono","Fira Code",Consolas,monospace', size: 11 }} }},
          grid: {{ color: '#21262d' }}
        }}
      }}
    }}
  }});
}})();
</script>"""


_TABLE_JS = """
<script>
function createTableController(cfg) {
  var table = document.getElementById(cfg.tableId);
  if (!table) return;
  var tbody   = table.querySelector('tbody');
  var allRows = Array.from(tbody.querySelectorAll('tr'));
  var headers = Array.from(table.querySelectorAll('thead th'));
  var page    = 0;
  var perPage = cfg.rowsPerPage || 1e9;
  var sortCol = -1, sortAsc = true;

  function getQ() {
    var el = cfg.searchId && document.getElementById(cfg.searchId);
    return el ? el.value.toLowerCase().trim() : '';
  }
  function getSel() {
    var el = cfg.typeSelectId && document.getElementById(cfg.typeSelectId);
    return el ? el.value : '';
  }
  function getFiltered() {
    var q = getQ(), sel = getSel();
    return allRows.filter(function(row) {
      var matchQ   = !q   || row.textContent.toLowerCase().includes(q);
      var matchSel = !sel || (row.dataset.atype || '') === sel;
      return matchQ && matchSel;
    });
  }
  function render() {
    var rows  = getFiltered();
    var total = rows.length;
    var start = page * perPage;
    allRows.forEach(function(r) { r.style.display = 'none'; });
    rows.slice(start, start + perPage).forEach(function(r) { r.style.display = ''; });

    var pEl = cfg.paginationId && document.getElementById(cfg.paginationId);
    if (pEl) {
      var totalPages = Math.max(1, Math.ceil(total / perPage));
      var from = total === 0 ? 0 : start + 1;
      var to   = Math.min(start + perPage, total);
      pEl.querySelector('.pag-info').textContent =
        total === 0 ? 'No results' : from + '–' + to + ' of ' + total;
      pEl.querySelector('.pag-prev').disabled = page === 0;
      pEl.querySelector('.pag-next').disabled = page >= totalPages - 1;
    }
  }
  function reset() { page = 0; render(); }

  // Column sort
  headers.forEach(function(th, idx) {
    th.addEventListener('click', function() {
      sortCol === idx ? (sortAsc = !sortAsc) : (sortCol = idx, sortAsc = true);
      headers.forEach(function(h) { h.classList.remove('sort-asc', 'sort-desc'); });
      th.classList.add(sortAsc ? 'sort-asc' : 'sort-desc');
      allRows.sort(function(a, b) {
        var ac = a.querySelectorAll('td')[idx];
        var bc = b.querySelectorAll('td')[idx];
        var an = ac && ac.dataset.num !== undefined ? parseFloat(ac.dataset.num) : NaN;
        var bn = bc && bc.dataset.num !== undefined ? parseFloat(bc.dataset.num) : NaN;
        var av, bv;
        if (!isNaN(an) && !isNaN(bn)) { av = an; bv = bn; }
        else {
          av = (ac ? ac.textContent.trim() : '').toLowerCase();
          bv = (bc ? bc.textContent.trim() : '').toLowerCase();
        }
        return (av < bv ? -1 : av > bv ? 1 : 0) * (sortAsc ? 1 : -1);
      });
      allRows.forEach(function(r) { tbody.appendChild(r); });
      reset();
    });
  });

  // Search
  var sEl = cfg.searchId && document.getElementById(cfg.searchId);
  if (sEl) sEl.addEventListener('input', reset);

  // Type filter
  var tEl = cfg.typeSelectId && document.getElementById(cfg.typeSelectId);
  if (tEl) tEl.addEventListener('change', reset);

  // Pagination buttons
  var pEl = cfg.paginationId && document.getElementById(cfg.paginationId);
  if (pEl) {
    pEl.querySelector('.pag-prev').addEventListener('click', function() {
      if (page > 0) { page--; render(); }
    });
    pEl.querySelector('.pag-next').addEventListener('click', function() {
      var totalPages = Math.max(1, Math.ceil(getFiltered().length / perPage));
      if (page < totalPages - 1) { page++; render(); }
    });
  }

  render();
}

createTableController({ tableId: 'callsignsTable', searchId: 'csSearch' });
createTableController({
  tableId: 'anomalyTable',
  searchId: 'anomSearch',
  typeSelectId: 'anomTypeFilter',
  paginationId: 'anomPagination',
  rowsPerPage: 25
});
</script>
"""

# ── Entry point ────────────────────────────────────────────────────────────────

def _page_header(ts: str) -> str:
    """Render the dashboard page header with back-link and build timestamp."""
    return (
        '<div class="page-header">'
        '<p style="margin-bottom:10px;"><a href="index.html">&larr; All Briefings</a></p>'
        '<h1>Air Picture &mdash; Analytics Dashboard</h1>'
        f'<p>14-day overview &middot; updated {html_mod.escape(ts)}</p>'
        '</div>'
    )


def build() -> None:  # pylint: disable=too-many-locals
    """Query DB, assemble dashboard HTML, write docs/dashboard.html."""
    print("[dashboard] Building analytics dashboard…")
    OUT_DIR.mkdir(exist_ok=True)
    out_path = OUT_DIR / "dashboard.html"

    try:
        print("[dashboard] Querying summary stats…")
        stats = query_summary_stats()

        print("[dashboard] Querying daily traffic…")
        d_labels, d_flights, d_anomalies = query_daily_traffic()

        print("[dashboard] Querying hourly activity…")
        h_labels, h_counts = query_hourly_activity()

        print("[dashboard] Querying top callsigns…")
        callsigns = query_top_callsigns()

        print("[dashboard] Querying anomalies…")
        anomalies = query_anomalies()
        anomaly_total = query_anomaly_total()

        print("[dashboard] Querying altitude distribution…")
        alt_labels, alt_counts = query_altitude_distribution()

    except Exception as exc:  # pylint: disable=broad-exception-caught
        print(f"[dashboard] DB error: {exc} — writing empty dashboard.")
        out_path.write_text(_no_data_page(), encoding="utf-8")
        return

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    unique_types = sorted({a["anomaly_type"] for a in anomalies if a.get("anomaly_type")})

    charts_row = (
        '<div class="chart-row">'
        + build_hourly_chart(h_labels, h_counts)
        + build_altitude_chart(alt_labels, alt_counts)
        + '</div>'
    )

    body = (
        _page_header(ts)
        + build_stats_bar(stats)
        + build_daily_traffic_chart(d_labels, d_flights, d_anomalies)
        + charts_row
        + build_callsigns_table(callsigns)
        + build_anomaly_table(anomalies, total=anomaly_total, unique_types=unique_types)
        + _TABLE_JS
    )

    html = _page("Air Picture — Analytics Dashboard", body)
    out_path.write_text(html, encoding="utf-8")
    print(f"[dashboard] Written → {out_path}")


if __name__ == "__main__":
    build()
