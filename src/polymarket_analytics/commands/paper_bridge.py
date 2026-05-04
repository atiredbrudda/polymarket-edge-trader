"""Bridge command connecting signal pipeline to paper trader.

Reads ACT/CONSIDER signals from analytics.db, checks live prices against
Q5 entry prices, sizes bets with correlation adjustment, and executes
paper trades via pm_trader.Engine.

Usage:
    polymarket --niche esports paper-bridge [--db-path PATH] [--dry-run]
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
from polymarket_analytics.scoring.thresholds import Q5_COMPOSITE_THRESHOLD

console = Console()

BANKROLL = 10_000.0
SPREAD_HARD_LIMIT = 0.03  # 3c — edge is gone (slippage cap)
SPREAD_SOFT_LIMIT = 0.01  # 1-2c — reduce size by half
NEGATIVE_SPREAD_FLOOR = -0.30  # falling knife — Q5's pre-game thesis disproven by post-news drift
PRICE_FLOOR = 0.05        # skip decided markets (backtest used 0.05-0.95 range)

_PRICE_CACHE_FILE = ".price_cache.json"
_JOURNAL_FILE = "decision_journal.log"


class _Journal:
    """Append-only strategy rules log.

    Records the active trading rules at the start of each bridge run.
    When a rule changes, the difference is visible by comparing headers.
    File lives next to paper.db at data/paper_trader/decision_journal.log.
    """

    def __init__(self, paper_dir: Path):
        self._path = paper_dir / _JOURNAL_FILE
        self._f = open(self._path, "a")

    def run_header(self, cash: float, n_signals: int, n_held: int,
                   n_tp_exited: int) -> None:
        self._f.write(
            f"\n{'=' * 80}\n"
            f"BRIDGE RUN  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            f"{'=' * 80}\n"
            f"Cash: ${cash:,.2f}  |  Signals: {n_signals}  |  "
            f"Open: {n_held}  |  TP-exited: {n_tp_exited}\n"
            f"\n"
            f"Entry rules:\n"
            f"  Signal tier      : ACT (net_q5 >= 3, not all-CLV-dom) + CONSIDER (net_q5 >= 2)\n"
            f"  Spread hard limit: {SPREAD_HARD_LIMIT}  → SKIP if live > q5_entry + this\n"
            f"  Spread soft limit: {SPREAD_SOFT_LIMIT}  → half size if spread > this\n"
            f"  Falling-knife    : {NEGATIVE_SPREAD_FLOOR}  → SKIP if live < q5_entry + this\n"
            f"  Price floor      : {PRICE_FLOOR}  → SKIP if live price below this\n"
            f"\n"
            f"Sizing:\n"
            f"  ACT              : 2.0% bankroll (net_q5 >= 3, not all-CLV-dom)\n"
            f"  CONSIDER         : 1.0% bankroll (net_q5 >= 2 OR all-CLV-dom)\n"
            f"  Correlated adj   : ÷ event_group_size\n"
            f"  Minimum order    : $1.00\n"
            f"\n"
            f"Exit rules:\n"
            f"  Take-profit      : sell at 1.5x entry (50% gain)\n"
            f"  Stop-loss        : none (proven harmful — 95% false-stop rate)\n"
            f"\n"
            f"Guardrails:\n"
            f"  SKIP_OPPOSITE_HELD : don't buy other side of same binary market\n"
            f"  SKIP_TP_EXIT       : don't re-enter after taking profit\n"
            f"  SKIP_NO_BOOK       : auto-resolve markets with dead orderbooks\n"
            f"  SKIP_HELD          : don't double-buy same position\n"
            f"{'=' * 80}\n"
        )
        self._f.flush()

    def close(self) -> None:
        self._f.close()


def _write_price_cache(paper_dir: Path, cache: dict) -> None:
    """Write a price snapshot so paper-take-profit can reuse prices fetched here."""
    try:
        data = {"written_at": time.time(), **cache}
        (paper_dir / _PRICE_CACHE_FILE).write_text(json.dumps(data))
    except OSError:
        pass  # non-critical — take-profit will fall back to live API


def _get_actionable_signals(db: sqlite_utils.Database) -> list[dict]:
    """Fetch ACT (net_q5 >= 3) and CONSIDER (net_q5 >= 2) signals, joined with market slug."""
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
          AND m.resolved = 0
          AND m.active = 1
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
    """Compute bet size based on tier + correlation adjustment.

    Sizing tiers:
        - ACT (net_q5 >= 3, not all-CLV-dom): 2.0% bankroll
        - CONSIDER (net_q5 >= 2 OR all-CLV-dom): 1.0% bankroll

    Divided by event_group_size to avoid over-allocating to correlated markets.

    Hi-conviction tier (was 2.5% on q5>=5 + clv_ratio>0.6) removed 2026-05-04.
    Q5_count past 3-4 carries no validated edge (historical n=6,398 + live n=727);
    the q5>=5/clv-dom>0.6 quadrant has the worst WR (46.5%) and second-worst ROI
    in live data. The override also directly contradicted the 2026-05-03 CLV-dom
    filter — both resolved by removal. See [[Plan Sizing Rework 2026-05-04]].
    """
    if signal["tier"] == "ACT":
        base_pct = 0.02
    else:
        base_pct = 0.01

    event_group = signal["event_group_size"] or 1
    adjusted_pct = base_pct / event_group

    return account_cash * adjusted_pct


def _map_outcome(direction: str) -> str:
    """Map our LONG/SHORT to paper trader outcome for binary YES/NO markets."""
    return "yes" if direction == "LONG" else "no"


def _resolve_token_and_outcome(
    db: sqlite_utils.Database,
    signal: dict,
    market: "Market",
    outcome: str,
) -> tuple[str, str]:
    """Resolve the token_id and outcome name for a signal.

    For binary YES/NO markets, uses the standard "yes"/"no" mapping.
    For head-to-head markets (team names as outcomes), falls back to looking
    up which token Q5 traders actually traded for this signal's market+direction.

    Returns (token_id, outcome_name) ready to pass to engine.buy().
    Raises ValueError if resolution fails.
    """
    # Standard path: works for binary YES/NO markets
    try:
        token_id = market.get_token_id(outcome)
        return token_id, outcome
    except ValueError:
        pass

    # Fallback: head-to-head or non-standard outcome names.
    # Find which token Q5 traders bought (LONG) or sold (SHORT) for this market.
    trade_side = "BUY" if signal["direction"] == "LONG" else "SELL"
    rows = db.execute(
        """
        SELECT t.token_id, COUNT(*) as n
        FROM trades t
        JOIN lift_scores ls ON ls.trader_address = t.trader_address
        WHERE t.market_id = ?
          AND t.side = ?
          AND ls.quintile = 5
          AND ls.composite_score >= ?
        GROUP BY t.token_id
        ORDER BY n DESC
        LIMIT 1
        """,
        [signal["market_id"], trade_side, Q5_COMPOSITE_THRESHOLD],
    ).fetchall()

    if not rows:
        raise ValueError(
            f"No Q5 {trade_side} trades found for market {signal['market_id']}"
        )

    token_id = rows[0][0]

    # Map token_id back to an outcome name the paper trader recognises
    for token in market.tokens:
        if token["token_id"] == token_id:
            return token_id, token["outcome"]

    raise ValueError(
        f"Token {token_id} found in trades but not in market.tokens "
        f"for {signal['market_id']}"
    )


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


def _load_open_positions(paper_dir: Path) -> tuple[set, dict]:
    """Return existing open positions from paper.db.

    Returns:
        held:    set of (market_condition_id, outcome) currently holding
        entries: dict of (market_condition_id, outcome) -> avg_entry_price
    """
    db_path = paper_dir / "paper.db"
    if not db_path.exists():
        return set(), {}
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT market_condition_id, outcome, avg_entry_price "
        "FROM positions WHERE is_resolved=0 AND shares>0"
    ).fetchall()
    conn.close()
    held = {(r[0], r[1].lower()) for r in rows}
    entries = {(r[0], r[1].lower()): r[2] for r in rows}
    return held, entries


def _record_snapshot(
    paper_dir: Path,
    market_condition_id: str,
    outcome: str,
    live_price: float,
    entry_price: float | None,
) -> None:
    """Append a price snapshot for an open position to paper.db.

    Called every time the bridge fetches a live price for a market where
    we already hold a position. Builds the time series needed for
    hold-vs-resolution analysis (pct_from_entry over time).
    """
    db_path = paper_dir / "paper.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS position_snapshots (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            market_condition_id  TEXT    NOT NULL,
            outcome              TEXT    NOT NULL,
            live_price           REAL    NOT NULL,
            entry_price          REAL,
            pct_from_entry       REAL,
            recorded_at          TEXT    NOT NULL
        )
    """)
    pct = (live_price - entry_price) / entry_price if entry_price else None
    conn.execute(
        "INSERT INTO position_snapshots "
        "(market_condition_id, outcome, live_price, entry_price, pct_from_entry, recorded_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (market_condition_id, outcome, live_price, entry_price, pct,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


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

    # Load existing positions — used for idempotency guard and price snapshots
    held, entry_prices = _load_open_positions(paper_dir)

    # Load TP-exited positions — don't re-enter after taking profit
    tp_exited: set[tuple[str, str]] = set()
    if "take_profit_log" in analytics_db.table_names():
        for row in analytics_db.execute(
            "SELECT DISTINCT market_condition_id, outcome FROM take_profit_log"
        ).fetchall():
            tp_exited.add((row[0], row[1].lower()))

    signals = _get_actionable_signals(analytics_db)
    if not signals:
        console.print("[yellow]No actionable signals found.[/yellow]")
        engine.close()
        return

    # Decision journal — append-only log file
    journal = _Journal(paper_dir)
    journal.run_header(account.cash, len(signals), len(held), len(tp_exited))

    console.print(f"\n[bold]=== Paper Trading Bridge ===[/bold]")
    console.print(f"Account cash: ${account.cash:,.2f}")
    console.print(f"Signals to evaluate: {len(signals)}  |  Open positions: {len(held)}\n")

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
    # Shared price snapshot written at end — consumed by paper-take-profit next stage.
    _price_cache: dict = {"token_prices": {}, "market_tokens": {}}

    for sig in signals:
        signal = sig
        outcome = _map_outcome(signal["direction"])

        # Fetch live price via paper trader API
        try:
            market = engine.api.get_market(signal["market_id"])
            token_id, resolved_outcome = _resolve_token_and_outcome(
                analytics_db, signal, market, outcome
            )
            live_price = engine.api.get_midpoint(token_id)
            # Stash for take-profit reuse
            _price_cache["token_prices"][token_id] = live_price
            if signal["market_id"] not in _price_cache["market_tokens"]:
                _price_cache["market_tokens"][signal["market_id"]] = market.tokens
        except Exception as e:
            err = str(e)
            # CLOB 404 = orderbook removed (market resolved/settled before DB caught up)
            if "No orderbook exists" in err:
                analytics_db.execute(
                    "UPDATE markets SET resolved = 1 WHERE condition_id = ?",
                    [signal["market_id"]],
                )
                decision = "SKIP_NO_BOOK"
                label = "[dim]SKIP_NO_BOOK[/dim]"
            else:
                decision = "SKIP_API"
                label = "[red]SKIP_API[/red]"
            _log_decision(analytics_db, signal, decision, reason=err)
            results.add_row(
                signal.get("question", signal["market_id"])[:40],
                signal["direction"], signal["tier"],
                f"{signal['q5_count']}/{signal['net_q5_count']}",
                f"{signal['avg_entry_price']:.3f}" if signal["avg_entry_price"] else "?",
                "ERR", "", label, ""
            )
            skips += 1
            continue

        # Opposing position guardrail: refuse if we hold the other side
        # of the same binary market. See wiki: opposing-positions-guardrail.md
        opposite_held = [
            (m, o) for (m, o) in held
            if m == signal["market_id"] and o != resolved_outcome.lower()
        ]
        if opposite_held:
            _log_decision(analytics_db, signal, "SKIP_OPPOSITE_HELD",
                          live_price, reason=f"holding opposite outcome: {opposite_held[0][1]}")
            results.add_row(
                signal.get("question", "")[:40],
                signal["direction"], signal["tier"],
                f"{signal['q5_count']}/{signal['net_q5_count']}",
                f"{signal['avg_entry_price']:.3f}" if signal["avg_entry_price"] else "?",
                f"{live_price:.3f}", "",
                "[yellow]SKIP_OPPOSITE[/yellow]", "",
            )
            skips += 1
            continue

        # Idempotency: skip if already holding this position.
        # Also record a price snapshot so we can later compare hold-vs-exit.
        if (signal["market_id"], resolved_outcome.lower()) in held:
            entry = entry_prices.get((signal["market_id"], resolved_outcome.lower()))
            _record_snapshot(paper_dir, signal["market_id"], resolved_outcome,
                             live_price, entry)
            _log_decision(analytics_db, signal, "SKIP_HELD",
                          live_price, live_price - (entry or live_price),
                          reason="already holding position")
            results.add_row(
                signal.get("question", "")[:40],
                signal["direction"], signal["tier"],
                f"{signal['q5_count']}/{signal['net_q5_count']}",
                f"{entry:.3f}" if entry else "?",
                f"{live_price:.3f}", "",
                "[dim]SKIP_HELD[/dim]", "",
            )
            skips += 1
            continue

        # Don't re-enter a position we already took profit on
        if (signal["market_id"], resolved_outcome.lower()) in tp_exited:
            _log_decision(analytics_db, signal, "SKIP_TP_EXIT",
                          live_price, reason="already took profit on this position")
            results.add_row(
                signal.get("question", "")[:40],
                signal["direction"], signal["tier"],
                f"{signal['q5_count']}/{signal['net_q5_count']}",
                f"{signal['avg_entry_price']:.3f}" if signal["avg_entry_price"] else "?",
                f"{live_price:.3f}", "",
                "[dim]SKIP_TP_EXIT[/dim]", "",
            )
            skips += 1
            continue

        q5_entry = signal["avg_entry_price"] or 0
        spread = live_price - q5_entry

        # Floor check — skip decided markets where price has collapsed
        if live_price < PRICE_FLOOR:
            _log_decision(analytics_db, signal, "SKIP_FLOOR",
                          live_price, spread, reason=f"live {live_price:.3f} < {PRICE_FLOOR}")
            results.add_row(
                signal.get("question", "")[:40],
                signal["direction"], signal["tier"],
                f"{signal['q5_count']}/{signal['net_q5_count']}",
                f"{q5_entry:.3f}", f"{live_price:.3f}", f"{spread:+.3f}",
                "[red]SKIP_FLOOR[/red]", ""
            )
            skips += 1
            continue

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

        if spread < NEGATIVE_SPREAD_FLOOR:
            _log_decision(analytics_db, signal, "SKIP_FALLING_KNIFE",
                          live_price, spread, reason=f"spread {spread:.3f} < {NEGATIVE_SPREAD_FLOOR}")
            results.add_row(
                signal.get("question", "")[:40],
                signal["direction"], signal["tier"],
                f"{signal['q5_count']}/{signal['net_q5_count']}",
                f"{q5_entry:.3f}", f"{live_price:.3f}", f"{spread:+.3f}",
                "[red]SKIP_FALLING_KNIFE[/red]", ""
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
            result = engine.buy(signal["market_id"], resolved_outcome, size_usd)
            _log_decision(analytics_db, signal, "BUY",
                          live_price, spread, size_usd,
                          reason=f"{resolved_outcome} @ {live_price:.3f}, q5_entry={q5_entry:.3f}")
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

    # Sweep any open positions whose signals are no longer ACT/CONSIDER.
    # These were skipped by the main loop, so they have no snapshot yet
    # for this run. Extra API calls only for the stale-signal subset.
    visited = {signal["market_id"] for signal in signals}
    stale = {(mid, out) for mid, out in held if mid not in visited}
    swept = 0
    for market_condition_id, outcome in stale:
        try:
            market = engine.api.get_market(market_condition_id)
            token_id = market.get_token_id(outcome)
            live_price = engine.api.get_midpoint(token_id)
            # Stash for take-profit reuse
            _price_cache["token_prices"][token_id] = live_price
            if market_condition_id not in _price_cache["market_tokens"]:
                _price_cache["market_tokens"][market_condition_id] = market.tokens
            entry = entry_prices.get((market_condition_id, outcome))
            _record_snapshot(paper_dir, market_condition_id, outcome,
                             live_price, entry)
            swept += 1
        except Exception:
            pass  # market closed or token gone — skip silently

    if swept:
        console.print(f"[dim]Snapshotted {swept} stale-signal position(s).[/dim]")

    _write_price_cache(paper_dir, _price_cache)
    journal.close()
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
