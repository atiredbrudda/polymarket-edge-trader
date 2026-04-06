"""Serve command — localhost dashboard for Q5 traders and active signals.

Starts an HTTP server on http://localhost:8080 (configurable).
The page polls /api/last-modified every 2s and re-renders when the DB changes,
so it updates automatically as soon as you re-run the pipeline.

Usage:
    polymarket --niche esports serve [--db-path PATH] [--port PORT]
"""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import click

from polymarket_analytics.cli import cli
from polymarket_analytics.db.schema import init_database

# ── HTML page ──────────────────────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Polymarket Smart Money</title>
<style>
  :root {
    --bg: #0d0d0d;
    --surface: #161616;
    --border: #2a2a2a;
    --text: #e8e8e8;
    --dim: #777;
    --cyan: #5fd7ff;
    --green: #5fff87;
    --red: #ff5f5f;
    --yellow: #ffd75f;
    --accent: #875fff;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace; font-size: 13px; }
  header { padding: 18px 28px 14px; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 16px; }
  header h1 { font-size: 15px; font-weight: 600; color: var(--cyan); letter-spacing: 0.05em; }
  #status { font-size: 11px; color: var(--dim); margin-left: auto; }
  #live-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: var(--green); margin-right: 5px; animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
  main { padding: 24px 28px; display: flex; flex-direction: column; gap: 36px; }

  section h2 { font-size: 12px; font-weight: 600; color: var(--dim); letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 12px; }

  table { width: 100%; border-collapse: collapse; }
  th { text-align: right; color: var(--dim); font-weight: 500; font-size: 11px; letter-spacing: 0.08em; padding: 6px 12px; border-bottom: 1px solid var(--border); }
  th:first-child, th:nth-child(2) { text-align: left; }
  td { padding: 6px 12px; border-bottom: 1px solid #1c1c1c; text-align: right; }
  td:first-child { text-align: right; color: var(--dim); width: 36px; }
  td:nth-child(2) { text-align: left; color: var(--cyan); font-size: 12px; font-family: monospace; }
  tr:hover td { background: #1a1a1a; }

  .pos { color: var(--green); }
  .neg { color: var(--red); }

  .signals-list { display: flex; flex-direction: column; gap: 16px; }
  .signal-card { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 16px 20px; }
  .signal-header { display: flex; align-items: baseline; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
  .signal-question { font-size: 13px; font-weight: 500; color: var(--text); flex: 1; min-width: 200px; }
  .badge { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 3px; letter-spacing: 0.05em; }
  .badge-long  { background: #1a3a1a; color: var(--green); border: 1px solid #2a5a2a; }
  .badge-short { background: #3a1a1a; color: var(--red);   border: 1px solid #5a2a2a; }
  .signal-meta { font-size: 11px; color: var(--dim); display: flex; gap: 16px; flex-wrap: wrap; }
  .signal-meta span b { color: var(--text); }
  .market-id { font-size: 10px; color: #444; margin-top: 4px; font-family: monospace; word-break: break-all; }
  .contrib-table { margin-top: 12px; }
  .contrib-table th { font-size: 10px; }
  .contrib-table td:nth-child(2) { font-size: 11px; }
  .no-data { color: var(--dim); font-size: 12px; padding: 40px; text-align: center; }
  .section-label { font-size: 11px; font-weight: 600; color: var(--dim); letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 10px; margin-top: 4px; }
  .live-label { color: var(--yellow); margin-top: 24px; }
  .event-title { font-size: 11px; color: var(--accent); font-weight: 500; margin-bottom: 6px; }
</style>
</head>
<body>
<header>
  <h1>=== Polymarket Smart Money Tracker ===</h1>
  <span id="status"><span id="live-dot"></span>live &mdash; <span id="updated">loading...</span></span>
</header>
<main id="main"><p class="no-data">Loading...</p></main>

<script>
let lastMtime = null;
const NICHE = document.currentScript ? '' : '';

function fmt(v, decimals=4) {
  if (v === null || v === undefined) return '—';
  return Number(v).toFixed(decimals);
}

function pnlClass(v) {
  if (v === null || v === undefined) return '';
  return Number(v) >= 0 ? 'pos' : 'neg';
}

function renderTraders(traders) {
  if (!traders || traders.length === 0) return '<p class="no-data">No Q5 traders found. Run the scoring pipeline first.</p>';
  const rows = traders.map((t, i) => `
    <tr>
      <td>${i+1}</td>
      <td>${t.trader_address}</td>
      <td>${fmt(t.composite_score)}</td>
      <td>${fmt(t.clv_raw)}</td>
      <td>${fmt(t.roi_raw)}</td>
      <td>${fmt(t.sharpe_raw)}</td>
      <td>${t.position_count ?? '—'}</td>
      <td class="${pnlClass(t.total_pnl)}">${fmt(t.total_pnl)}</td>
    </tr>`).join('');
  return `
    <table>
      <thead><tr>
        <th>#</th><th>Address</th><th>Score</th><th>CLV</th><th>ROI</th><th>Sharpe</th><th>Positions</th><th>PnL</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function signalCard(s) {
  const badgeClass = s.direction === 'LONG' ? 'badge-long' : 'badge-short';
  const eventPrefix = s.event_title ? `<div class="event-title">${s.event_title}</div>` : '';
  const contribs = s.contributors && s.contributors.length ? `
    <table class="contrib-table">
      <thead><tr><th style="text-align:left">#</th><th style="text-align:left">Address</th><th>Score</th><th>Size</th><th>Avg Entry</th></tr></thead>
      <tbody>${s.contributors.map((c,i) => `
        <tr>
          <td>${i+1}</td>
          <td>${c.trader_address}</td>
          <td>${fmt(c.composite_score)}</td>
          <td>${fmt(c.size)}</td>
          <td>${fmt(c.avg_entry_price)}</td>
        </tr>`).join('')}
      </tbody>
    </table>` : '<p style="color:var(--dim);font-size:11px;margin-top:8px">(no contributor detail)</p>';
  return `
    <div class="signal-card">
      ${eventPrefix}
      <div class="signal-header">
        <span class="signal-question">${s.question}</span>
        <span class="badge ${badgeClass}">${s.direction}</span>
      </div>
      <div class="signal-meta">
        <span>Q5 traders: <b>${s.q5_count}</b></span>
        <span>Avg score: <b>${fmt(s.avg_score)}</b></span>
        ${s.tier ? `<span>Tier: <b style="color:var(--yellow)">${s.tier}</b></span>` : ''}
        ${s.clv_dominant_count !== null && s.clv_dominant_count !== undefined ? `<span>CLV dominant: <b>${s.clv_dominant_count}</b></span>` : ''}
        ${s.avg_entry_price !== null && s.avg_entry_price !== undefined ? `<span>Avg entry: <b>${fmt(s.avg_entry_price, 3)}</b></span>` : ''}
        ${s.min_entry_price !== null && s.min_entry_price !== undefined ? `<span>Min entry: <b>${fmt(s.min_entry_price, 3)}</b></span>` : ''}
      </div>
      <div class="market-id">${s.market_id}</div>
      ${contribs}
    </div>`;
}

function renderSignals(signals) {
  if (!signals || signals.length === 0) return '<p class="no-data">No signals detected. Run detect.</p>';
  const upcoming = signals.filter(s => s.status === 'upcoming');
  const live     = signals.filter(s => s.status === 'live');
  let html = '';
  if (upcoming.length) {
    html += `<h3 class="section-label">Upcoming (${upcoming.length})</h3><div class="signals-list">${upcoming.map(signalCard).join('')}</div>`;
  }
  if (live.length) {
    html += `<h3 class="section-label live-label">Live / Settling (${live.length})</h3><div class="signals-list">${live.map(signalCard).join('')}</div>`;
  }
  return html;
}

function render(data) {
  const main = document.getElementById('main');
  main.innerHTML = `
    <section>
      <h2>Q5 Traders &mdash; ${data.niche} &nbsp;(${(data.traders||[]).length} total)</h2>
      ${renderTraders(data.traders)}
    </section>
    <section>
      <h2>Active Signals &mdash; ${(data.signals||[]).length} total</h2>
      ${renderSignals(data.signals)}
    </section>`;
  document.getElementById('updated').textContent = 'updated ' + new Date().toLocaleTimeString();
}

async function fetchData() {
  const r = await fetch('/api/data');
  const data = await r.json();
  render(data);
}

async function poll() {
  try {
    const r = await fetch('/api/last-modified');
    const { mtime } = await r.json();
    if (mtime !== lastMtime) {
      lastMtime = mtime;
      await fetchData();
    }
  } catch(e) { /* server not ready */ }
}

fetchData();
setInterval(poll, 2000);
</script>
</body>
</html>
"""


# ── Data queries ───────────────────────────────────────────────────────────────

def _get_data(db, niche_slug: str) -> dict:
    traders = [
        {
            "trader_address": row[0],
            "composite_score": row[1],
            "clv_raw": row[2],
            "roi_raw": row[3],
            "sharpe_raw": row[4],
            "position_count": row[5],
            "total_pnl": row[6],
        }
        for row in db.execute(
            """
            SELECT trader_address, composite_score, clv_raw, roi_raw,
                   sharpe_raw, position_count, total_pnl
            FROM q5_traders
            WHERE category = :niche_slug
            ORDER BY composite_score DESC
            """,
            {"niche_slug": niche_slug},
        )
    ]

    cutoff_rows = list(db.execute(
        "SELECT MAX(computed_at) FROM lift_scores WHERE category = :niche_slug",
        {"niche_slug": niche_slug},
    ))
    cutoff = cutoff_rows[0][0] if cutoff_rows else None

    signals_raw = list(db.execute(
        """
        SELECT s.market_id, s.direction, s.q5_count, s.avg_score,
               COALESCE(m.question, s.market_id) AS question,
               m.event_title,
               CASE WHEN datetime(m.end_date) > datetime('now', '+5 hours') THEN 'upcoming' ELSE 'live' END AS status,
               s.clv_dominant_count, s.avg_entry_price, s.min_entry_price, s.tier
        FROM signals s
        LEFT JOIN markets m ON m.condition_id = s.market_id
        WHERE (m.end_date IS NULL OR datetime(m.end_date) > datetime('now'))
        ORDER BY status ASC, s.avg_score DESC
        """
    ))

    signals = []
    for market_id, direction, q5_count, avg_score, question, event_title, status, clv_dominant_count, avg_entry_price, min_entry_price, tier in signals_raw:
        contributors = [
            {
                "trader_address": r[0],
                "composite_score": r[1],
                "size": r[2],
                "avg_entry_price": r[3],
            }
            for r in db.execute(
                """
                SELECT p.trader_address, ls.composite_score, p.size, p.avg_entry_price
                FROM positions p
                JOIN lift_scores ls ON ls.trader_address = p.trader_address
                WHERE p.market_id = :market_id
                  AND p.direction = :direction
                  AND p.resolved = 0
                  AND p.size > 0
                  AND ls.quintile = 5
                  AND ls.category = :niche_slug
                  AND ls.computed_at = :cutoff
                ORDER BY ls.composite_score DESC
                """,
                {"market_id": market_id, "direction": direction,
                 "niche_slug": niche_slug, "cutoff": cutoff},
            )
        ]
        # Show event_title as prefix when it differs from question
        display_title = question
        if event_title and event_title != question:
            display_title = question  # question shown in card body
        signals.append({
            "market_id": market_id,
            "direction": direction,
            "q5_count": q5_count,
            "avg_score": avg_score,
            "question": question,
            "event_title": event_title if event_title and event_title != question else None,
            "status": status,
            "contributors": contributors,
            "clv_dominant_count": clv_dominant_count,
            "avg_entry_price": avg_entry_price,
            "min_entry_price": min_entry_price,
            "tier": tier,
        })

    return {"niche": niche_slug, "traders": traders, "signals": signals}


# ── HTTP handler ───────────────────────────────────────────────────────────────

def make_handler(db_path: Path, niche_slug: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # silence request logs

        def _send(self, code: int, content_type: str, body: bytes):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path

            if path == "/" or path == "":
                self._send(200, "text/html; charset=utf-8", HTML.encode())

            elif path == "/api/last-modified":
                try:
                    mtime = os.path.getmtime(db_path)
                except OSError:
                    mtime = 0
                body = json.dumps({"mtime": mtime}).encode()
                self._send(200, "application/json", body)

            elif path == "/api/data":
                try:
                    db = init_database(db_path)
                    data = _get_data(db, niche_slug)
                except Exception as e:
                    data = {"error": str(e), "niche": niche_slug, "traders": [], "signals": []}
                body = json.dumps(data).encode()
                self._send(200, "application/json", body)

            else:
                self._send(404, "text/plain", b"Not found")

    return Handler


# ── CLI command ────────────────────────────────────────────────────────────────

@cli.command("serve")
@click.option("--db-path", default="data/analytics.db", help="Path to SQLite database")
@click.option("--port", default=8080, help="Port to listen on (default: 8080)")
@click.pass_context
def serve(ctx: Any, db_path: str, port: int) -> None:
    """Start a localhost dashboard for Q5 traders and active signals.

    The page auto-updates whenever the database changes (no manual refresh needed).
    Open http://localhost:{port} in your browser.
    """
    niche = ctx.obj.get("niche", "esports")
    config = ctx.obj.get("config")

    if not config:
        raise click.ClickException(f"No config found for niche: {niche}")

    db_path_obj = Path(db_path)
    handler = make_handler(db_path_obj, niche)
    server = HTTPServer(("localhost", port), handler)

    click.echo(f"=== Polymarket Dashboard ===")
    click.echo(f"  Niche   : {niche}")
    click.echo(f"  DB      : {db_path_obj.resolve()}")
    click.echo(f"  URL     : http://localhost:{port}")
    click.echo(f"  Updates : automatically on DB change")
    click.echo(f"\nPress Ctrl+C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        click.echo("\nStopped.")
        server.server_close()
