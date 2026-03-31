"""Backfill command for ingesting historical trades with 2-tier API/Graph orchestration.

This command fetches historical trades for all discovered traders in a niche,
using the Data API first (Tier 1) and falling back to The Graph (Tier 2) when
the API returns 0 trades.

Usage:
    polymarket --niche esports backfill [--db-path PATH]
"""

import asyncio
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import click
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TimeElapsedColumn,
    TextColumn,
)

from polymarket_analytics.cli import cli
from polymarket_analytics.api.data import DataAPIClient
from polymarket_analytics.api.graph import GraphAPIClient, parse_graph_event
from polymarket_analytics.db.schema import init_database
from polymarket_analytics.extraction.patterns import EntityPatternMatcher
from polymarket_analytics.extraction.llm import LLMFallback


console = Console()


async def fetch_trades_with_retry(
    client: DataAPIClient,
    trader_address: str,
    max_retries: int = 10,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
) -> List[dict]:
    """Fetch trades from Data API with exponential backoff for HTTP 425.

    Args:
        client: DataAPIClient instance
        trader_address: Trader wallet address
        max_retries: Maximum retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds

    Returns:
        List of trade dicts from API

    Raises:
        click.ClickException: If max retries exceeded
    """
    delay = base_delay
    last_error: Optional[Exception] = None

    for attempt in range(max_retries):
        try:
            trades = await client.fetch_user_trades(trader_address)
            return trades
        except Exception as e:
            error_str = str(e)
            # Check for HTTP 425 (CLOB API restart) or similar rate-limit errors
            if "425" in error_str or "Too Early" in error_str:
                last_error = e
                console.print(
                    f"  [yellow]HTTP 425 for {trader_address[:8]}... (attempt {attempt + 1}/{max_retries}), "
                    f"retrying in {delay:.1f}s[/yellow]"
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, max_delay)
                continue
            else:
                # Other errors - don't retry, just warn
                console.print(
                    f"  [red]Error fetching trades for {trader_address[:8]}...: {e}[/red]"
                )
                return []

    # Max retries exceeded
    raise click.ClickException(
        f"Failed to fetch trades for {trader_address[:8]}... after {max_retries} retries: {last_error}"
    )


async def backfill_trader(
    db: Any,
    trader_address: str,
    data_client: DataAPIClient,
    graph_client: GraphAPIClient,
) -> Dict[str, int]:
    """Backfill trades for a single trader with 2-tier logic.

    Args:
        db: sqlite-utils Database instance
        trader_address: Trader wallet address
        data_client: DataAPIClient for Tier 1
        graph_client: GraphAPIClient for Tier 2 fallback

    Returns:
        Dict with ingested, skipped, fallback counts
    """
    stats = {"ingested": 0, "skipped": 0, "fallback": False}

    # Scoring window: 30 days + 10-day safeguard
    COVERAGE_DAYS = 40
    coverage_cutoff = datetime.now(timezone.utc) - timedelta(days=COVERAGE_DAYS)

    # Tier 1: Try Data API first
    api_trades = await fetch_trades_with_retry(data_client, trader_address)

    # Tier 2: Graph fallback if API doesn't cover the full 40-day window.
    # "Covers" means at least one trade predates the cutoff (oldest trade >= 40 days ago).
    # If API returns 0 trades OR all trades are within the last 40 days, use Graph.
    def _api_covers_window(trades: list) -> bool:
        for t in trades:
            ts = t.get("timestamp")
            if ts is None:
                continue
            try:
                if isinstance(ts, int):
                    trade_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                else:
                    trade_dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                if trade_dt <= coverage_cutoff:
                    return True
            except Exception:
                continue
        return False

    needs_graph = not api_trades or not _api_covers_window(api_trades)

    if needs_graph:
        stats["fallback"] = True
        graph_events = await graph_client.fetch_trader_trades(trader_address)
        # Merge Graph trades with API trades (union — INSERT OR IGNORE deduplicates)
        for event in graph_events:
            api_trades.append(parse_graph_event(event, trader_address))

    if not api_trades:
        return stats

    # Process trades
    now = datetime.now(timezone.utc).isoformat()

    for trade in api_trades:
        # Handle both API and Graph trade formats
        if "trade_id" in trade:
            # Already parsed (Graph format)
            trade_id = trade["trade_id"]
            token_id = trade["token_id"]
            side = trade["side"]
            price_str = trade["price"]
            size_str = trade["size"]
            timestamp = trade["timestamp"]
        else:
            # API format
            trade_id = (
                trade.get("trade_id")
                or f"{trader_address}_{trade.get('txHash', '')}_{trade.get('timestamp', '')}"
            )
            token_id = trade.get("asset") or trade.get("asset_id")
            side = "BUY" if trade.get("side") == "BUY" else "SELL"
            price_str = str(trade.get("price", "0"))
            size_str = str(trade.get("size", "0"))
            timestamp = trade.get("timestamp")

        if not token_id:
            stats["skipped"] += 1
            continue

        # Token catalog lookup: resolve token_id -> condition_id
        catalog_result = list(
            db.query(
                "SELECT condition_id FROM token_catalog WHERE token_id = :token_id",
                {"token_id": str(token_id)},
            )
        )

        if not catalog_result:
            stats["skipped"] += 1
            continue

        condition_id = catalog_result[0]["condition_id"]

        # Convert price to Decimal
        try:
            price = Decimal(price_str)
            # Convert Graph decimal odds to implied probability if > 1.0
            if price > 1:
                price = Decimal("1") / price
        except Exception:
            price = Decimal("0")

        # Convert size to Decimal
        try:
            size = Decimal(size_str)
        except Exception:
            size = Decimal("0")

        # Convert timestamp to ISO format
        if isinstance(timestamp, int):
            # Unix timestamp from Graph
            try:
                timestamp_iso = datetime.fromtimestamp(
                    timestamp, tz=timezone.utc
                ).isoformat()
            except (ValueError, OSError):
                timestamp_iso = now
        else:
            # Already ISO format or None
            timestamp_iso = timestamp if timestamp else now

        # Prepare trade record
        trade_data = {
            "trade_id": trade_id,
            "token_id": str(token_id),
            "timestamp": timestamp_iso,
            "side": side,
            "price": price,
            "size": size,
            "market_id": condition_id,  # Real condition_id from catalog lookup
            "trader_address": trader_address,
        }

        # Insert with INSERT OR IGNORE (idempotent via PRIMARY KEY)
        try:
            db["trades"].insert(trade_data, replace=False)
            stats["ingested"] += 1
        except Exception:
            stats["skipped"] += 1

    # Mark trader as backfill complete
    if stats["ingested"] > 0 or stats["skipped"] > 0:
        db["traders"].update(trader_address, {"backfill_complete": True})

    return stats


async def backfill_async(ctx, db_path: str) -> None:
    """Async backfill implementation."""
    niche = ctx.obj.get("niche", "esports")
    config = ctx.obj.get("config")

    if not config:
        raise click.ClickException(f"No config found for niche: {niche}")

    # Initialize database
    db_path_obj = Path(db_path)
    if not db_path_obj.parent.exists():
        db_path_obj.parent.mkdir(parents=True, exist_ok=True)

    db = init_database(db_path_obj)

    console.print("[bold]=== Backfilling Trade History ===[/bold]\n")

    # Dependency assertions
    if not db["traders"].exists():
        raise click.ClickException(
            "traders table does not exist. Run discover command first."
        )
    if not db["token_catalog"].exists():
        raise click.ClickException(
            "token_catalog table does not exist. Run classify-tokens command first."
        )

    # Query traders needing backfill
    traders = list(db.query(
        "SELECT address FROM traders WHERE backfill_complete = False OR backfill_complete IS NULL"
    ))

    if not traders:
        console.print("[green]All traders already backfilled. Skipping to entity extraction.[/green]")
    else:
        console.print(f"[bold]Step 1/2[/bold] Fetching trades for {len(traders):,} traders...")

    if traders:
        # Initialize API clients
        data_client = DataAPIClient()
        graph_client = GraphAPIClient(api_key=None)

        start_time = time.time()
        total_stats = {
            "traders_processed": 0,
            "trades_ingested": 0,
            "trades_skipped": 0,
            "graph_fallbacks": 0,
            "errors": 0,
        }

        def _desc() -> str:
            return (
                f"[cyan]Traders[/cyan]  "
                f"[dim]ingested: {total_stats['trades_ingested']:,} | "
                f"skipped: {total_stats['trades_skipped']:,} | "
                f"graph fallbacks: {total_stats['graph_fallbacks']:,} | "
                f"errors: {total_stats['errors']:,}[/dim]"
            )

        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                console=console,
                transient=False,
            ) as progress:
                task = progress.add_task(_desc(), total=len(traders))

                for trader in traders:
                    trader_address = trader["address"]
                    progress.update(
                        task,
                        description=f"[cyan]↓ trades[/cyan]  [dim]{trader_address[:10]}...[/dim]",
                    )

                    try:
                        stats = await backfill_trader(
                            db,
                            trader_address,
                            data_client,
                            graph_client,
                        )

                        total_stats["traders_processed"] += 1
                        total_stats["trades_ingested"] += stats["ingested"]
                        total_stats["trades_skipped"] += stats["skipped"]
                        if stats["fallback"]:
                            total_stats["graph_fallbacks"] += 1

                    except click.ClickException:
                        raise
                    except Exception as e:
                        total_stats["errors"] += 1
                        total_stats["traders_processed"] += 1
                        console.print(f"  [red]✗ {trader_address[:10]}...: {e}[/red]")

                    progress.update(task, description=_desc())
                    progress.advance(task)

            elapsed = time.time() - start_time
            console.print(
                f"\n[bold green]Backfill complete[/bold green] ({elapsed:.1f}s)\n"
                f"  Traders processed:    {total_stats['traders_processed']:,}\n"
                f"  Trades ingested:      {total_stats['trades_ingested']:,}\n"
                f"  Trades skipped:       {total_stats['trades_skipped']:,}\n"
                f"  Graph fallbacks used: {total_stats['graph_fallbacks']:,}\n"
                f"  Errors:               {total_stats['errors']:,}"
            )

        finally:
            await data_client.close()
            await graph_client.close()

    # -------------------------------------------------------------------------
    # Step 2: Post-backfill entity extraction
    # Markets touched by backfill may never have been seen by discover,
    # so they have no market_entities row → invisible to build-positions.
    # -------------------------------------------------------------------------
    console.print("\n[bold]Step 2/2[/bold] Post-backfill entity extraction...")

    markets_needing_entities = list(db.query(
        """
        SELECT DISTINCT t.market_id AS condition_id, m.question, m.event_slug
        FROM trades t
        JOIN markets m ON m.condition_id = t.market_id
        LEFT JOIN market_entities me ON me.condition_id = t.market_id
        WHERE (me.condition_id IS NULL OR (me.game IS NULL AND me.team_a IS NULL))
          AND m.niche_slug = :niche
          AND m.question IS NOT NULL
        """,
        {"niche": niche},
    ))

    if not markets_needing_entities:
        console.print("  [green]✓[/green] All markets already have entities extracted.")
        return

    console.print(f"  Found {len(markets_needing_entities):,} markets without entity rows")

    # Setup extractors
    pattern_matcher = EntityPatternMatcher()
    llm_fallback: Optional[LLMFallback] = None
    try:
        llm_fallback = LLMFallback()
        console.print("  [green]✓[/green] LLM fallback ready")
    except ValueError as e:
        console.print(f"  [yellow]⚠ LLM unavailable: {e}[/yellow]")

    # Pre-seed event_slug → entities from DB (siblings extracted in prior runs)
    event_slug_entities: Dict[str, Dict[str, Any]] = {}
    rows = db.execute("""
        SELECT m.event_slug, me.game, me.team_a, me.team_b, me.tournament, me.market_type
        FROM market_entities me
        JOIN markets m ON me.condition_id = m.condition_id
        WHERE m.event_slug IS NOT NULL AND me.game IS NOT NULL
    """).fetchall()
    for row in rows:
        slug = row[0]
        if slug and slug not in event_slug_entities:
            event_slug_entities[slug] = {
                "game": row[1], "team_a": row[2], "team_b": row[3],
                "tournament": row[4], "market_type": row[5],
            }

    entity_records: List[Dict[str, Any]] = []
    pattern_count = 0
    llm_count = 0
    event_slug_count = 0
    llm_disabled = False  # becomes True on first API error

    def _entity_id(condition_id: str, entities: Dict[str, Any]) -> str:
        entity_str = json.dumps(entities, sort_keys=True)
        return hashlib.sha256(f"{condition_id}:{entity_str}".encode()).hexdigest()[:16]

    def _desc() -> str:
        return (
            f"[cyan]Entities[/cyan]  "
            f"[dim]pattern: {pattern_count - event_slug_count:,} | "
            f"event_slug: {event_slug_count:,} | llm: {llm_count:,} | "
            f"total: {len(entity_records):,}[/dim]"
        )

    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task(_desc(), total=len(markets_needing_entities))

        for row in markets_needing_entities:
            cid = row["condition_id"]
            question = row["question"]
            event_slug = row["event_slug"]

            entities = pattern_matcher.extract(question)
            pattern_incomplete = (
                entities.get("game") is None or entities.get("team_a") is None
            )

            # event_slug fallback: inherit entities from a sibling market
            if pattern_incomplete and event_slug and event_slug in event_slug_entities:
                entities = event_slug_entities[event_slug]
                event_slug_count += 1
                pattern_incomplete = False

            # LLM fallback: only if pattern and event_slug both failed
            if pattern_incomplete and not llm_disabled and llm_fallback is not None:
                progress.update(
                    task,
                    description=f"[cyan]⚙ LLM[/cyan]  [dim]{question[:58]}[/dim]",
                )
                try:
                    entities = llm_fallback.extract(question)
                    llm_count += 1
                except Exception as e:
                    llm_disabled = True
                    llm_fallback = None
                    console.print(
                        f"  [yellow]⚠ LLM disabled after error: {e}[/yellow]\n"
                        f"  [dim]Remaining markets will use pattern-only extraction.[/dim]"
                    )

            if entities.get("game") is not None or entities.get("team_a") is not None:
                pattern_count += 1
                # Cache for siblings processed later in this run
                if event_slug and event_slug not in event_slug_entities:
                    event_slug_entities[event_slug] = entities

            entity_records.append({
                "id": _entity_id(cid, entities),
                "condition_id": cid,
                "game": entities.get("game"),
                "team_a": entities.get("team_a"),
                "team_b": entities.get("team_b"),
                "tournament": entities.get("tournament"),
                "market_type": entities.get("market_type"),
            })

            progress.update(task, description=_desc())
            progress.advance(task)

    if entity_records:
        with console.status(
            f"[bold green]Writing {len(entity_records):,} entities to DB...",
            spinner="dots",
        ):
            with db.conn:
                db.conn.executemany(
                    """
                    INSERT INTO market_entities (id, condition_id, game, team_a, team_b, tournament, market_type)
                    VALUES (:id, :condition_id, :game, :team_a, :team_b, :tournament, :market_type)
                    ON CONFLICT(condition_id) DO UPDATE SET
                        id          = excluded.id,
                        game        = excluded.game,
                        team_a      = excluded.team_a,
                        team_b      = excluded.team_b,
                        tournament  = excluded.tournament,
                        market_type = excluded.market_type
                    """,
                    entity_records,
                )
        console.print(
            f"  [green]✓[/green] {len(entity_records):,} entities written "
            f"(pattern: {pattern_count - event_slug_count:,}, event_slug: {event_slug_count:,}, LLM: {llm_count:,})"
        )

    return


@cli.command()
@click.option(
    "--db-path",
    default="data/analytics.db",
    help="Path to SQLite database (default: data/analytics.db)",
)
@click.pass_context
def backfill(ctx, db_path: str) -> None:
    """Backfill historical trades for niche traders.

    This command:
    1. Asserts dependencies exist (traders, token_catalog tables)
    2. Queries traders with backfill_complete=False
    3. For each trader:
       - Tier 1: Fetch trades from Data API
       - Tier 2: Graph fallback if API returns 0 trades
    4. Resolves token_id -> condition_id via token_catalog lookup
    5. Inserts trades with INSERT OR IGNORE (idempotent)
    6. Sets backfill_complete=True after successful backfill

    Args:
        ctx: Click context with niche and config
        db_path: Path to SQLite database
    """
    asyncio.run(backfill_async(ctx, db_path))
