"""Take-profit command for paper trading positions.

Scans open positions where the current price has moved ``threshold``× from
avg_entry_price and exits them to lock in the CLV edge before late reversal.

Also fills in final outcomes for previously exited positions so the user can
see whether the take-profit level was well-calibrated.

Usage:
    polymarket --niche esports paper-take-profit [--dry-run]
    polymarket --niche esports paper-take-profit --threshold 1.6
"""

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
import sqlite_utils
from rich.console import Console
from rich.table import Table

from polymarket_analytics.cli import cli
from polymarket_analytics.db.schema import init_database

console = Console()

DEFAULT_THRESHOLD = 1.5  # exit when live_price >= avg_entry * threshold

_PRICE_CACHE_FILE = ".price_cache.json"
_PRICE_CACHE_TTL = 900  # 15 minutes — same cron pass is always within this window


def _read_price_cache(paper_dir: Path) -> dict:
    """Load the price snapshot written by paper-bridge, if fresh enough."""
    try:
        data = json.loads((paper_dir / _PRICE_CACHE_FILE).read_text())
        if time.time() - data.get("written_at", 0) > _PRICE_CACHE_TTL:
            return {}
        return data
    except (OSError, json.JSONDecodeError, KeyError):
        return {}


_CREATE_TP_LOG = """
    CREATE TABLE IF NOT EXISTS take_profit_log (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        market_condition_id TEXT    NOT NULL,
        outcome             TEXT    NOT NULL,
        entry_price         REAL    NOT NULL,
        exit_price          REAL    NOT NULL,
        shares              REAL    NOT NULL,
        exit_value_usd      REAL    NOT NULL,
        threshold           REAL    NOT NULL,
        exited_at           TEXT    NOT NULL,
        -- filled in once the market resolves
        final_outcome       TEXT,
        final_price         REAL,
        counterfactual_pnl  REAL,
        outcome_filled_at   TEXT
    )
"""


# ─── helpers ─────────────────────────────────────────────────────────────────

def _ensure_tp_log(analytics_db: sqlite_utils.Database) -> None:
    analytics_db.execute(_CREATE_TP_LOG)
    analytics_db.conn.commit()


def _ensure_book_dead_column(paper_dir: Path) -> None:
    """Add book_dead column to paper.db positions if missing.

    Set to 1 once CLOB returns "No orderbook exists" so we stop re-polling
    a position whose book has been removed (game ended, awaiting Gamma
    resolution). Without this flag, take-profit scans the same dead-book
    position every 30min and logs a redundant SKIP_NO_BOOK each time.
    """
    db_path = paper_dir / "paper.db"
    if not db_path.exists():
        return
    conn = sqlite3.connect(str(db_path))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(positions)").fetchall()}
    if "book_dead" not in cols:
        conn.execute("ALTER TABLE positions ADD COLUMN book_dead INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    conn.close()


def _mark_book_dead(paper_dir: Path, market_id: str, outcome: str) -> None:
    """Flag a position as orderbook-removed so subsequent take-profit scans skip it."""
    db_path = paper_dir / "paper.db"
    if not db_path.exists():
        return
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE positions SET book_dead=1 WHERE market_condition_id=? AND outcome=?",
        (market_id, outcome),
    )
    conn.commit()
    conn.close()


def _load_open_positions(paper_dir: Path) -> list[dict]:
    """Return all unresolved paper positions with shares > 0 and a live orderbook."""
    db_path = paper_dir / "paper.db"
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT market_condition_id, outcome, shares, avg_entry_price, market_question "
        "FROM positions "
        "WHERE is_resolved=0 AND shares>0 AND COALESCE(book_dead,0)=0"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _log_decision(
    analytics_db: sqlite_utils.Database,
    market_id: str,
    outcome: str,
    decision: str,
    live_price: float | None = None,
    entry_price: float = 0.0,
    size_usd: float = 0.0,
    reason: str = "",
) -> None:
    """Append a row to bridge_decisions for dashboard visibility."""
    if "bridge_decisions" not in analytics_db.table_names():
        analytics_db.execute("""
            CREATE TABLE IF NOT EXISTS bridge_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id TEXT, market_id TEXT, direction TEXT,
                tier TEXT, q5_count INTEGER, net_q5_count INTEGER,
                q5_avg_entry REAL, live_price REAL, spread_vs_q5 REAL,
                decision TEXT, size_usd REAL, event_group_size INTEGER,
                reason TEXT, checked_at TEXT
            )
        """)

    direction = "LONG" if outcome.lower() == "yes" else "SHORT"
    spread = (live_price - entry_price) if live_price is not None else None
    analytics_db.execute(
        """
        INSERT INTO bridge_decisions (
            signal_id, market_id, direction, tier, q5_count, net_q5_count,
            q5_avg_entry, live_price, spread_vs_q5, decision, size_usd,
            event_group_size, reason, checked_at
        ) VALUES (
            NULL, :market_id, :direction, NULL, NULL, NULL,
            :entry, :live_price, :spread, :decision, :size_usd,
            NULL, :reason, :checked_at
        )
        """,
        {
            "market_id": market_id,
            "direction": direction,
            "entry": entry_price,
            "live_price": live_price,
            "spread": spread,
            "decision": decision,
            "size_usd": size_usd,
            "reason": reason,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    analytics_db.conn.commit()


def _record_tp_exit(
    analytics_db: sqlite_utils.Database,
    position: dict,
    exit_price: float,
    threshold: float,
) -> None:
    """Insert a take_profit_log row for a newly exited position."""
    shares = position["shares"]
    analytics_db.execute(
        """
        INSERT INTO take_profit_log (
            market_condition_id, outcome, entry_price, exit_price,
            shares, exit_value_usd, threshold, exited_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            position["market_condition_id"],
            position["outcome"],
            position["avg_entry_price"],
            exit_price,
            shares,
            shares * exit_price,
            threshold,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    analytics_db.conn.commit()


# ─── check-back: fill in final outcomes ──────────────────────────────────────

def _fill_final_outcomes(analytics_db: sqlite_utils.Database) -> list[dict]:
    """Fill final_outcome for TP log rows whose market has since resolved.

    Returns list of newly-resolved rows for display.
    """
    from polymarket_analytics.commands.paper_dashboard import (
        _determine_winner,
    )

    pending = analytics_db.execute(
        "SELECT id, market_condition_id, outcome, entry_price, exit_price, shares "
        "FROM take_profit_log WHERE final_outcome IS NULL"
    ).fetchall()

    if not pending:
        return []

    filled = []
    for row in pending:
        tp_id, market_id, tp_outcome, entry_price, exit_price, shares = row

        # Look up the resolved market in analytics.db
        market_row = analytics_db.execute(
            """
            SELECT outcome, question FROM markets
            WHERE condition_id = ?
              AND (resolved = 1 OR active = 0)
              AND outcome IS NOT NULL
            """,
            [market_id],
        ).fetchone()

        if market_row is None:
            continue  # not yet resolved — skip

        winning_outcome = market_row[0]
        question = market_row[1] or ""

        # Determine final price for our position:
        #   1.0 if our outcome won, 0.0 if lost, entry_price if VOID
        if winning_outcome.upper() == "VOID":
            final_price = entry_price  # refunded at cost
            final_label = "VOID"
        else:
            won = _determine_winner(tp_outcome, winning_outcome, [], question=question)
            if won is True:
                final_price = 1.0
                final_label = "WON"
            elif won is False:
                final_price = 0.0
                final_label = "LOST"
            else:
                continue  # can't map team name — skip until we can

        # Counterfactual P&L: what would we have gained/lost by holding?
        # Positive = we missed extra gains; negative = TP saved us from a loss
        counterfactual_pnl = (final_price - exit_price) * shares

        analytics_db.execute(
            """
            UPDATE take_profit_log
            SET final_outcome = ?, final_price = ?,
                counterfactual_pnl = ?, outcome_filled_at = ?
            WHERE id = ?
            """,
            (
                final_label,
                final_price,
                counterfactual_pnl,
                datetime.now(timezone.utc).isoformat(),
                tp_id,
            ),
        )
        analytics_db.conn.commit()

        filled.append({
            "market_condition_id": market_id,
            "outcome": tp_outcome,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "final_outcome": final_label,
            "final_price": final_price,
            "counterfactual_pnl": counterfactual_pnl,
            "shares": shares,
        })

    return filled


def _print_resolved_tps(filled: list[dict]) -> None:
    """Print the check-back table for newly resolved TP exits."""
    t = Table(title="Take-Profit Outcomes (newly resolved)")
    t.add_column("Market ID", max_width=20)
    t.add_column("Out")
    t.add_column("Entry")
    t.add_column("Exited @")
    t.add_column("Final")
    t.add_column("Result")
    t.add_column("Counterfactual P&L", justify="right")
    t.add_column("TP verdict")

    for r in filled:
        final = r["final_outcome"]
        cpnl = r["counterfactual_pnl"]

        if final == "WON":
            result_str = "[yellow]WON[/yellow]"
            # positive counterfactual = left money on table; negative shouldn't happen
            verdict = "[yellow]Left money on table[/yellow]" if cpnl > 0 else "[green]Perfect[/green]"
            cpnl_str = f"[yellow]+${cpnl:,.2f}[/yellow]" if cpnl > 0 else f"[green]${cpnl:,.2f}[/green]"
        elif final == "LOST":
            result_str = "[red]LOST[/red]"
            # negative counterfactual = TP saved us from losing more
            verdict = "[green]TP saved the trade[/green]"
            cpnl_str = f"[green]${cpnl:,.2f}[/green]"
        else:  # VOID
            result_str = "[dim]VOID[/dim]"
            verdict = "[dim]—[/dim]"
            cpnl_str = "[dim]$0.00[/dim]"

        t.add_row(
            r["market_condition_id"][:18] + "…",
            r["outcome"],
            f"{r['entry_price']:.3f}",
            f"{r['exit_price']:.3f}",
            f"{r['final_price']:.2f}",
            result_str,
            cpnl_str,
            verdict,
        )

    console.print(t)
    console.print(
        "[dim]Counterfactual P&L = what holding to resolution would have added "
        "(positive = left gains; negative = losses avoided)[/dim]\n"
    )


# ─── core scan ───────────────────────────────────────────────────────────────

def _run_take_profit(
    db_path: str, paper_data_dir: str, dry_run: bool, threshold: float
) -> None:
    from pm_trader.engine import Engine
    from pm_trader.models import SimError

    analytics_db = init_database(Path(db_path))
    _ensure_tp_log(analytics_db)
    paper_dir = Path(paper_data_dir)
    _ensure_book_dead_column(paper_dir)
    engine = Engine(paper_dir)
    price_cache = _read_price_cache(paper_dir)

    # ── 1. Check-back: fill in final outcomes for past TP exits ──────────────
    filled = _fill_final_outcomes(analytics_db)
    if filled:
        console.print(f"\n[bold]=== TP Check-Back: {len(filled)} outcome(s) resolved ===[/bold]")
        _print_resolved_tps(filled)
    else:
        console.print("[dim]No pending TP outcomes resolved yet.[/dim]\n")

    # ── 2. Scan open positions for new take-profit opportunities ─────────────
    positions = _load_open_positions(paper_dir)
    if not positions:
        console.print("[yellow]No open positions found.[/yellow]")
        engine.close()
        return

    console.print(f"[bold]=== Take-Profit Scan ===[/bold]")
    console.print(f"Open positions: {len(positions)}  |  Threshold: {threshold:.1f}x entry\n")

    t = Table(title="Take-Profit Scan")
    t.add_column("Market", max_width=40)
    t.add_column("Out")
    t.add_column("Entry")
    t.add_column("Live")
    t.add_column("Ratio")
    t.add_column("Shares")
    t.add_column("Decision")
    t.add_column("Value")

    exits = 0
    holds = 0
    errors = 0

    for pos in positions:
        market_id = pos["market_condition_id"]
        outcome = pos["outcome"]
        avg_entry = pos["avg_entry_price"] or 0.0
        shares = pos["shares"]
        label = (pos.get("market_question") or market_id)[:40]

        if avg_entry <= 0:
            errors += 1
            t.add_row(label, outcome, "—", "—", "—", f"{shares:.1f}",
                      "[red]SKIP_ENTRY[/red]", "")
            continue

        # Fetch live price — try the bridge price cache first (written seconds ago),
        # fall back to a live API call only for cache misses.
        cached_tokens = price_cache.get("market_tokens", {}).get(market_id, [])
        cached_token_id = next(
            (tok["token_id"] for tok in cached_tokens
             if tok.get("outcome", "").lower() == outcome.lower()),
            None,
        )
        cached_price = (
            price_cache.get("token_prices", {}).get(cached_token_id)
            if cached_token_id else None
        )

        if cached_price is not None:
            live_price = cached_price
        else:
            try:
                market = engine.api.get_market(market_id)
                cached_token_id = market.get_token_id(outcome)
                live_price = engine.api.get_midpoint(cached_token_id)
            except Exception as e:
                err = str(e)
                if "No orderbook exists" in err:
                    decision = "SKIP_NO_BOOK"
                    dec_label = "[dim]SKIP_NO_BOOK[/dim]"
                    # Stop polling — book is gone, no take-profit exit possible.
                    # paper-resolve-outcomes will settle this position when Gamma resolves.
                    _mark_book_dead(paper_dir, market_id, outcome)
                else:
                    decision = "SKIP_API"
                    dec_label = "[red]SKIP_API[/red]"
                _log_decision(analytics_db, market_id, outcome, decision,
                              reason=err, entry_price=avg_entry)
                t.add_row(label, outcome, f"{avg_entry:.3f}", "ERR", "—",
                          f"{shares:.1f}", dec_label, "")
                errors += 1
                continue

        ratio = live_price / avg_entry
        value_usd = shares * live_price

        if ratio >= threshold:
            action = "DRY_RUN" if dry_run else "TAKE_PROFIT"
            if not dry_run:
                # Simulate bid-side fill before committing — midpoint can lie on thin books.
                try:
                    from pm_trader.orderbook import simulate_sell_fill
                    book = engine.api.get_order_book(cached_token_id)
                    fee_rate_bps = engine.api.get_fee_rate(cached_token_id)
                    fill_preview = simulate_sell_fill(book, shares, fee_rate_bps)
                    if fill_preview.avg_price < avg_entry:
                        _log_decision(
                            analytics_db, market_id, outcome, "SKIP_THIN_BOOK",
                            fill_preview.avg_price, avg_entry, value_usd,
                            reason=f"fill {fill_preview.avg_price:.3f} < entry {avg_entry:.3f}",
                        )
                        t.add_row(
                            label, outcome,
                            f"{avg_entry:.3f}", f"{live_price:.3f}", f"{ratio:.2f}x",
                            f"{shares:.1f}", "[yellow]SKIP_THIN_BOOK[/yellow]",
                            f"${fill_preview.avg_price * shares:.2f}",
                        )
                        errors += 1
                        continue
                except Exception as e:
                    _log_decision(analytics_db, market_id, outcome, "SKIP_API",
                                  live_price, avg_entry, value_usd, reason=str(e))
                    t.add_row(label, outcome, f"{avg_entry:.3f}", f"{live_price:.3f}",
                              f"{ratio:.2f}x", f"{shares:.1f}", "[red]SKIP_API[/red]", "")
                    errors += 1
                    continue

                try:
                    result = engine.sell(market_id, outcome, shares)
                    actual_exit_price = result.trade.avg_price
                    _record_tp_exit(analytics_db, pos, actual_exit_price, threshold)
                except SimError as e:
                    _log_decision(analytics_db, market_id, outcome, "SKIP_ERROR",
                                  live_price, avg_entry, value_usd, reason=str(e))
                    t.add_row(label, outcome, f"{avg_entry:.3f}", f"{live_price:.3f}",
                              f"{ratio:.2f}x", f"{shares:.1f}",
                              f"[red]ERROR[/red]", str(e)[:20])
                    errors += 1
                    continue

            _log_decision(analytics_db, market_id, outcome, action,
                          live_price, avg_entry, value_usd,
                          reason=f"ratio {ratio:.2f} >= {threshold:.1f}")
            color = "blue" if dry_run else "green"
            t.add_row(
                label, outcome,
                f"{avg_entry:.3f}", f"{live_price:.3f}", f"{ratio:.2f}x",
                f"{shares:.1f}",
                f"[{color}]{action}[/{color}]", f"${value_usd:.2f}"
            )
            exits += 1
        else:
            holds += 1
            t.add_row(
                label, outcome,
                f"{avg_entry:.3f}", f"{live_price:.3f}", f"{ratio:.2f}x",
                f"{shares:.1f}",
                "[dim]HOLD[/dim]", f"${value_usd:.2f}"
            )

    console.print(t)
    console.print(
        f"\n[bold]Summary:[/bold] {exits} exit{'s' if exits != 1 else ''}, "
        f"{holds} hold{'s' if holds != 1 else ''}, {errors} error{'s' if errors != 1 else ''}"
    )
    if dry_run and exits:
        console.print("[dim]--dry-run: no trades executed[/dim]")

    engine.close()


# ─── CLI entry point ──────────────────────────────────────────────────────────

@cli.command("paper-take-profit")
@click.option("--db-path", default="data/analytics.db",
              help="Path to analytics SQLite database")
@click.option("--paper-data-dir", default="data/paper_trader",
              help="Directory for paper trader data")
@click.option("--dry-run", is_flag=True, default=False,
              help="Show which positions would be exited without selling")
@click.option("--threshold", default=DEFAULT_THRESHOLD, type=float, show_default=True,
              help="Exit when live_price >= avg_entry_price * threshold")
@click.pass_context
def paper_take_profit(
    ctx: Any, db_path: str, paper_data_dir: str, dry_run: bool, threshold: float
) -> None:
    """Exit positions that have moved threshold-x from entry price.

    Runs in two phases each time:

    \b
    1. Check-back — fills in final outcomes for previously exited positions
       and shows whether each TP exit was well-timed (left money on the table
       vs saved a losing trade).

    \b
    2. Scan — checks all open positions against the threshold and sells any
       that qualify, logging each decision to bridge_decisions.

    Counterfactual P&L = (final_resolution_price - exit_price) × shares.
    Positive means you left gains on the table; negative means the TP
    prevented a loss.
    """
    _run_take_profit(db_path, paper_data_dir, dry_run, threshold)
