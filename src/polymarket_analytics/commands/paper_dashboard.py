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

    # Deployed = actual cost tied up in open positions
    deployed = conn.execute(
        "SELECT COALESCE(SUM(total_cost), 0) FROM positions WHERE is_resolved = 0 AND shares > 0"
    ).fetchone()[0]

    # Realized P&L: market-resolved positions (is_resolved=1) OR TP-exited (shares=0)
    realized_pnl = conn.execute(
        "SELECT COALESCE(SUM(realized_pnl), 0) FROM positions WHERE is_resolved = 1 OR shares = 0"
    ).fetchone()[0]

    open_count = conn.execute(
        "SELECT COUNT(*) FROM positions WHERE is_resolved = 0 AND shares > 0"
    ).fetchone()[0]

    trades_count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]

    pnl_color = "green" if realized_pnl >= 0 else "red"
    cash_color = "red" if cash < LOW_CASH_THRESHOLD else "white"

    lines = [
        f"Started:   ${starting:>10,.2f}    Created: {created[:10]}",
        f"Cash:      [{cash_color}]${cash:>10,.2f}[/{cash_color}]",
        f"Deployed:  ${deployed:>10,.2f}    (cost of {open_count} open positions)",
        f"Realized:  [{pnl_color}]${realized_pnl:>+10,.2f}[/{pnl_color}]   (closed positions)",
        f"Trades:    {trades_count:>10,}",
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

    _closed = "(is_resolved = 1 OR shares = 0)"
    resolved_won = conn.execute(
        f"SELECT COUNT(*), COALESCE(SUM(realized_pnl), 0) FROM positions WHERE {_closed} AND realized_pnl > 0"
    ).fetchone()
    resolved_lost = conn.execute(
        f"SELECT COUNT(*), COALESCE(SUM(realized_pnl), 0) FROM positions WHERE {_closed} AND realized_pnl <= 0"
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

    # Closed positions table: market-resolved (is_resolved=1) OR TP-exited (shares=0)
    resolved_rows = conn.execute("""
        SELECT market_question, outcome, shares, total_cost, realized_pnl, resolved_at
        FROM positions
        WHERE is_resolved = 1 OR shares = 0
        ORDER BY COALESCE(resolved_at, '9999') DESC
        LIMIT ?
    """, (limit,)).fetchall()

    won_count, won_pnl = resolved_won
    lost_count, lost_pnl = resolved_lost
    total_resolved = won_count + lost_count

    if resolved_rows:
        rtable = Table(
            title=f"Closed Positions (last {len(resolved_rows)} of {total_resolved})",
            show_lines=False,
        )
        rtable.add_column("Market", max_width=42, no_wrap=True)
        rtable.add_column("Outcome", max_width=12, no_wrap=True)
        rtable.add_column("Result", justify="center", no_wrap=True)
        rtable.add_column("Cost", justify="right", no_wrap=True)
        rtable.add_column("P&L", justify="right", no_wrap=True)
        rtable.add_column("Closed", no_wrap=True)

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

            if r["resolved_at"]:
                closed_str = r["resolved_at"][:10]
            else:
                closed_str = "[dim]TP exit[/dim]"
            rtable.add_row(
                r["market_question"][:42],
                (r["outcome"] or "").upper()[:12],
                result_str,
                f"${r['total_cost']:.2f}",
                pnl_str,
                closed_str,
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
                "SKIP_OPPOSITE_HELD": "yellow",
                "SKIP_API": "red",
                "SKIP_NO_BOOK": "dim",
                "SKIP_TP_EXIT": "dim",
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
    table.add_column("Side", no_wrap=True)
    table.add_column("Shares", justify="right", no_wrap=True)
    table.add_column("@ Price", justify="right", no_wrap=True)
    table.add_column("Cost", justify="right", no_wrap=True)
    table.add_column("Date", no_wrap=True)

    for r in rows:
        side = r["side"].upper()
        side_styled = f"[green]{side}[/green]" if side == "BUY" else f"[red]{side}[/red]"
        table.add_row(
            r["market_question"][:42],
            r["outcome"].upper()[:12],
            side_styled,
            f"{r['shares']:,.0f}",
            f"{r['avg_price']:.3f}",
            f"${r['amount_usd']:.2f}",
            r["created_at"][:16],
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


def _parse_teams_from_question(question: str) -> list[str]:
    """Extract [team_a, team_b] from a market question like 'Game: A vs B (BO3) - ...'

    Returns empty list if the pattern doesn't match.
    """
    import re
    m = re.search(r':\s*(.+?)\s+vs\.?\s+(.+?)(?:\s*\(|$|\s*-)', question)
    if m:
        return [m.group(1).strip(), m.group(2).strip()]
    return []


def _determine_winner(
    paper_outcome: str,
    analytics_outcome: str,
    outcomes_list: list[str],
    question: str = "",
) -> bool | None:
    """Return True if paper position won, False if lost, None if unresolvable.

    analytics_outcome is always "YES" or "NO" (normalised by ingest-events).
    YES means outcomes_list[0] won; NO means outcomes_list[1] won.

    Mapping rules:
      - "yes" / "over"  → always YES token (index 0)
      - "no"  / "under" → always NO  token (index 1)
      - team name       → find case-insensitive match in outcomes_list
      - fallback        → parse "Team A vs Team B" from question text
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

    # Fallback: parse team names from market question text.
    # Head-to-head format is "Game: Team A vs Team B (BO3) - ..."
    # Index 0 (Team A) = YES, Index 1 (Team B) = NO.
    if question:
        parsed = _parse_teams_from_question(question)
        for i, name in enumerate(parsed):
            if name.lower() == p:
                return (analytics_outcome == "YES") if i == 0 else (analytics_outcome == "NO")

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

                won = _determine_winner(
                    paper_outcome, analytics_outcome, outcomes_list,
                    question=pos["market_question"] or "",
                )
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
.meta { color: #8b949e; font-size: 11px; margin-bottom: 16px; }
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
         padding: 8px 12px; color: #3fb950; margin-bottom: 14px;
         transition: opacity 0.5s ease; }

/* Tabs */
.tabs {
    display: flex;
    gap: 0;
    border-bottom: 1px solid #30363d;
    margin-bottom: 20px;
}
.tab-btn {
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    color: #8b949e;
    cursor: pointer;
    font-family: inherit;
    font-size: 12px;
    font-weight: 500;
    padding: 8px 16px;
    letter-spacing: 0.03em;
    margin-bottom: -1px;
}
.tab-btn:hover { color: #e6edf3; }
.tab-btn.active { color: #58a6ff; border-bottom-color: #58a6ff; }
.tab-badge {
    display: inline-block;
    background: #21262d;
    border-radius: 10px;
    font-size: 10px;
    padding: 1px 6px;
    margin-left: 5px;
    color: #8b949e;
}
.tab-btn.active .tab-badge { background: #1f3a5f; color: #58a6ff; }
.tab-panel { display: none; }
.tab-panel.active { display: block; }
.btn-show-more {
    background: none;
    border: 1px solid #30363d;
    border-radius: 4px;
    color: #8b949e;
    cursor: pointer;
    font-family: inherit;
    font-size: 11px;
    padding: 4px 12px;
}
.btn-show-more:hover { color: #e6edf3; border-color: #8b949e; }
"""

_JS = """
// Tab switching — persists across auto-refresh via localStorage
function showTab(name) {
    document.querySelectorAll('.tab-btn').forEach(b =>
        b.classList.toggle('active', b.dataset.tab === name));
    document.querySelectorAll('.tab-panel').forEach(p =>
        p.classList.toggle('active', p.dataset.panel === name));
    localStorage.setItem('paperTab', name);
}
const savedTab = localStorage.getItem('paperTab') || 'overview';
showTab(savedTab);

// Auto-refresh countdown
let secs = 30;
const el = document.getElementById('cd');
setInterval(() => {
    secs -= 1;
    if (secs <= 0) { location.reload(); return; }
    if (el) el.textContent = secs + 's';
}, 1000);

// Auto-dismiss flash message after 3s and clean the URL
const flash = document.getElementById('flash');
if (flash) {
    setTimeout(() => {
        flash.style.opacity = '0';
        setTimeout(() => { flash.style.display = 'none'; }, 500);
    }, 3000);
    history.replaceState(null, '', '/');
}
"""


def _html_page(tabs: list, now: str = "", msg: str = "") -> str:
    """Render the full page with tab navigation.

    tabs: list of (tab_id, label, badge_count_or_None, html_content)
    """
    flash = f'<div id="flash" class="flash">{_html_module.escape(msg)}</div>' if msg else ""

    nav_html = '<div class="tabs">'
    panels_html = ""
    for tab_id, label, badge, content in tabs:
        badge_html = f'<span class="tab-badge">{badge}</span>' if badge is not None else ""
        nav_html += (
            f'<button class="tab-btn" data-tab="{tab_id}"'
            f' onclick="showTab(\'{tab_id}\')">{_html_module.escape(label)}{badge_html}</button>'
        )
        panels_html += f'<div class="tab-panel" data-panel="{tab_id}">{content}</div>'
    nav_html += "</div>"

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
{flash}{nav_html}{panels_html}
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

    # Deployed = actual cost tied up in open positions
    deployed = conn.execute(
        "SELECT COALESCE(SUM(total_cost), 0) FROM positions WHERE is_resolved = 0 AND shares > 0"
    ).fetchone()[0]

    # Realized P&L: market-resolved positions (is_resolved=1) OR TP-exited (shares=0)
    realized_pnl = conn.execute(
        "SELECT COALESCE(SUM(realized_pnl), 0) FROM positions WHERE is_resolved = 1 OR shares = 0"
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
      <td class="dim">cost of {open_count} open positions</td>
    </tr>
    <tr>
      <td>Realized P&amp;L</td>
      <td class="{pnl_cls}">{pnl_sign}${realized_pnl:,.2f}</td>
      <td class="dim">closed positions</td>
    </tr>
    <tr>
      <td>Trades</td>
      <td>{trades_count:,}</td>
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


def _html_open_positions(conn: sqlite3.Connection, limit: int = 20) -> str:
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

    if not rows:
        return '<div class="card dim">No open positions.</div>'

    rows_html = "".join(f"""
    <tr>
      <td>{_html_module.escape(r['market_question'][:55])}</td>
      <td>{_html_module.escape(r['outcome'].upper()[:12])}</td>
      <td class="r">{r['shares']:,.0f}</td>
      <td class="r">{r['avg_entry_price']:.3f}</td>
      <td class="r">${r['total_cost']:.2f}</td>
    </tr>""" for r in rows)

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
</div>"""


def _html_resolved_positions(conn: sqlite3.Connection, limit: int = 20) -> str:
    _closed = "(is_resolved = 1 OR shares = 0)"
    won_count, won_pnl = conn.execute(
        f"SELECT COUNT(*), COALESCE(SUM(realized_pnl), 0) FROM positions WHERE {_closed} AND realized_pnl > 0"
    ).fetchone()
    lost_count, lost_pnl = conn.execute(
        f"SELECT COUNT(*), COALESCE(SUM(realized_pnl), 0) FROM positions WHERE {_closed} AND realized_pnl <= 0"
    ).fetchone()
    total_closed = won_count + lost_count

    rows = conn.execute(f"""
        SELECT p.market_question, p.outcome, p.total_cost, p.realized_pnl,
               p.resolved_at, p.is_resolved,
               COALESCE(
                   NULLIF(p.total_cost, 0),
                   (SELECT SUM(t.amount_usd) FROM trades t
                    WHERE t.market_condition_id = p.market_condition_id
                      AND t.outcome = p.outcome AND t.side = 'buy')
               ) as original_cost
        FROM positions p
        WHERE {_closed}
        ORDER BY COALESCE(p.resolved_at, '9999') DESC
    """).fetchall()

    if not rows:
        return '<div class="card dim">No closed positions yet.</div>'

    SHOW_FIRST = 10
    rows_html = ""
    for i, r in enumerate(rows):
        pnl = r["realized_pnl"] or 0.0
        extra_cls = ' class="res-extra" style="display:none"' if i >= SHOW_FIRST else ""

        if r["is_resolved"]:
            if pnl > 0:
                result = '<span class="green">WIN</span>'
                pnl_str = f'<span class="green">+${pnl:.2f}</span>'
            elif pnl < 0:
                result = '<span class="red">LOSS</span>'
                pnl_str = f'<span class="red">-${abs(pnl):.2f}</span>'
            else:
                result = '<span class="dim">VOID</span>'
                pnl_str = '<span class="dim">$0.00</span>'
            type_str = '<span class="dim">Market</span>'
            date_str = (r["resolved_at"] or "")[:10]
        else:
            # TP exit — shares zeroed by engine.sell(), no resolved_at in paper.db
            result = f'<span class="blue">TP exit</span>'
            pnl_str = f'<span class="green">+${pnl:.2f}</span>'
            type_str = '<span class="blue">TP exit</span>'
            date_str = '<span class="dim">—</span>'

        rows_html += f"""
    <tr{extra_cls}>
      <td>{_html_module.escape((r['market_question'] or '')[:60])}</td>
      <td>{_html_module.escape((r['outcome'] or '').upper()[:12])}</td>
      <td class="r">{type_str}</td>
      <td class="r">{result}</td>
      <td class="r">${r['original_cost'] or 0:.2f}</td>
      <td class="r">{pnl_str}</td>
      <td class="dim">{date_str}</td>
    </tr>"""

    show_more = ""
    if len(rows) > SHOW_FIRST:
        hidden = len(rows) - SHOW_FIRST
        show_more = f"""
  <div style="margin-top:10px">
    <button class="btn-show-more" onclick="
      var els = document.querySelectorAll('.res-extra');
      var hidden = els[0] && els[0].style.display === 'none';
      els.forEach(function(el) {{ el.style.display = hidden ? '' : 'none'; }});
      this.textContent = hidden ? 'Show less' : 'Show {hidden} more';
    ">Show {hidden} more</button>
  </div>"""

    win_rate_str = ""
    if total_closed > 0:
        win_rate = won_count / total_closed * 100
        win_rate_str = (
            f'<div class="resolved-bar">'
            f'Closed: {total_closed} &nbsp;&middot;&nbsp; '
            f'<span class="green">{won_count} profitable (+${won_pnl:.2f})</span> &nbsp;&middot;&nbsp; '
            f'<span class="red">{lost_count} loss (${lost_pnl:.2f})</span> &nbsp;&middot;&nbsp; '
            f'Win rate: {win_rate:.0f}%'
            f'</div>'
        )

    return f"""
<div class="card">
  <div class="card-title">Closed Positions ({total_closed})</div>
  <table>
    <thead><tr>
      <th>Market</th><th>Outcome</th>
      <th class="r">Type</th><th class="r">Result</th>
      <th class="r">Cost</th><th class="r">P&amp;L</th><th>Date</th>
    </tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
  {win_rate_str}{show_more}
</div>"""


def _html_take_profit_log(analytics_db_path: str) -> str:
    try:
        aconn = sqlite3.connect(analytics_db_path)
        aconn.row_factory = sqlite3.Row
        # Aggregate by position — a single position may be sold across multiple TP runs
        rows = aconn.execute("""
            SELECT tpl.outcome,
                   SUM(tpl.entry_price * tpl.shares) / SUM(tpl.shares) as entry_price,
                   SUM(tpl.exit_price * tpl.shares) / SUM(tpl.shares) as exit_price,
                   SUM(tpl.shares) as shares,
                   SUM(tpl.exit_value_usd) as exit_value_usd,
                   MAX(tpl.threshold) as threshold,
                   MAX(tpl.exited_at) as exited_at,
                   -- use latest non-null final_outcome/counterfactual
                   MAX(tpl.final_outcome) as final_outcome,
                   MAX(tpl.final_price) as final_price,
                   SUM(tpl.counterfactual_pnl) as counterfactual_pnl,
                   COALESCE(m.question, tpl.market_condition_id) AS question
            FROM take_profit_log tpl
            LEFT JOIN markets m ON m.condition_id = tpl.market_condition_id
            GROUP BY tpl.market_condition_id, tpl.outcome
            ORDER BY MAX(tpl.id) DESC
        """).fetchall()
        aconn.close()
    except Exception as e:
        return f'<div class="card dim">Take-profit log unavailable: {_html_module.escape(str(e))}</div>'

    if not rows:
        return '<div class="card dim">No take-profit exits yet. Run paper-take-profit to scan open positions.</div>'

    rows_html = ""
    for r in rows:
        ratio = r["exit_price"] / r["entry_price"] if r["entry_price"] else 0
        exited = (r["exited_at"] or "")[:16]
        fo = r["final_outcome"]
        cpnl = r["counterfactual_pnl"]

        if fo is None:
            final_str = '<span class="dim">pending</span>'
            cpnl_str = '<span class="dim">—</span>'
            verdict_str = '<span class="dim">—</span>'
        elif fo == "WON":
            final_str = '<span class="yellow">WON</span>'
            if cpnl is not None and cpnl > 0:
                cpnl_str = f'<span class="yellow">+${cpnl:.2f}</span>'
                verdict_str = '<span class="yellow">Left $ on table</span>'
            else:
                v = cpnl or 0
                cpnl_str = f'<span class="green">${v:.2f}</span>'
                verdict_str = '<span class="green">Perfect</span>'
        elif fo == "LOST":
            final_str = '<span class="red">LOST</span>'
            v = cpnl or 0
            cpnl_str = f'<span class="green">${v:.2f}</span>'
            verdict_str = '<span class="green">TP saved trade</span>'
        else:
            final_str = '<span class="dim">VOID</span>'
            cpnl_str = '<span class="dim">$0.00</span>'
            verdict_str = '<span class="dim">—</span>'

        rows_html += f"""
    <tr>
      <td>{_html_module.escape(r['question'][:55])}</td>
      <td>{_html_module.escape((r['outcome'] or '').upper()[:12])}</td>
      <td class="r">{r['entry_price']:.3f}</td>
      <td class="r">{r['exit_price']:.3f}</td>
      <td class="r">{ratio:.2f}x</td>
      <td class="r">{r['shares']:,.0f}</td>
      <td class="r">${r['exit_value_usd']:.2f}</td>
      <td class="dim">{exited}</td>
      <td class="r">{final_str}</td>
      <td class="r">{cpnl_str}</td>
      <td>{verdict_str}</td>
    </tr>"""

    return f"""
<div class="card">
  <div class="card-title">Take-Profit Exits ({len(rows)})</div>
  <table>
    <thead><tr>
      <th>Market</th><th>Outcome</th>
      <th class="r">Entry</th><th class="r">Exit</th><th class="r">Ratio</th>
      <th class="r">Shares</th><th class="r">Value</th><th>Exited</th>
      <th class="r">Result</th><th class="r">Counterfactual</th><th>Verdict</th>
    </tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
  <div class="dim" style="font-size:11px;margin-top:8px">
    Counterfactual P&amp;L = gains left on table (positive) or losses avoided (negative) vs holding to resolution.
  </div>
</div>"""


def _html_signal_log(analytics_db_path: str, limit: int = 50) -> str:
    DECISION_COLORS = {
        "BUY": "green", "TAKE_PROFIT": "green",
        "SKIP_PRICE": "yellow", "SKIP_SIZE": "yellow",
        "SKIP_OPPOSITE_HELD": "yellow",
        "SKIP_API": "red", "SKIP_NO_BOOK": "gray",
        "SKIP_TP_EXIT": "gray",
        "SKIP_ERROR": "red",
        "DRY_RUN": "blue",
    }
    try:
        aconn = sqlite3.connect(analytics_db_path)
        aconn.row_factory = sqlite3.Row
        rows = aconn.execute("""
            SELECT bd.decision, bd.direction, bd.tier, bd.q5_count,
                   bd.q5_avg_entry, bd.live_price, bd.spread_vs_q5,
                   bd.size_usd, bd.reason, bd.checked_at,
                   COALESCE(m.question, bd.market_id) AS question
            FROM bridge_decisions bd
            LEFT JOIN markets m ON m.condition_id = bd.market_id
            ORDER BY bd.id DESC
            LIMIT ?
        """, (limit,)).fetchall()
        aconn.close()
    except Exception as e:
        return f'<div class="card dim">Signal log unavailable: {_html_module.escape(str(e))}</div>'

    if not rows:
        return '<div class="card dim">No signal evaluations yet. Run paper-bridge to evaluate signals.</div>'

    rows_html = ""
    for r in rows:
        color = DECISION_COLORS.get(r["decision"], "")
        dec_cell = f'<span class="{color}">{_html_module.escape(r["decision"])}</span>' if color else _html_module.escape(r["decision"])
        tier = r["tier"] or "—"
        tier_cls = "yellow" if tier in ("ACT", "CONSIDER") else "dim"
        q5 = str(r["q5_count"]) if r["q5_count"] is not None else "—"
        entry = f'{r["q5_avg_entry"]:.3f}' if r["q5_avg_entry"] is not None else "—"
        live = f'{r["live_price"]:.3f}' if r["live_price"] is not None else "—"
        spread = f'{r["spread_vs_q5"]:.3f}' if r["spread_vs_q5"] is not None else "—"
        size = f'${r["size_usd"]:.2f}' if r["size_usd"] else "—"
        reason = (r["reason"] or "").strip()[:45]
        checked = (r["checked_at"] or "")[:16].replace("T", " ")
        rows_html += f"""
    <tr>
      <td style="max-width:320px;word-break:break-word">{_html_module.escape(r['question'])}</td>
      <td>{_html_module.escape(r['direction'] or '')}</td>
      <td class="{tier_cls}">{_html_module.escape(tier)}</td>
      <td class="r">{q5}</td>
      <td class="r">{entry}</td>
      <td class="r">{live}</td>
      <td class="r">{spread}</td>
      <td class="r">{size}</td>
      <td>{dec_cell}</td>
      <td class="dim" style="font-size:10px;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{_html_module.escape(reason)}</td>
      <td class="dim" style="font-size:10px;white-space:nowrap">{checked}</td>
    </tr>"""

    return f"""
<div class="card">
  <div class="card-title">Signal Evaluations (last {limit})</div>
  <table>
    <thead><tr>
      <th>Market</th><th>Dir</th><th>Tier</th>
      <th class="r">Q5</th><th class="r">Q5 Entry</th><th class="r">Live</th><th class="r">Spread</th>
      <th class="r">Size</th><th>Decision</th><th>Reason</th><th>Time</th>
    </tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>"""


def _html_decision_stats(analytics_db_path: str, days: int = 7) -> str:
    COLORS = {
        "BUY": "green", "SKIP_PRICE": "yellow", "SKIP_SIZE": "yellow",
        "SKIP_OPPOSITE_HELD": "yellow",
        "SKIP_API": "red", "SKIP_NO_BOOK": "gray",
        "SKIP_TP_EXIT": "gray",
        "SKIP_ERROR": "red", "DRY_RUN": "blue",
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
        SELECT market_question, outcome, side, avg_price, amount_usd, shares, created_at
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
      <td class="{'green' if r['side'] == 'buy' else 'red'}">{r['side'].upper()}</td>
      <td class="r">{r['shares']:,.0f}</td>
      <td class="r">{r['avg_price']:.3f}</td>
      <td class="r">${r['amount_usd']:.2f}</td>
      <td class="dim">{_html_module.escape(r['created_at'][:16])}</td>
    </tr>""" for r in rows)

    return f"""
<div class="card">
  <div class="card-title">Recent Trades (last {limit})</div>
  <table>
    <thead><tr>
      <th>Market</th><th>Outcome</th><th>Side</th>
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
        return _html_page([("overview", "Overview", None, err)])

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(str(paper_db_path))
    conn.row_factory = sqlite3.Row
    try:
        open_count = conn.execute(
            "SELECT COUNT(*) FROM positions WHERE is_resolved = 0 AND shares > 0"
        ).fetchone()[0]
        resolved_count = conn.execute(
            "SELECT COUNT(*) FROM positions WHERE is_resolved = 1 OR shares = 0"
        ).fetchone()[0]
        trade_count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]

        tp_count = None
        try:
            aconn = sqlite3.connect(analytics_db_path)
            tp_count = aconn.execute("SELECT COUNT(DISTINCT market_condition_id || outcome) FROM take_profit_log").fetchone()[0]
            aconn.close()
        except Exception:
            pass

        tabs = [
            ("overview",  "Overview",        None,           _html_account_summary(conn)),
            ("positions", "Open Positions",  open_count,     _html_open_positions(conn, limit)),
            ("resolved",  "Resolved",        resolved_count, _html_resolved_positions(conn, limit)),
            ("takeprofit","Take Profit",     tp_count,       _html_take_profit_log(analytics_db_path)),
            ("signals",   "Signal Log",      None,           _html_signal_log(analytics_db_path)),
            ("bridge",    "Bridge",          None,           _html_decision_stats(analytics_db_path, days)),
            ("trades",    "Trades",          trade_count,    _html_recent_trades(conn, trade_limit)),
        ]
    finally:
        conn.close()

    return _html_page(tabs, now=now, msg=msg)


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
