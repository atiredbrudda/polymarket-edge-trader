"""Monitor command — polls Q5 traders for new entries on any market.

Instead of discovering markets first and finding traders (discover's approach),
this command monitors known Q5 traders and discovers markets from their activity.
This catches entry-price alpha early, before the line moves.

See: LLM Wiki / Discovery Timing Paradox

Usage:
    polymarket --niche esports monitor [--since 24] [--dry-run] [--chain] [--poll 60]
"""

import asyncio
import json
import os
import signal
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

from polymarket_analytics.api.data import DataAPIClient
from polymarket_analytics.api.gamma import GammaAPIClient
from polymarket_analytics.api.graph import GraphAPIClient
from polymarket_analytics.cli import cli
from polymarket_analytics.commands.backfill import (
    ShutdownManager,
    backfill_trader,
    fetch_trades_with_retry,
)
from polymarket_analytics.db.schema import init_database
from polymarket_analytics.extraction.patterns import EntityPatternMatcher
from polymarket_analytics.extraction.slug_parser import parse_event_slug

console = Console()

CONCURRENT_LIMIT = 10


def _load_q5_traders(db: Any, niche: str) -> tuple[list[dict], str]:
    """Load Q5 traders with their last_monitored_at timestamps.

    Returns (traders_list, computed_at_iso).
    """
    # Get latest scoring timestamp for staleness reporting
    computed_row = db.execute(
        "SELECT MAX(computed_at) FROM lift_scores WHERE category = ?",
        [niche],
    ).fetchone()
    computed_at = computed_row[0] if computed_row and computed_row[0] else "never"

    rows = db.execute(
        """
        SELECT qt.trader_address, t.last_monitored_at, t.last_trade_seen_at
        FROM q5_traders qt
        JOIN traders t ON t.address = qt.trader_address
        WHERE qt.category = :niche
        """,
        {"niche": niche},
    ).fetchall()

    traders = [
        {
            "address": row[0],
            "last_monitored_at": row[1],
            "last_trade_seen_at": row[2],
        }
        for row in rows
    ]
    return traders, computed_at


def _get_since_ts(trader: dict, default_since_hours: int) -> Optional[int]:
    """Compute since_unix_ts for a trader based on last_monitored_at or default."""
    if trader["last_monitored_at"]:
        try:
            dt = datetime.fromisoformat(trader["last_monitored_at"])
            return int(dt.timestamp())
        except Exception:
            pass
    # Fall back to --since hours
    cutoff = datetime.now(timezone.utc) - timedelta(hours=default_since_hours)
    return int(cutoff.timestamp())


def _filter_by_niche(
    trades: list[dict],
    known_markets: dict[str, str],
    allowed_prefixes: set[str],
) -> tuple[list[dict], set[str]]:
    """Filter trades to niche-relevant markets.

    Args:
        trades: Raw trades from API
        known_markets: {condition_id: event_slug} for markets in DB
        allowed_prefixes: Set of allowed event_slug prefixes

    Returns:
        (niche_trades, unknown_condition_ids)
    """
    niche_trades = []
    unknown_cids: Set[str] = set()

    for trade in trades:
        cid = trade.get("conditionId") or trade.get("condition_id")
        if not cid:
            continue

        if cid in known_markets:
            slug = known_markets[cid]
            prefix = slug.split("-")[0] if slug else ""
            if not allowed_prefixes or prefix in allowed_prefixes:
                niche_trades.append(trade)
        else:
            unknown_cids.add(cid)

    return niche_trades, unknown_cids


async def _discover_markets(
    gamma: GammaAPIClient,
    condition_ids: set[str],
    db: Any,
    niche: str,
    allowed_prefixes: set[str],
    pattern_matcher: EntityPatternMatcher,
) -> dict[str, str]:
    """Auto-discover unknown markets from Gamma API.

    Returns {condition_id: event_slug} for markets that passed the prefix filter.
    Also upserts markets, token_catalog, and market_entities.
    """
    discovered: dict[str, str] = {}
    now_iso = datetime.now(timezone.utc).isoformat()
    cid_list = list(condition_ids)
    total = len(cid_list)
    completed = 0
    passed_filter = 0
    semaphore = asyncio.Semaphore(10)

    async def _fetch_one_market(cid: str) -> tuple[str, Any]:
        nonlocal completed
        async with semaphore:
            try:
                market = await gamma.fetch_market_by_condition(cid)
            except Exception:
                market = None
            completed += 1
            end = "\n" if completed == total else "\r"
            print(f"    [{completed}/{total}] markets fetched   ", end=end, flush=True)
            return cid, market

    fetch_results = await asyncio.gather(*[_fetch_one_market(cid) for cid in cid_list])

    for cid, market in fetch_results:
        if not market:
            continue

        # Extract event_slug
        events = market.get("events", [])
        event_slug = events[0].get("slug", "") if events else ""
        prefix = event_slug.split("-")[0] if event_slug else ""

        if allowed_prefixes and prefix not in allowed_prefixes:
            continue

        passed_filter += 1

        # Upsert market
        db.execute(
            """
            INSERT INTO markets (condition_id, question, outcome, resolved, niche_slug,
                                 created_at, end_date, category, active, tokens, event_slug)
            VALUES (:condition_id, :question, :outcome, :resolved, :niche_slug,
                    :created_at, :end_date, :category, :active, :tokens, :event_slug)
            ON CONFLICT(condition_id) DO UPDATE SET
                question = excluded.question,
                end_date = excluded.end_date,
                active   = excluded.active,
                tokens   = excluded.tokens,
                event_slug = excluded.event_slug
            """,
            {
                "condition_id": cid,
                "question": market.get("question", ""),
                "outcome": None,
                "resolved": False,
                "niche_slug": niche,
                "created_at": now_iso,
                "end_date": market.get("endDate"),
                "category": niche,
                "active": True,
                "tokens": json.dumps(market.get("tokens", [])),
                "event_slug": event_slug,
            },
        )

        # Upsert token_catalog from clobTokenIds
        clob_token_ids_raw = market.get("clobTokenIds")
        if clob_token_ids_raw:
            try:
                if isinstance(clob_token_ids_raw, str):
                    clob_token_ids = json.loads(clob_token_ids_raw)
                else:
                    clob_token_ids = clob_token_ids_raw
            except (json.JSONDecodeError, ValueError):
                clob_token_ids = []
        else:
            clob_token_ids = []

        if clob_token_ids:
            question = market.get("question", "")
            outcomes = market.get("outcomes", "YES,NO")
            if isinstance(outcomes, list):
                outcomes = ",".join(outcomes)
            outcome_list = outcomes.split(",") if outcomes else []
            market_type = "binary" if outcome_list == ["YES", "NO"] else "categorical"

            for token_id in clob_token_ids[:2]:
                db.execute(
                    """
                    INSERT INTO token_catalog (token_id, condition_id, question, niche_slug, node_path, market_type, created_at)
                    VALUES (:token_id, :condition_id, :question, :niche_slug, :node_path, :market_type, :created_at)
                    ON CONFLICT(token_id) DO UPDATE SET
                        condition_id = excluded.condition_id,
                        question = excluded.question
                    """,
                    {
                        "token_id": token_id,
                        "condition_id": cid,
                        "question": question,
                        "niche_slug": niche,
                        "node_path": f"{niche}/{niche}",
                        "market_type": market_type,
                        "created_at": now_iso,
                    },
                )

        # Entity extraction (patterns + slug parser, no LLM)
        question = market.get("question", "")
        entities = pattern_matcher.extract(question)
        if entities.get("game") is None or entities.get("team_a") is None:
            if event_slug:
                parsed = parse_event_slug(event_slug)
                if parsed.get("game"):
                    entities = parsed

        if entities.get("game") or entities.get("team_a"):
            import hashlib

            entity_str = json.dumps(entities, sort_keys=True)
            eid = hashlib.sha256(f"{cid}:{entity_str}".encode()).hexdigest()[:16]
            db.execute(
                """
                INSERT INTO market_entities (id, condition_id, game, team_a, team_b, tournament, market_type)
                VALUES (:id, :condition_id, :game, :team_a, :team_b, :tournament, :market_type)
                ON CONFLICT(id) DO NOTHING
                """,
                {
                    "id": eid,
                    "condition_id": cid,
                    "game": entities.get("game"),
                    "team_a": entities.get("team_a"),
                    "team_b": entities.get("team_b"),
                    "tournament": entities.get("tournament"),
                    "market_type": entities.get("market_type"),
                },
            )

        db.conn.commit()
        discovered[cid] = event_slug

    return discovered


async def _monitor_pass(
    ctx: Any,
    db: Any,
    niche: str,
    config: Any,
    since_hours: int,
    dry_run: bool,
    shutdown: ShutdownManager,
) -> dict[str, int]:
    """Run a single monitoring pass. Returns stats dict."""
    stats = {
        "q5_traders": 0,
        "traders_polled": 0,
        "new_trades": 0,
        "new_markets": 0,
        "niche_filtered": 0,
        "traders_with_trades": 0,
    }

    # Phase 1: Load Q5 traders
    traders, computed_at = _load_q5_traders(db, niche)
    stats["q5_traders"] = len(traders)

    if not traders:
        console.print("[yellow]No Q5 traders found. Run score first.[/yellow]")
        return stats

    console.print(f"  Q5 traders: {len(traders)} (scored at: {computed_at})")

    # Phase 2: Concurrent trade fetching
    console.print(f"  Fetching new trades (concurrency={CONCURRENT_LIMIT})...")

    data_client = DataAPIClient()
    graph_client = GraphAPIClient(api_key=os.getenv("GRAPH_API_KEY"))
    gamma_client = GammaAPIClient()

    semaphore = asyncio.Semaphore(CONCURRENT_LIMIT)
    fetch_completed = 0

    async def _fetch_one(trader: dict) -> tuple[str, list, int]:
        nonlocal fetch_completed
        since_ts = _get_since_ts(trader, since_hours)
        if shutdown.shutdown_requested:
            return trader["address"], [], since_ts
        async with semaphore:
            if shutdown.shutdown_requested:
                return trader["address"], [], since_ts
            try:
                trades = await fetch_trades_with_retry(
                    data_client, trader["address"], since_unix_ts=since_ts
                )
            except Exception:
                trades = []
            fetch_completed += 1
            end = "\n" if fetch_completed == len(traders) else "\r"
            print(f"    [{fetch_completed}/{len(traders)}] traders fetched   ", end=end, flush=True)
            return trader["address"], trades, since_ts

    results = await asyncio.gather(*[_fetch_one(t) for t in traders])
    stats["traders_polled"] = len(results)

    if shutdown.shutdown_requested:
        return stats

    # Phase 3: Filter by niche
    allowed_prefixes = set(getattr(config, "event_slug_prefixes", []) or [])

    # Load known markets for prefix checking
    known_markets: dict[str, str] = {}
    for row in db.execute(
        "SELECT condition_id, event_slug FROM markets"
    ).fetchall():
        known_markets[row[0]] = row[1] or ""

    # Build since_ts map so Phase 5 can pass it to backfill_trader
    since_ts_map: dict[str, int] = {addr: ts for addr, _, ts in results}

    # Group trades by trader, filter by niche
    trader_niche_trades: dict[str, list] = {}
    all_unknown_cids: set[str] = set()
    total_raw = 0

    for address, trades, _since_ts in results:
        if not trades:
            continue
        total_raw += len(trades)
        niche_trades, unknown_cids = _filter_by_niche(
            trades, known_markets, allowed_prefixes
        )
        all_unknown_cids.update(unknown_cids)
        if niche_trades:
            trader_niche_trades[address] = niche_trades

    console.print(
        f"  Raw trades: {total_raw}, "
        f"niche-matched: {sum(len(t) for t in trader_niche_trades.values())}, "
        f"unknown markets: {len(all_unknown_cids)}"
    )

    # Phase 4: Auto-discover unknown markets
    if all_unknown_cids and not dry_run:
        console.print(f"  Discovering {len(all_unknown_cids)} unknown markets...")
        pattern_matcher = EntityPatternMatcher()
        discovered = await _discover_markets(
            gamma_client, all_unknown_cids, db, niche, allowed_prefixes, pattern_matcher
        )
        stats["new_markets"] = len(discovered)
        console.print(f"    {len(discovered)} passed niche filter")

        # Update known_markets and re-filter trades that were in unknown_cids
        known_markets.update(discovered)
        for address, trades, _since_ts in results:
            if not trades:
                continue
            # Re-check trades on newly-discovered markets
            for trade in trades:
                cid = trade.get("conditionId") or trade.get("condition_id")
                if cid and cid in discovered:
                    if address not in trader_niche_trades:
                        trader_niche_trades[address] = []
                    trader_niche_trades[address].append(trade)

    stats["niche_filtered"] = sum(len(t) for t in trader_niche_trades.values())
    stats["traders_with_trades"] = len(trader_niche_trades)

    if dry_run:
        console.print(f"  [blue]DRY RUN — skipping trade upsert[/blue]")
        _print_summary(stats, trader_niche_trades, db)
        await _cleanup(data_client, gamma_client)
        return stats

    # Phase 5: Delegate to backfill_trader for trade normalization + upsert.
    # Pass since_unix_ts so backfill_trader treats this as incremental and skips
    # the 40-day Graph coverage check (historical trades are already in the DB).
    if trader_niche_trades:
        console.print(
            f"  Upserting trades for {len(trader_niche_trades)} traders..."
        )
        # Load global token catalog for backfill_trader
        global_catalog = {
            row[0]: row[1]
            for row in db.execute(
                "SELECT token_id, condition_id FROM token_catalog"
            ).fetchall()
        }

        ingested_total = 0
        upsert_total = len(trader_niche_trades)
        for i, (address, trades) in enumerate(trader_niche_trades.items(), 1):
            if shutdown.shutdown_requested:
                break
            end = "\n" if i == upsert_total else "\r"
            print(f"    [{i}/{upsert_total}] upserting trader {address[:10]}...   ", end=end, flush=True)
            try:
                result = await backfill_trader(
                    db,
                    address,
                    data_client,
                    graph_client,
                    since_unix_ts=since_ts_map.get(address),
                    prefetched_trades=trades,
                    global_catalog=global_catalog,
                )
                ingested_total += result.get("ingested", 0)
            except Exception as e:
                console.print(
                    f"    [yellow]Failed {address[:10]}...: {e}[/yellow]"
                )

        stats["new_trades"] = ingested_total
        console.print(f"    {ingested_total} trades ingested")

    # Phase 6: Update last_monitored_at for all polled traders
    now_iso = datetime.now(timezone.utc).isoformat()
    with db.conn:
        db.conn.executemany(
            "UPDATE traders SET last_monitored_at = ? WHERE address = ?",
            [(now_iso, addr) for addr, _, _ts in results],
        )

    _print_summary(stats, trader_niche_trades, db)
    await _cleanup(data_client, gamma_client)
    return stats


def _print_summary(
    stats: dict, trader_trades: dict[str, list], db: Any
) -> None:
    """Print a summary table of the monitoring pass."""
    table = Table(title="Monitor Summary")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("Q5 traders", str(stats["q5_traders"]))
    table.add_row("Traders polled", str(stats["traders_polled"]))
    table.add_row("Traders with niche trades", str(stats["traders_with_trades"]))
    table.add_row("Niche-relevant trades", str(stats["niche_filtered"]))
    table.add_row("New markets discovered", str(stats["new_markets"]))
    table.add_row("Trades ingested", str(stats["new_trades"]))

    console.print(table)

    # Show per-market breakdown if there are trades
    if trader_trades:
        market_counts: dict[str, int] = {}
        for trades in trader_trades.values():
            for t in trades:
                cid = t.get("conditionId") or t.get("condition_id") or "?"
                market_counts[cid] = market_counts.get(cid, 0) + 1

        if market_counts:
            mtable = Table(title="Trades by Market")
            mtable.add_column("Market", max_width=50)
            mtable.add_column("Trades", justify="right")

            # Look up questions for display
            market_questions: dict[str, str] = {}
            cids = list(market_counts.keys())
            if cids:
                placeholders = ",".join("?" * len(cids))
                for row in db.execute(
                    f"SELECT condition_id, question FROM markets WHERE condition_id IN ({placeholders})",
                    cids,
                ).fetchall():
                    market_questions[row[0]] = row[1]

            for cid, count in sorted(
                market_counts.items(), key=lambda x: -x[1]
            )[:15]:
                label = market_questions.get(cid, cid)[:50]
                mtable.add_row(label, str(count))

            console.print(mtable)


async def _cleanup(data_client: DataAPIClient, gamma_client: GammaAPIClient) -> None:
    """Close API clients."""
    try:
        await data_client.close()
    except Exception:
        pass
    try:
        await gamma_client.close()
    except Exception:
        pass


async def _monitor_async(
    ctx: Any,
    db_path: str,
    since_hours: int,
    dry_run: bool,
    chain: bool,
    poll_minutes: Optional[int],
) -> None:
    """Main monitor entrypoint."""
    niche = ctx.obj.get("niche", "esports")
    config = ctx.obj.get("config")

    if not config:
        raise click.ClickException(f"No config found for niche: {niche}")

    db = init_database(Path(db_path))

    # Dependency checks
    if "lift_scores" not in db.table_names():
        raise click.ClickException(
            "lift_scores table does not exist. Run score first."
        )

    shutdown = ShutdownManager()
    loop = asyncio.get_running_loop()
    shutdown.install(loop)

    try:
        pass_num = 0
        while True:
            pass_num += 1
            if poll_minutes:
                console.print(
                    f"\n[bold]=== Monitor Pass #{pass_num} ===[/bold]"
                )
            else:
                console.print("\n[bold]=== Q5 Trader Monitor ===[/bold]")

            stats = await _monitor_pass(
                ctx, db, niche, config, since_hours, dry_run, shutdown
            )

            if shutdown.shutdown_requested:
                shutdown.print_interrupted_summary()
                break

            # Chain: run build-positions + detect
            if chain and not dry_run and stats["new_trades"] > 0:
                console.print("\n[bold]Chaining: build-positions → detect[/bold]")
                from polymarket_analytics.commands.build_positions import (
                    _build_positions_async,
                )
                from polymarket_analytics.commands.detect import _detect_async

                await _build_positions_async(ctx, db_path)
                await _detect_async(ctx, db_path)

            if not poll_minutes:
                break

            console.print(
                f"\n[dim]Next pass in {poll_minutes} minutes. Ctrl+C to stop.[/dim]"
            )
            # Sleep in small increments so shutdown is responsive
            for _ in range(poll_minutes * 60):
                if shutdown.shutdown_requested:
                    break
                await asyncio.sleep(1)

            if shutdown.shutdown_requested:
                shutdown.print_interrupted_summary()
                break
    finally:
        shutdown.uninstall(loop)


@cli.command()
@click.option(
    "--db-path",
    default="data/analytics.db",
    help="Path to SQLite database",
)
@click.option(
    "--since",
    "since_hours",
    default=24,
    type=int,
    help="Look back N hours for new trades (default: 24)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Fetch and filter but don't write to DB",
)
@click.option(
    "--chain",
    is_flag=True,
    default=False,
    help="Run build-positions + detect after monitoring",
)
@click.option(
    "--poll",
    "poll_minutes",
    default=None,
    type=int,
    help="Poll continuously every N minutes (default: single-shot)",
)
@click.pass_context
def monitor(
    ctx: Any,
    db_path: str,
    since_hours: int,
    dry_run: bool,
    chain: bool,
    poll_minutes: Optional[int],
) -> None:
    """Monitor Q5 traders for new entries on any market.

    Polls known Q5 traders for recent trades, filters to niche-relevant
    markets, auto-discovers unknown markets, and upserts trades.

    Use --chain to automatically run build-positions + detect after.
    Use --poll N to run continuously every N minutes.
    """
    asyncio.run(
        _monitor_async(ctx, db_path, since_hours, dry_run, chain, poll_minutes)
    )
