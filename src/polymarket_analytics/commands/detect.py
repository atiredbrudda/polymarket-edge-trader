"""Detect command for consensus signal detection.

This command orchestrates the signal detection pipeline:
1. Assert dependencies exist (lift_scores, positions tables)
2. Detect convergence of Q5 traders on same market+direction
3. Upsert detected signals to database
4. Print summary with counts

Usage:
    polymarket --niche esports detect [--db-path PATH]
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
from rich.console import Console

from src.polymarket_analytics.cli import cli
from src.polymarket_analytics.db.schema import init_database
from src.polymarket_analytics.detection.convergence import detect_convergence
from src.polymarket_analytics.detection.writer import upsert_signals_batch

console = Console()


async def _detect_async(ctx: Any, db_path: str) -> None:
    """Async detect implementation."""
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
    console.print("[bold]=== Detecting Consensus Signals ===[/bold]\n")

    # Dependency assertions (fail loudly)
    # Assert lift_scores table exists
    if not db["lift_scores"].exists():
        raise click.ClickException(
            "lift_scores table does not exist. Run score command first."
        )

    # Assert positions table exists
    if not db["positions"].exists():
        raise click.ClickException(
            "positions table does not exist. Run build-positions command first."
        )

    # Note: Q5 trader check removed — detect_convergence() calls _assert_dependencies()
    # which validates Q5 traders with MAX(computed_at) filter for latest scoring run.
    # Duplicate check here was misleading (passed on stale Q5, then real guard fired).

    # Run detection pipeline with Rich progress
    start_time = datetime.now(timezone.utc)

    with console.status("[bold green]Detecting convergence...", spinner="dots"):
        convergence_df = detect_convergence(db, niche)

    if convergence_df.empty:
        console.print("[yellow]No consensus signals found.[/yellow]")
        return

    with console.status("[bold green]Upserting signals...", spinner="dots"):
        upserted = upsert_signals_batch(db, convergence_df, niche)

    end_time = datetime.now(timezone.utc)
    elapsed = (end_time - start_time).total_seconds()

    # Print summary
    console.print(f"\n[green]Detection complete ({elapsed:.1f}s)[/green]")
    console.print(f"  [bold]Signals detected/updated:[/bold] {upserted}")


@cli.command()
@click.option(
    "--db-path",
    default="data/analytics.db",
    help="Path to SQLite database (default: data/analytics.db)",
)
@click.pass_context
def detect(ctx: Any, db_path: str) -> None:
    """Detect consensus signals for the specified niche.

    This command:
    1. Asserts dependencies exist (lift_scores, positions tables, Q5 traders)
    2. Detects convergence where >= 2 Q5 traders converge on same market+direction
    3. Upserts detected signals to signals table with first_seen/last_updated tracking
    4. Prints summary with signals detected/updated count

    Args:
        ctx: Click context with niche and config
        db_path: Path to SQLite database
    """
    asyncio.run(_detect_async(ctx, db_path))
