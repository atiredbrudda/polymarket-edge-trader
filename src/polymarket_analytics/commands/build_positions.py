"""Build-positions command for aggregating trades into positions.

This command aggregates raw trades into one position per (trader, market) pair
with direction, size, volume-weighted entry price, and timestamps.

Usage:
    polymarket --niche esports build-positions [--db-path PATH]
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
from rich.console import Console

from src.polymarket_analytics.cli import cli
from src.polymarket_analytics.db.schema import init_database
from src.polymarket_analytics.positions.aggregation import build_positions_from_trades


console = Console()


async def _build_positions_async(ctx: Any, db_path: str) -> None:
    """Async build-positions implementation."""
    niche = ctx.obj.get("niche", "esports")
    config = ctx.obj.get("config")

    if not config:
        raise click.ClickException(f"No config found for niche: {niche}")

    # Initialize database
    db_path_obj = Path(db_path)
    if not db_path_obj.parent.exists():
        db_path_obj.parent.mkdir(parents=True, exist_ok=True)

    db = init_database(db_path_obj)

    # Print header
    console.print("[bold]=== Building Positions ===[/bold]\n")

    # Dependency assertions
    # Assert trades table exists
    if not db["trades"].exists():
        raise click.ClickException(
            "trades table does not exist. Run backfill command first."
        )

    # Assert market_entities table exists
    if not db["market_entities"].exists():
        raise click.ClickException(
            "market_entities table does not exist. Run discover command first."
        )

    # Assert positions table exists
    if not db["positions"].exists():
        raise click.ClickException(
            "positions table does not exist. Check schema initialization."
        )

    # Run aggregation with spinner
    start_time = datetime.now(timezone.utc)

    with console.status("[bold green]Aggregating positions...", spinner="dots"):
        position_count = build_positions_from_trades(db, niche)

    end_time = datetime.now(timezone.utc)
    elapsed = (end_time - start_time).total_seconds()

    # Print summary
    console.print(f"\n[green]Positions built successfully ({elapsed:.1f}s)[/green]")
    console.print(f"  [bold]Positions created/updated:[/bold] {position_count:,}")


@cli.command()
@click.option(
    "--db-path",
    default="data/analytics.db",
    help="Path to SQLite database (default: data/analytics.db)",
)
@click.pass_context
def build_positions(ctx: Any, db_path: str) -> None:
    """Build positions from trades for the specified niche.

    This command:
    1. Asserts dependencies exist (trades, market_entities, positions tables)
    2. Aggregates trades into one position per (trader, market) pair
    3. Calculates direction (LONG/SHORT/FLAT) based on net signed size
    4. Computes volume-weighted average entry price
    5. Tracks entry_timestamp and last_trade_timestamp

    Args:
        ctx: Click context with niche and config
        db_path: Path to SQLite database
    """
    asyncio.run(_build_positions_async(ctx, db_path))
