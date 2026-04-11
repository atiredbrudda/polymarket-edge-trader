"""Bridge command connecting signal pipeline to paper trader.

Reads ACT/CONSIDER signals from analytics.db, checks live prices against
Q5 entry prices, sizes bets with correlation adjustment, and executes
paper trades via pm_trader.Engine.

Usage:
    polymarket --niche esports paper-bridge [--db-path PATH] [--dry-run]
"""

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

BANKROLL = 10_000.0
SPREAD_HARD_LIMIT = 0.03  # 3c — edge is gone
SPREAD_SOFT_LIMIT = 0.01  # 1-2c — reduce size by half


def _get_actionable_signals(db: sqlite_utils.Database) -> list[dict]:
    """Fetch signals with tier ACT or CONSIDER, joined with market slug."""
    query = """
        SELECT
            s.id, s.market_id, s.direction, s.tier,
            s.q5_count, s.net_q5_count, s.avg_entry_price, s.min_entry_price,
            s.avg_score, s.clv_dominant_count,
            s.event_slug, s.event_group_size,
            m.question
        FROM signals s
        JOIN markets m ON m.condition_id = s.market_id
        WHERE s.tier IN ('ACT', 'CONSIDER')
          AND (m.end_date IS NULL OR datetime(m.end_date) > datetime('now'))
    """
    cols = [
        "id", "market_id", "direction", "tier",
        "q5_count", "net_q5_count", "avg_entry_price", "min_entry_price",
        "avg_score", "clv_dominant_count",
        "event_slug", "event_group_size", "question",
    ]
    rows = db.execute(query).fetchall()
    return [dict(zip(cols, row)) for row in rows]


def _compute_size(signal: dict, account_cash: float) -> float:
    """Compute bet size based on enrichment tier + correlation adjustment.

    Sizing tiers:
        - High conviction (q5_count >= 5, CLV dominant): 2.5% bankroll
        - Standard ACT (q5_count >= 3): 2.0% bankroll
        - CONSIDER (q5_count >= 2): 1.0% bankroll

    Divided by event_group_size to avoid over-allocating to correlated markets.
    """
    q5_count = signal["q5_count"]
    clv_dominant = signal["clv_dominant_count"] or 0
    clv_ratio = clv_dominant / q5_count if q5_count > 0 else 0

    if q5_count >= 5 and clv_ratio > 0.6:
        base_pct = 0.025  # 2.5% high conviction
    elif signal["tier"] == "ACT":
        base_pct = 0.02  # 2% standard ACT
    else:
        base_pct = 0.01  # 1% CONSIDER

    event_group = signal["event_group_size"] or 1
    adjusted_pct = base_pct / event_group

    return account_cash * adjusted_pct


def _map_outcome(direction: str) -> str:
    """Map our LONG/SHORT to paper trader outcome.

    LONG = YES side (outcomes[0]), SHORT = NO side (outcomes[1]).
    The paper trader validates against the market's actual outcomes,
    so we pass 'yes'/'no' and let it normalize.
    """
    return "yes" if direction == "LONG" else "no"


def _log_decision(
    db: sqlite_utils.Database,
    signal: dict,
    decision: str,
    live_price: float | None = None,
    spread: float | None = None,
    size_usd: float = 0.0,
    reason: str = "",
) -> None:
    """Log every signal evaluation to the bridge_decisions table."""
    if "bridge_decisions" not in db.table_names():
        db.execute("""
            CREATE TABLE IF NOT EXISTS bridge_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id TEXT,
                market_id TEXT,
                direction TEXT,
                tier TEXT,
                q5_count INTEGER,
                net_q5_count INTEGER,
                q5_avg_entry REAL,
                live_price REAL,
                spread_vs_q5 REAL,
                decision TEXT,
                size_usd REAL,
                event_group_size INTEGER,
                reason TEXT,
                checked_at TEXT
            )
        """)

    db.execute(
        """
        INSERT INTO bridge_decisions (
            signal_id, market_id, direction, tier, q5_count, net_q5_count,
            q5_avg_entry, live_price, spread_vs_q5, decision, size_usd,
            event_group_size, reason, checked_at
        ) VALUES (
            :signal_id, :market_id, :direction, :tier, :q5_count, :net_q5_count,
            :q5_avg_entry, :live_price, :spread_vs_q5, :decision, :size_usd,
            :event_group_size, :reason, :checked_at
        )
        """,
        {
            "signal_id": signal["id"],
            "market_id": signal["market_id"],
            "direction": signal["direction"],
            "tier": signal["tier"],
            "q5_count": signal["q5_count"],
            "net_q5_count": signal["net_q5_count"],
            "q5_avg_entry": signal["avg_entry_price"],
            "live_price": live_price,
            "spread_vs_q5": spread,
            "decision": decision,
            "size_usd": size_usd,
            "event_group_size": signal["event_group_size"],
            "reason": reason,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    db.conn.commit()


def _check_event_exposure(
    portfolio: list[dict], signal: dict, max_event_pct: float = 0.10
) -> float | None:
    """Check if we already have exposure to this event.

    Returns existing exposure amount, or None if no exposure.
    Skips check if signal has no event_slug.
    """
    event_slug = signal["event_slug"]
    if not event_slug:
        return None

    # We can't directly match event_slug to portfolio positions since
    # the paper trader doesn't store event_slug. Instead, we track
    # by market_id (condition_id) — same event = same event_slug in
    # our markets table, but paper trader only knows condition_id.
    # For now, return None — the event_group_size sizing already
    # handles correlation. Full exposure check requires cross-DB join.
    return None


def _run_bridge(db_path: str, dry_run: bool, paper_data_dir: str) -> None:
    """Core bridge logic."""
    from pm_trader.engine import Engine
    from pm_trader.models import SimError

    # Open analytics DB
    analytics_db = init_database(Path(db_path))

    # Open paper trader engine
    paper_dir = Path(paper_data_dir)
    paper_dir.mkdir(parents=True, exist_ok=True)
    engine = Engine(paper_dir)

    # Ensure account exists
    try:
        account = engine.get_account()
    except SimError:
        account = engine.init_account(BANKROLL)
        console.print(f"[green]Initialized paper account with ${BANKROLL:,.0f}[/green]")

    signals = _get_actionable_signals(analytics_db)
    if not signals:
        console.print("[yellow]No actionable signals found.[/yellow]")
        engine.close()
        return

    console.print(f"\n[bold]=== Paper Trading Bridge ===[/bold]")
    console.print(f"Account cash: ${account.cash:,.2f}")
    console.print(f"Signals to evaluate: {len(signals)}\n")

    results = Table(title="Signal Evaluations")
    results.add_column("Market", max_width=40)
    results.add_column("Dir")
    results.add_column("Tier")
    results.add_column("Q5/Net")
    results.add_column("Q5 Entry")
    results.add_column("Live")
    results.add_column("Spread")
    results.add_column("Decision")
    results.add_column("Size")

    buys = 0
    skips = 0

    for sig in signals:
        signal = sig
        outcome = _map_outcome(signal["direction"])

        # Fetch live price via paper trader API
        try:
            market = engine.api.get_market(signal["market_id"])
            token_id = market.get_token_id(outcome)
            live_price = engine.api.get_midpoint(token_id)
        except Exception as e:
            _log_decision(analytics_db, signal, "SKIP_API", reason=str(e))
            results.add_row(
                signal.get("question", signal["market_id"])[:40],
                signal["direction"], signal["tier"],
                f"{signal['q5_count']}/{signal['net_q5_count']}",
                f"{signal['avg_entry_price']:.3f}" if signal["avg_entry_price"] else "?",
                "ERR", "", "SKIP_API", ""
            )
            skips += 1
            continue

        q5_entry = signal["avg_entry_price"] or 0
        spread = live_price - q5_entry

        # Price check
        if spread > SPREAD_HARD_LIMIT:
            _log_decision(analytics_db, signal, "SKIP_PRICE",
                          live_price, spread, reason=f"spread {spread:.3f} > {SPREAD_HARD_LIMIT}")
            results.add_row(
                signal.get("question", "")[:40],
                signal["direction"], signal["tier"],
                f"{signal['q5_count']}/{signal['net_q5_count']}",
                f"{q5_entry:.3f}", f"{live_price:.3f}", f"{spread:+.3f}",
                "[red]SKIP_PRICE[/red]", ""
            )
            skips += 1
            continue

        # Compute size
        size_usd = _compute_size(signal, account.cash)

        # Reduce size if spread is in soft zone (1-3c)
        if spread > SPREAD_SOFT_LIMIT:
            size_usd *= 0.5

        # Floor at minimum order
        if size_usd < 1.0:
            _log_decision(analytics_db, signal, "SKIP_SIZE",
                          live_price, spread, reason="size below $1 minimum")
            results.add_row(
                signal.get("question", "")[:40],
                signal["direction"], signal["tier"],
                f"{signal['q5_count']}/{signal['net_q5_count']}",
                f"{q5_entry:.3f}", f"{live_price:.3f}", f"{spread:+.3f}",
                "[yellow]SKIP_SIZE[/yellow]", f"${size_usd:.2f}"
            )
            skips += 1
            continue

        if dry_run:
            _log_decision(analytics_db, signal, "DRY_RUN",
                          live_price, spread, size_usd)
            results.add_row(
                signal.get("question", "")[:40],
                signal["direction"], signal["tier"],
                f"{signal['q5_count']}/{signal['net_q5_count']}",
                f"{q5_entry:.3f}", f"{live_price:.3f}", f"{spread:+.3f}",
                "[blue]DRY_RUN[/blue]", f"${size_usd:.2f}"
            )
            continue

        # Execute paper trade
        try:
            result = engine.buy(signal["market_id"], outcome, size_usd)
            _log_decision(analytics_db, signal, "BUY",
                          live_price, spread, size_usd)
            results.add_row(
                signal.get("question", "")[:40],
                signal["direction"], signal["tier"],
                f"{signal['q5_count']}/{signal['net_q5_count']}",
                f"{q5_entry:.3f}", f"{live_price:.3f}", f"{spread:+.3f}",
                "[green]BUY[/green]",
                f"${size_usd:.2f}"
            )
            buys += 1
            # Refresh account for next sizing calculation
            account = engine.get_account()
        except SimError as e:
            _log_decision(analytics_db, signal, "SKIP_ERROR",
                          live_price, spread, reason=str(e))
            results.add_row(
                signal.get("question", "")[:40],
                signal["direction"], signal["tier"],
                f"{signal['q5_count']}/{signal['net_q5_count']}",
                f"{q5_entry:.3f}", f"{live_price:.3f}", f"{spread:+.3f}",
                f"[red]ERROR[/red]", str(e)[:20]
            )
            skips += 1

    console.print(results)
    console.print(f"\n[bold]Summary:[/bold] {buys} buys, {skips} skips")

    if not dry_run:
        account = engine.get_account()
        console.print(f"Remaining cash: ${account.cash:,.2f}")

    engine.close()


@cli.command("paper-bridge")
@click.option("--db-path", default="data/analytics.db",
              help="Path to analytics SQLite database")
@click.option("--paper-data-dir", default="data/paper_trader",
              help="Directory for paper trader data")
@click.option("--dry-run", is_flag=True, default=False,
              help="Evaluate signals without executing trades")
@click.pass_context
def paper_bridge(ctx: Any, db_path: str, paper_data_dir: str, dry_run: bool) -> None:
    """Execute paper trades based on detected signals.

    Reads ACT/CONSIDER signals, checks live prices vs Q5 entry,
    and executes paper buys via polymarket-paper-trader.

    Use --dry-run to see what would be traded without executing.
    """
    _run_bridge(db_path, dry_run, paper_data_dir)
