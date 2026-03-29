"""Resolve-positions command for computing PnL from market outcomes.

This command resolves unresolved positions by computing PnL based on markets.outcome
(YES/NO) with correct formulas for all 4 direction/outcome combinations.

Usage:
    polymarket --niche esports resolve-positions [--db-path PATH]
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
from rich.console import Console

from src.polymarket_analytics.cli import cli
from src.polymarket_analytics.db.schema import init_database
from src.polymarket_analytics.positions.resolution import resolve_position_pnl

console = Console()


async def _resolve_positions_async(ctx: Any, db_path: str) -> None:
    """Async resolve-positions implementation."""
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
    console.print("[bold]=== Resolving Positions ===[/bold]\n")

    # Dependency assertions
    # Assert positions table exists
    if not db["positions"].exists():
        raise click.ClickException(
            "positions table does not exist. Check schema initialization."
        )

    # Assert markets table exists
    if not db["markets"].exists():
        raise click.ClickException(
            "markets table does not exist. Check schema initialization."
        )

    # Check for unresolved positions before running
    unresolved_count = db.execute(
        "SELECT COUNT(*) as cnt FROM positions WHERE resolved = 0"
    ).fetchone()[0]

    if unresolved_count == 0:
        raise click.ClickException(
            "No unresolved positions found. All positions already resolved."
        )

    # Check for markets with outcomes
    markets_with_outcomes = db.execute(
        "SELECT COUNT(*) as cnt FROM markets WHERE outcome IS NOT NULL"
    ).fetchone()[0]

    if markets_with_outcomes == 0:
        raise click.ClickException(
            "No market outcomes found. Run resolve-outcomes command first."
        )

    # Run resolution with spinner
    start_time = datetime.now(timezone.utc)

    with console.status("[bold green]Resolving positions...", spinner="dots"):
        resolved_count = resolve_position_pnl(db, niche)

    end_time = datetime.now(timezone.utc)
    elapsed = (end_time - start_time).total_seconds()

    # Get count of still-unresolved positions
    still_unresolved = db.execute(
        "SELECT COUNT(*) as cnt FROM positions WHERE resolved = 0"
    ).fetchone()[0]

    # Print summary
    console.print(f"\n[green]Positions resolved successfully ({elapsed:.1f}s)[/green]")
    console.print(f"  [bold]Positions resolved:[/bold] {resolved_count:,}")
    console.print(f"  [bold]Still open (unresolved):[/bold] {still_unresolved:,}")


@cli.command()
@click.option(
    "--db-path",
    default="data/analytics.db",
    help="Path to SQLite database (default: data/analytics.db)",
)
@click.pass_context
def resolve_positions(ctx: Any, db_path: str) -> None:
    """Resolve positions and compute PnL for the specified niche.

    This command:
    1. Asserts dependencies exist (positions, markets tables)
    2. Checks for unresolved positions and market outcomes
    3. Updates positions with resolved=1, outcome (WIN/LOSS/FLAT), and pnl
    4. Uses SQL CASE expression for PnL calculation

    PnL formulas:
    - LONG + YES: size * (1.0 - entry) → WIN
    - LONG + NO: size * (0.0 - entry) → LOSS
    - SHORT + NO: size * entry → WIN
    - SHORT + YES: size * (entry - 1.0) → LOSS
    - FLAT: 0 → FLAT

    Args:
        ctx: Click context with niche and config
        db_path: Path to SQLite database
    """
    asyncio.run(_resolve_positions_async(ctx, db_path))
