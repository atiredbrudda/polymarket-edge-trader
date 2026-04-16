"""Paper trading dashboard command.

Shows portfolio summary, open positions, decision log stats, and recent trades.
Includes account reset and market resolution helpers.

Usage:
    polymarket --niche esports paper-dashboard
    polymarket --niche esports paper-dashboard --serve
    polymarket --niche esports paper-dashboard --serve --port 8080
    polymarket --niche esports paper-dashboard --resolve
    polymarket --niche esports paper-dashboard --reset
"""

import html as _html_module
import sqlite3
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote_plus, urlparse

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from polymarket_analytics.cli import cli

console = Console()

BANKROLL = 10_000.0
LOW_CASH_THRESHOLD = 500.0  # Alert when cash drops below this


# ─── database helpers ────────────────────────────────────────────────────────

def _open_paper_db(paper_data_dir: str) -> sqlite3.Connection:
    db_path = Path(paper_data_dir) / "paper.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


# ─── terminal output ─────────────────────────────────────────────────────────

def _print_account_summary(conn: sqlite3.Connection) -> float:
    """Print account summary panel. Returns current cash."""
    row = conn.execute("SELECT * FROM account WHERE id = 1").fetchone()
    if row is None:
        console.print("[red]No paper account found. Run paper-bridge first.[/red]")
        return 0.0

    cash = row["cash"]
    starting = row["starting_balance"]
    created = row["created_at"]

    # Deployed = total_cost of open (unresolved) positions
    # Cash spent = starting - cash (ground truth, avoids pm_trader total_cost discrepancy)
    deployed = starting - cash

    # Realized P&L from resolved positions
    realized_row = conn.execute(
        "SELECT COALESCE(SUM(realized_pnl), 0) FROM positions WHERE is_resolved = 1"
    ).fetchone()
    realized_pnl = realized_row[0]

    open_count = conn.execute(
        "SELECT COUNT(*) FROM positions WHERE is_resolved = 0 AND shares > 0"
    ).fetchone()[0]

    trades_count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]

    pnl_color = "green" if realized_pnl >= 0 else "red"
    cash_color = "red" if cash < LOW_CASH_THRESHOLD else "white"

    lines = [
        f"Started:   ${starting:>10,.2f}    Created: {created[:10]}",
        f"Cash:      [{cash_color}]${cash:>10,.2f}[/{cash_color}]",
        f"Deployed:  ${deployed:>10,.2f}    (cash spent on open positions)",
        f"Realized:  [{pnl_color}]${realized_pnl:>+10,.2f}[/{pnl_color}]   (resolved positions)",
        f"Positions: {open_count:>10,}    open   |   {trades_count:,} total trades",
    ]

    if cash < LOW_CASH_THRESHOLD:
        lines.append(f"\n[bold red]LOW CASH WARNING: ${cash:.2f} remaining — bet sizing will SKIP_SIZE.[/bold red]")
        lines.append("[bold red]Run with --reset to reinitialize to $10,000.[/bold red]")

    console.print(Panel("\n".join(lines), title="[bold]Account Summary[/bold]", border_style="blue"))
    return cash


def _print_positions(conn: sqlite3.Connection, limit: int = 20) -> None:
    """Print top open positions sorted by cost."""
    rows = conn.execute("""
        SELECT market_question, outcome, shares, avg_entry_price, total_cost, realized_pnl
        FROM positions
        WHERE is_resolved = 0 AND shares > 0
        ORDER BY total_cost DESC
        LIMIT ?
    """, (limit,)).fetchall()

    total_open = conn.execute(
        "SELECT COUNT(*) FROM positions WHERE is_resolved = 0 AND shares > 0"
    ).fetchone()[0]

    resolved_won = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(realized_pnl), 0) FROM positions WHERE is_resolved = 1 AND realized_pnl > 0"
    ).fetchone()
    resolved_lost = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(realized_pnl), 0) FROM positions WHERE is_resolved = 1 AND realized_pnl <= 0"
    ).fetchone()

    table = Table(
        title=f"Open Positions (top {min(limit, total_open)} of {total_open})",
        show_lines=False,
    )
    table.add_column("Market", max_width=42, no_wrap=True)
    table.add_column("Outcome", max_width=12, no_wrap=True)
    table.add_column("Shares", justify="right", no_wrap=True)
    table.add_column("Entry", justify="right", no_wrap=True)
    table.add_column("Cost", justify="right", no_wrap=True)

    for r in rows:
        table.add_row(
            r["market_question"][:42],
            r["outcome"].upper()[:12],
            f"{r['shares']:,.0f}",
            f"{r['avg_entry_price']:.3f}",
            f"${r['total_cost']:.2f}",
        )

    console.print(table)

    # Resolved positions table
    resolved_rows = conn.execute("""
        SELECT market_question, outcome, shares, total_cost, realized_pnl, resolved_at
        FROM positions
        WHERE is_resolved = 1
        ORDER BY resolved_at DESC
        LIMIT ?
    """, (limit,)).fetchall()

    won_count, won_pnl = resolved_won
    lost_count, lost_pnl = resolved_lost
    total_resolved = won_count + lost_count

    if resolved_rows:
        rtable = Table(
            title=f"Resolved Positions (last {len(resolved_rows)} of {total_resolved})",
            show_lines=False,
        )
        rtable.add_column("Market", max_width=42, no_wrap=True)
        rtable.add_column("Outcome", max_width=12, no_wrap=True)
        rtable.add_column("Result", justify="center", no_wrap=True)
        rtable.add_column("Cost", justify="right", no_wrap=True)
        rtable.add_column("P&L", justify="right", no_wrap=True)
        rtable.add_column("Resolved", no_wrap=True)

        for r in resolved_rows:
            pnl = r["realized_pnl"] or 0.0
            if pnl > 0:
                result_str = "[green]WIN[/green]"
                pnl_str = f"[green]+${pnl:.2f}[/green]"
            elif pnl < 0:
                result_str = "[red]LOSS[/red]"
                pnl_str = f"[red]-${abs(pnl):.2f}[/red]"
            else:
                result_str = "[dim]VOID[/dim]"
                pnl_str = "[dim]$0.00[/dim]"

            resolved_at = (r["resolved_at"] or "")[:10]
            rtable.add_row(
                r["market_question"][:42],
                (r["outcome"] or "").upper()[:12],
                result_str,
                f"${r['total_cost']:.2f}",
                pnl_str,
                resolved_at,
            )

        console.print(rtable)

        if total_resolved > 0:
            win_rate = won_count / total_resolved * 100
            console.print(
                f"Resolved: {total_resolved} total  |  "
                f"[green]{won_count} won (+${won_pnl:.2f})[/green]  |  "
                f"[red]{lost_count} lost (${lost_pnl:.2f})[/red]  |  "
                f"Win rate: {win_rate:.0f}%"
            )


def _print_decision_stats(analytics_db_path: str, days: int = 7) -> None:
    """Print bridge decision stats from analytics.db."""
    try:
        aconn = sqlite3.connect(analytics_db_path)
        aconn.row_factory = sqlite3.Row

        rows = aconn.execute("""
            SELECT decision, COUNT(*) as n
            FROM bridge_decisions
            WHERE checked_at >= datetime('now', ?)
            GROUP BY decision
            ORDER BY n DESC
        """, (f"-{days} days",)).fetchall()

        if not rows:
            aconn.close()
            return

        table = Table(title=f"Bridge Decisions (last {days} days)")
        table.add_column("Decision")
        table.add_column("Count", justify="right")
        table.add_column("Bar")

        total = sum(r["n"] for r in rows)
        for r in rows:
            pct = r["n"] / total * 100
            bar = "█" * int(pct / 3)
            color = {
                "BUY": "green",
                "SKIP_PRICE": "yellow",
                "SKIP_SIZE": "yellow",
                "SKIP_API": "red",
                "SKIP_ERROR": "red",
                "DRY_RUN": "blue",
            }.get(r["decision"], "white")
            table.add_row(
                f"[{color}]{r['decision']}[/{color}]",
                str(r["n"]),
                f"[{color}]{bar}[/{color}] {pct:.0f}%",
            )

        console.print(table)
        aconn.close()

    except Exception as e:
        console.print(f"[dim]Bridge stats unavailable: {e}[/dim]")


def _print_recent_trades(conn: sqlite3.Connection, limit: int = 10) -> None:
    """Print recent trades from paper.db."""
    rows = conn.execute("""
        SELECT market_question, outcome, side, avg_price, amount_usd, shares, created_at
        FROM trades
        ORDER BY id DESC
        LIMIT ?
    """, (limit,)).fetchall()

    if not rows:
        console.print("[dim]No trades yet.[/dim]")
        return

    table = Table(title=f"Recent Trades (last {limit})")
    table.add_column("Market", max_width=42, no_wrap=True)
    table.add_column("Outcome", max_width=12, no_wrap=True)
    table.add_column("Shares", justify="right", no_wrap=True)
    table.add_column("@ Price", justify="right", no_wrap=True)
    table.add_column("Cost", justify="right", no_wrap=True)
    table.add_column("Date", no_wrap=True)

    for r in rows:
        table.add_row(
            r["market_question"][:42],
            r["outcome"].upper()[:12],
            f"{r['shares']:,.0f}",
            f"{r['avg_price']:.3f}",
            f"${r['amount_usd']:.2f}",
            r["created_at"][:10],
        )

    console.print(table)


def _do_reset(paper_data_dir: str) -> None:
    """Reset paper account to starting balance."""
    from pm_trader.engine import Engine
    engine = Engine(Path(paper_data_dir))
    engine.reset()
    account = engine.init_account(BANKROLL)
    engine.close()
    console.print(f"[green]Account reset to ${BANKROLL:,.0f}. All positions and trades cleared.[/green]")


def _determine_winner(paper_outcome: str, analytics_outcome: str, outcomes_list: list[str]) -> bool | None:
    """Return True if paper position won, False if lost, None if unresolvable.

    analytics_outcome is always "YES" or "NO" (normalised by ingest-events).
    YES means outcomes_list[0] won; NO means outcomes_list[1] won.

    Mapping rules:
      - "yes" / "over"  → always YES token (index 0)
      - "no"  / "under" → always NO  token (index 1)
      - team name       → find case-insensitive match in outcomes_list
    """
    p = paper_outcome.lower()

    if p in ("yes", "over"):
        return analytics_outcome == "YES"
    if p in ("no", "under"):
        return analytics_outcome == "NO"

    # Team name — look up position in outcomes_list
    for i, name in enumerate(outcomes_list):
        if name.lower() == p:
            if i == 0:
                return analytics_outcome == "YES"
            else:
                return analytics_outcome == "NO"

    return None  # outcomes_list empty or name not matched


def _do_resolve(paper_data_dir: str, analytics_db_path: str) -> None:
    """Resolve closed market positions by cross-referencing analytics.db.

    Bypasses engine.resolve_market() (which requires market.closed==True from
    the Gamma API) and instead reads resolution state directly from analytics.db,
    which captures markets as soon as active=0 — the same condition used by
    resolve-positions for analytics positions.

    Token→outcome mapping uses the market_cache in paper.db (populated when
    paper-bridge ran) so no live API calls are needed.
    """
    import json

    paper_db_path = Path(paper_data_dir) / "paper.db"
    if not paper_db_path.exists():
        console.print("[red]No paper.db found. Run paper-bridge first.[/red]")
        return

    paper_conn = sqlite3.connect(str(paper_db_path))
    paper_conn.row_factory = sqlite3.Row
    analytics_conn = sqlite3.connect(analytics_db_path)
    analytics_conn.row_factory = sqlite3.Row

    try:
        if paper_conn.execute("SELECT id FROM account WHERE id=1").fetchone() is None:
            console.print("[red]No paper account. Run paper-bridge first.[/red]")
            return

        open_positions = paper_conn.execute(
            "SELECT market_condition_id, market_question, outcome, shares, total_cost "
            "FROM positions WHERE is_resolved=0 AND shares>0"
        ).fetchall()

        if not open_positions:
            console.print("[dim]No open positions to resolve.[/dim]")
            return

        console.print(f"[bold]Checking {len(open_positions)} open positions...[/bold]")

        resolved_count = 0
        void_count = 0
        unresolvable = 0
        cash_returned = 0.0

        for pos in open_positions:
            cid = pos["market_condition_id"]
            paper_outcome = pos["outcome"]
            shares = pos["shares"]
            total_cost = pos["total_cost"]

            # Look up market in analytics.db
            mkt = analytics_conn.execute(
                "SELECT outcome, active, resolved FROM markets WHERE condition_id=?",
                (cid,),
            ).fetchone()

            if mkt is None or (mkt["active"] == 1 and mkt["resolved"] == 0):
                continue  # still open

            analytics_outcome = mkt["outcome"]

            if analytics_outcome is None:
                # VOID: cancelled/postponed — refund stake, zero P&L
                payout = total_cost
                pnl = 0.0
                label = "VOID"
                void_count += 1
            else:
                # Get outcomes ordering from market_cache to map team names → YES/NO
                cached = paper_conn.execute(
                    "SELECT data FROM market_cache WHERE cache_key=?",
                    (f"market:{cid}",),
                ).fetchone()

                outcomes_list: list[str] = []
                if cached:
                    try:
                        mdata = json.loads(cached["data"])
                        raw = mdata.get("outcomes", "[]")
                        outcomes_list = json.loads(raw) if isinstance(raw, str) else raw
                    except (json.JSONDecodeError, ValueError):
                        pass

                won = _determine_winner(paper_outcome, analytics_outcome, outcomes_list)
                if won is None:
                    unresolvable += 1
                    continue

                payout = shares if won else 0.0
                pnl = payout - total_cost
                label = "WIN" if won else "LOSS"

            now = datetime.now(timezone.utc).isoformat()
            paper_conn.execute(
                "UPDATE positions SET is_resolved=1, realized_pnl=?, resolved_at=? "
                "WHERE market_condition_id=? AND outcome=?",
                (pnl, now, cid, paper_outcome),
            )
            paper_conn.execute(
                "UPDATE account SET cash=cash+? WHERE id=1", (payout,)
            )
            cash_returned += payout
            resolved_count += 1

            pnl_color = "green" if pnl >= 0 else "red"
            console.print(
                f"  [{pnl_color}]{pos['market_question'][:50]}[/{pnl_color}] "
                f"({paper_outcome}) → {label}  pnl ${pnl:+.2f}"
            )

        paper_conn.commit()

    finally:
        paper_conn.close()
        analytics_conn.close()

    total = resolved_count + void_count
    if total == 0 and unresolvable == 0:
        console.print("[dim]No closed markets to resolve yet.[/dim]")
        return

    console.print(
        f"\n[green]{resolved_count} resolved[/green]"
        + (f"  {void_count} voided" if void_count else "")
        + (f"  [dim]{unresolvable} unresolvable (no outcome mapping)[/dim]" if unresolvable else "")
        + f"  |  cash returned: ${cash_returned:,.2f}"
    )


# ─── HTML generation ─────────────────────────────────────────────────────────

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    background: #0d1117;
    color: #e6edf3;
    font-family: 'Menlo', 'Monaco', 'Consolas', monospace;
    font-size: 13px;
    padding: 20px;
    max-width: 1100px;
    margin: 0 auto;
}
h1 { color: #58a6ff; font-size: 18px; margin-bottom: 4px; }
.meta { color: #8b949e; font-size: 11px; margin-bottom: 20px; }
.card {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 16px;
    margin-bottom: 16px;
}
.card-title {
    font-size: 13px;
    font-weight: bold;
    color: #58a6ff;
    border-bottom: 1px solid #30363d;
    padding-bottom: 8px;
    margin-bottom: 12px;
}
table { width: 100%; border-collapse: collapse; }
th {
    text-align: left;
    color: #8b949e;
    font-weight: normal;
    padding: 4px 8px;
    border-bottom: 1px solid #21262d;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
th.r, td.r { text-align: right; }
td { padding: 4px 8px; border-bottom: 1px solid #161b22; }
tr:hover td { background: #1c2128; }
.green { color: #3fb950; }
.red   { color: #f85149; }
.yellow{ color: #d29922; }
.blue  { color: #58a6ff; }
.dim   { color: #8b949e; }
.summary td:first-child { color: #8b949e; width: 100px; }
.summary td:nth-child(2) { font-weight: bold; width: 140px; }
.warn {
    background: #2d1010;
    border: 1px solid #f85149;
    border-radius: 4px;
    padding: 8px 12px;
    color: #f85149;
    margin-top: 10px;
    font-weight: bold;
}
.resolved-bar { margin-top: 10px; color: #8b949e; font-size: 12px; }
.bar { letter-spacing: -1px; }
.actions { display: flex; gap: 8px; margin-top: 14px; }
button {
    font-family: inherit;
    font-size: 12px;
    padding: 5px 14px;
    border-radius: 4px;
    border: 1px solid;
    cursor: pointer;
    font-weight: bold;
}
.btn-resolve { background: #0d2b1a; color: #3fb950; border-color: #3fb950; }
.btn-resolve:hover { background: #163d26; }
.btn-reset   { background: #2d1010; color: #f85149; border-color: #f85149; }
.btn-reset:hover { background: #3d1515; }
.flash { background: #162a1e; border: 1px solid #3fb950; border-radius: 4px;
         padding: 8px 12px; color: #3fb950; margin-bottom: 14px; }
"""

_JS = """
let secs = 30;
const el = document.getElementById('cd');
setInterval(() => {
    secs -= 1;
    if (secs <= 0) { location.reload(); return; }
    if (el) el.textContent = secs + 's';
}, 1000);
"""


def _html_page(body: str, now: str = "", msg: str = "") -> str:
    flash = f'<div class="flash">{_html_module.escape(msg)}</div>' if msg else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Paper Trading Dashboard</title>
<style>{_CSS}</style>
</head>
<body>
<h1>Paper Trading Dashboard</h1>
<p class="meta">Updated {now} &nbsp;&middot;&nbsp; Refreshing in <span id="cd">30s</span></p>
{flash}{body}
<script>{_JS}</script>
</body>
</html>"""


def _html_account_summary(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT * FROM account WHERE id = 1").fetchone()
    if row is None:
        return '<div class="card"><p class="red">No paper account found. Run paper-bridge first.</p></div>'

    cash = row["cash"]
    starting = row["starting_balance"]
    created = row["created_at"]
    deployed = starting - cash

    realized_pnl = conn.execute(
        "SELECT COALESCE(SUM(realized_pnl), 0) FROM positions WHERE is_resolved = 1"
    ).fetchone()[0]

    open_count = conn.execute(
        "SELECT COUNT(*) FROM positions WHERE is_resolved = 0 AND shares > 0"
    ).fetchone()[0]

    trades_count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]

    pnl_cls = "green" if realized_pnl >= 0 else "red"
    cash_cls = "red" if cash < LOW_CASH_THRESHOLD else ""
    pnl_sign = "+" if realized_pnl >= 0 else ""

    warn = ""
    if cash < LOW_CASH_THRESHOLD:
        warn = f'<div class="warn">LOW CASH: ${cash:.2f} remaining — bet sizing will SKIP_SIZE.</div>'

    return f"""
<div class="card">
  <div class="card-title">Account Summary</div>
  <table class="summary">
    <tr>
      <td>Started</td>
      <td>${starting:,.2f}</td>
      <td class="dim">Created {_html_module.escape(created[:10])}</td>
    </tr>
    <tr>
      <td>Cash</td>
      <td class="{cash_cls}">${cash:,.2f}</td>
    </tr>
    <tr>
      <td>Deployed</td>
      <td>${deployed:,.2f}</td>
      <td class="dim">cash spent on open positions</td>
    </tr>
    <tr>
      <td>Realized P&amp;L</td>
      <td class="{pnl_cls}">{pnl_sign}${realized_pnl:,.2f}</td>
      <td class="dim">resolved positions</td>
    </tr>
    <tr>
      <td>Positions</td>
      <td>{open_count:,} open</td>
      <td class="dim">{trades_count:,} total trades</td>
    </tr>
  </table>
  {warn}
  <div class="actions">
    <form method="POST" action="/resolve">
      <button type="submit" class="btn-resolve">Resolve Closed Markets</button>
    </form>
    <form method="POST" action="/reset"
          onsubmit="return confirm('Reset paper account to $10,000? This clears ALL positions and trade history.')">
      <button type="submit" class="btn-reset">Reset Account</button>
    </form>
  </div>
</div>"""


def _html_positions(conn: sqlite3.Connection, limit: int = 20) -> str:
    rows = conn.execute("""
        SELECT market_question, outcome, shares, avg_entry_price, total_cost
        FROM positions
        WHERE is_resolved = 0 AND shares > 0
        ORDER BY total_cost DESC
        LIMIT ?
    """, (limit,)).fetchall()

    total_open = conn.execute(
        "SELECT COUNT(*) FROM positions WHERE is_resolved = 0 AND shares > 0"
    ).fetchone()[0]

    won_count, won_pnl = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(realized_pnl), 0) FROM positions WHERE is_resolved = 1 AND realized_pnl > 0"
    ).fetchone()
    lost_count, lost_pnl = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(realized_pnl), 0) FROM positions WHERE is_resolved = 1 AND realized_pnl <= 0"
    ).fetchone()

    rows_html = "".join(f"""
    <tr>
      <td>{_html_module.escape(r['market_question'][:55])}</td>
      <td>{_html_module.escape(r['outcome'].upper()[:12])}</td>
      <td class="r">{r['shares']:,.0f}</td>
      <td class="r">{r['avg_entry_price']:.3f}</td>
      <td class="r">${r['total_cost']:.2f}</td>
    </tr>""" for r in rows)

    total_resolved = won_count + lost_count
    resolved_bar = ""
    if total_resolved > 0:
        win_rate = won_count / total_resolved * 100
        resolved_bar = (
            f'<div class="resolved-bar">'
            f'Resolved: {total_resolved} &nbsp;&middot;&nbsp; '
            f'<span class="green">{won_count} won (+${won_pnl:.2f})</span> &nbsp;&middot;&nbsp; '
            f'<span class="red">{lost_count} lost (${lost_pnl:.2f})</span> &nbsp;&middot;&nbsp; '
            f'Win rate: {win_rate:.0f}%'
            f'</div>'
        )

    shown = min(limit, total_open)
    return f"""
<div class="card">
  <div class="card-title">Open Positions (top {shown} of {total_open})</div>
  <table>
    <thead><tr>
      <th>Market</th><th>Outcome</th>
      <th class="r">Shares</th><th class="r">Entry</th><th class="r">Cost</th>
    </tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
  {resolved_bar}
</div>"""


def _html_decision_stats(analytics_db_path: str, days: int = 7) -> str:
    COLORS = {
        "BUY": "green", "SKIP_PRICE": "yellow", "SKIP_SIZE": "yellow",
        "SKIP_API": "red", "SKIP_ERROR": "red", "DRY_RUN": "blue",
    }
    try:
        aconn = sqlite3.connect(analytics_db_path)
        aconn.row_factory = sqlite3.Row
        rows = aconn.execute("""
            SELECT decision, COUNT(*) as n
            FROM bridge_decisions
            WHERE checked_at >= datetime('now', ?)
            GROUP BY decision
            ORDER BY n DESC
        """, (f"-{days} days",)).fetchall()
        aconn.close()

        if not rows:
            return ""

        total = sum(r["n"] for r in rows)
        BLOCK = "\u2588"
        rows_html = "".join(f"""
    <tr>
      <td class="{COLORS.get(r['decision'], '')}">{_html_module.escape(r['decision'])}</td>
      <td class="r">{r['n']}</td>
      <td>
        <span class="bar {COLORS.get(r['decision'], '')}">{BLOCK * int(r['n'] / total * 100 / 3)}</span>
        <span class="dim"> {r['n'] / total * 100:.0f}%</span>
      </td>
    </tr>""" for r in rows)

        return f"""
<div class="card">
  <div class="card-title">Bridge Decisions (last {days} days)</div>
  <table>
    <thead><tr><th>Decision</th><th class="r">Count</th><th>Distribution</th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>"""
    except Exception as e:
        return f'<div class="card dim">Bridge stats unavailable: {_html_module.escape(str(e))}</div>'


def _html_recent_trades(conn: sqlite3.Connection, limit: int = 10) -> str:
    rows = conn.execute("""
        SELECT market_question, outcome, avg_price, amount_usd, shares, created_at
        FROM trades
        ORDER BY id DESC
        LIMIT ?
    """, (limit,)).fetchall()

    if not rows:
        return '<div class="card dim">No trades yet.</div>'

    rows_html = "".join(f"""
    <tr>
      <td>{_html_module.escape(r['market_question'][:55])}</td>
      <td>{_html_module.escape(r['outcome'].upper()[:12])}</td>
      <td class="r">{r['shares']:,.0f}</td>
      <td class="r">{r['avg_price']:.3f}</td>
      <td class="r">${r['amount_usd']:.2f}</td>
      <td class="dim">{_html_module.escape(r['created_at'][:10])}</td>
    </tr>""" for r in rows)

    return f"""
<div class="card">
  <div class="card-title">Recent Trades (last {limit})</div>
  <table>
    <thead><tr>
      <th>Market</th><th>Outcome</th>
      <th class="r">Shares</th><th class="r">Price</th><th class="r">Cost</th><th>Date</th>
    </tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>"""


def _generate_html(
    paper_data_dir: str,
    analytics_db_path: str,
    limit: int,
    trade_limit: int,
    days: int,
    msg: str = "",
) -> str:
    paper_db_path = Path(paper_data_dir) / "paper.db"
    if not paper_db_path.exists():
        err = '<div class="card"><p class="red">No paper.db found. Run paper-bridge first.</p></div>'
        return _html_page(err)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(str(paper_db_path))
    conn.row_factory = sqlite3.Row
    try:
        body = (
            _html_account_summary(conn)
            + _html_positions(conn, limit)
            + _html_decision_stats(analytics_db_path, days)
            + _html_recent_trades(conn, trade_limit)
        )
    finally:
        conn.close()

    return _html_page(body, now=now, msg=msg)


# ─── HTTP server ─────────────────────────────────────────────────────────────

def _serve_dashboard(
    port: int,
    paper_data_dir: str,
    analytics_db_path: str,
    limit: int,
    trade_limit: int,
    days: int,
) -> None:
    cfg = dict(
        paper_data_dir=paper_data_dir,
        analytics_db_path=analytics_db_path,
        limit=limit,
        trade_limit=trade_limit,
        days=days,
    )

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            parsed = urlparse(self.path)
            if parsed.path != "/":
                self.send_response(404)
                self.end_headers()
                return
            msg = unquote_plus(parse_qs(parsed.query).get("msg", [""])[0])
            page = _generate_html(**cfg, msg=msg)
            data = page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:
            action = self.path
            msg = ""
            if action == "/resolve":
                try:
                    _do_resolve(cfg["paper_data_dir"], cfg["analytics_db_path"])
                    msg = "Resolve+complete"
                except Exception as e:
                    msg = f"Error:+{quote(str(e))}"
            elif action == "/reset":
                try:
                    from pm_trader.engine import Engine
                    engine = Engine(Path(cfg["paper_data_dir"]))
                    engine.reset()
                    engine.init_account(BANKROLL)
                    engine.close()
                    msg = f"Account+reset+to+%2410%2C000"
                except Exception as e:
                    msg = f"Error:+{quote(str(e))}"
            self.send_response(303)
            self.send_header("Location", f"/?msg={msg}" if msg else "/")
            self.end_headers()

        def log_message(self, fmt: str, *args: Any) -> None:
            pass  # suppress per-request logs

    server = HTTPServer(("127.0.0.1", port), Handler)
    url = f"http://localhost:{port}"
    console.print(f"[bold green]Dashboard at {url}[/bold green]  [dim](Ctrl+C to stop)[/dim]")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console.print("\n[dim]Server stopped.[/dim]")


# ─── CLI command ─────────────────────────────────────────────────────────────

@cli.command("paper-dashboard")
@click.option(
    "--db-path",
    default="data/analytics.db",
    help="Path to analytics SQLite database",
)
@click.option(
    "--paper-data-dir",
    default="data/paper_trader",
    help="Directory for paper trader data",
)
@click.option(
    "--limit",
    default=20,
    type=int,
    help="Max positions to show (default: 20)",
)
@click.option(
    "--trades",
    "trade_limit",
    default=10,
    type=int,
    help="Recent trades to show (default: 10)",
)
@click.option(
    "--days",
    default=7,
    type=int,
    help="Days of bridge decision history (default: 7)",
)
@click.option(
    "--resolve",
    is_flag=True,
    default=False,
    help="Resolve all closed market positions before showing dashboard",
)
@click.option(
    "--reset",
    is_flag=True,
    default=False,
    help="Reset paper account to $10,000 (clears all positions and trades)",
)
@click.option(
    "--serve",
    is_flag=True,
    default=False,
    help="Serve dashboard on localhost (auto-refreshes every 30s)",
)
@click.option(
    "--port",
    default=8080,
    type=int,
    help="Port for --serve (default: 8080)",
)
@click.pass_context
def paper_dashboard(
    ctx: Any,
    db_path: str,
    paper_data_dir: str,
    limit: int,
    trade_limit: int,
    days: int,
    resolve: bool,
    reset: bool,
    serve: bool,
    port: int,
) -> None:
    """Show paper trading portfolio, P&L, and decision stats.

    Reads directly from paper.db — no live API calls.
    Use --serve to launch a web dashboard at localhost:8080.
    Use --resolve to settle positions in closed markets.
    Use --reset to reinitialize account to $10,000 (destructive).
    """
    if reset:
        console.print("[bold yellow]This will delete all positions and trade history.[/bold yellow]")
        if not click.confirm("Are you sure you want to reset the paper account?", default=False):
            console.print("[dim]Aborted.[/dim]")
            return
        _do_reset(paper_data_dir)
        console.print()

    if resolve:
        _do_resolve(paper_data_dir, db_path)
        console.print()

    if serve:
        _serve_dashboard(port, paper_data_dir, db_path, limit, trade_limit, days)
        return

    paper_db_path = Path(paper_data_dir) / "paper.db"
    if not paper_db_path.exists():
        console.print("[red]No paper.db found. Run paper-bridge first.[/red]")
        return

    conn = _open_paper_db(paper_data_dir)

    _print_account_summary(conn)
    console.print()
    _print_positions(conn, limit=limit)
    console.print()
    _print_decision_stats(db_path, days=days)
    console.print()
    _print_recent_trades(conn, limit=trade_limit)

    conn.close()
