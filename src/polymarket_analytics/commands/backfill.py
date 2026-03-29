"""Backfill command for ingesting historical trades with 2-tier API/Graph orchestration.

This command fetches historical trades for all discovered traders in a niche,
using the Data API first (Tier 1) and falling back to The Graph (Tier 2) when
the API returns 0 trades.

Usage:
    polymarket --niche esports backfill [--db-path PATH]
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import click
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TaskProgressColumn,
    TimeElapsedColumn,
    TextColumn,
)

from src.polymarket_analytics.cli import cli
from src.polymarket_analytics.api.data import DataAPIClient
from src.polymarket_analytics.api.graph import GraphAPIClient, parse_graph_event
from src.polymarket_analytics.db.schema import init_database


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

    # Tier 1: Try Data API first
    api_trades = await fetch_trades_with_retry(data_client, trader_address)

    # Tier 2: Graph fallback if API returns 0 trades
    if not api_trades:
        stats["fallback"] = True
        console.print(
            f"  [yellow]API returned 0 trades for {trader_address[:8]}..., using Graph fallback[/yellow]"
        )
        graph_events = await graph_client.fetch_trader_trades(trader_address)
        # Parse Graph events to trade format
        for event in graph_events:
            trade_data = parse_graph_event(event, trader_address)
            api_trades.append(trade_data)

    if not api_trades:
        # No trades from either source
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
            # Token not in catalog - skip this trade (don't insert with synthetic ID)
            stats["skipped"] += 1
            console.print(
                f"  [yellow]Skipped trade {trade_id[:8]}...: token_id {token_id} not in catalog[/yellow]"
            )
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
        except Exception as e:
            # UNIQUE constraint violation or other error
            if "UNIQUE" in str(e) or "PRIMARY KEY" in str(e):
                stats["skipped"] += 1
            else:
                console.print(
                    f"  [red]Error inserting trade {trade_id[:8]}...: {e}[/red]"
                )

    # Mark trader as backfill complete
    if stats["ingested"] > 0 or stats["skipped"] > 0:
        db["traders"].update({"address": trader_address, "backfill_complete": True})

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

    # Dependency assertions (RESL-01, RESL-02)
    console.print("[bold]=== Backfilling Trade History ===[/bold]\n")

    # Assert traders table exists
    if not db["traders"].exists():
        raise click.ClickException(
            "traders table does not exist. Run discover command first."
        )

    # Assert token_catalog table exists
    if not db["token_catalog"].exists():
        raise click.ClickException(
            "token_catalog table does not exist. Run classify-tokens command first."
        )

    # Query traders needing backfill
    traders_query = """
        SELECT address FROM traders WHERE backfill_complete = False OR backfill_complete IS NULL
    """
    traders = list(db.query(traders_query))

    if not traders:
        console.print("[green]All traders already backfilled.[/green]")
        return

    console.print(f"Found {len(traders)} traders needing backfill\n")

    # Initialize API clients
    data_client = DataAPIClient()
    graph_client = GraphAPIClient(api_key=None)  # Graph API key optional

    try:
        # Main backfill loop with progress bar
        total_stats = {
            "traders_processed": 0,
            "trades_ingested": 0,
            "trades_skipped": 0,
            "graph_fallbacks": 0,
        }

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=False,
        ) as progress:
            task = progress.add_task(
                f"[cyan]Backfilling traders for {niche}",
                total=len(traders),
            )

            for trader in traders:
                trader_address = trader["address"]
                progress.update(
                    task,
                    description=f"[cyan]Processing {trader_address[:8]}...",
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

                    if stats["ingested"] > 0:
                        console.print(
                            f"  [green]+{stats['ingested']} trades[/green], "
                            f"[yellow]{stats['skipped']} skipped[/yellow]"
                        )

                except click.ClickException as e:
                    # Re-raise click exceptions (like max retries)
                    raise
                except Exception as e:
                    console.print(
                        f"  [red]Error processing {trader_address[:8]}...: {e}[/red]"
                    )
                    total_stats["traders_processed"] += 1

                progress.advance(task)

        # Print summary
        console.print("\n[bold]Backfill complete[/bold]")
        console.print(f"  Traders processed:      {total_stats['traders_processed']}")
        console.print(f"  Trades ingested:        {total_stats['trades_ingested']:,}")
        console.print(f"  Trades skipped:         {total_stats['trades_skipped']:,}")
        console.print(f"  Graph fallbacks used:   {total_stats['graph_fallbacks']}")

    finally:
        # Cleanup clients
        await data_client.close()
        await graph_client.close()


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
