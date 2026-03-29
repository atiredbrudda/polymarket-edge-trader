"""Score command for computing trader lift_scores.

This command orchestrates the full scoring pipeline:
1. Extract resolved positions within scoring window
2. Calculate CLV, ROI, Sharpe metrics
3. Compute z-score normalized scores
4. Assign quintiles
5. Upsert results to lift_scores table

Usage:
    polymarket --niche esports score [--db-path PATH]
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
from rich.console import Console

from polymarket_analytics.cli import cli
from polymarket_analytics.db.schema import init_database
from polymarket_analytics.scoring.extraction import extract_resolved_positions
from polymarket_analytics.scoring.metrics import calculate_all_metrics
from polymarket_analytics.scoring.normalization import compute_normalized_scores
from polymarket_analytics.scoring.writer import write_lift_scores

console = Console()


async def _score_async(ctx: Any, db_path: str) -> None:
    """Async score implementation."""
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
    console.print("[bold]=== Scoring Traders ===[/bold]\n")

    # Dependency assertions (fail loudly)
    # Assert positions table exists
    if not db["positions"].exists():
        raise click.ClickException(
            "positions table does not exist. Run build-positions command first."
        )

    # Assert markets table exists
    if not db["markets"].exists():
        raise click.ClickException(
            "markets table does not exist. Check schema initialization."
        )

    # Assert markets with outcome IS NOT NULL exist
    markets_with_outcomes = db.execute(
        "SELECT COUNT(*) as cnt FROM markets WHERE outcome IS NOT NULL"
    ).fetchone()[0]

    if markets_with_outcomes == 0:
        raise click.ClickException(
            "No markets with outcomes found. Run resolve-outcomes command first."
        )

    # Assert resolved positions exist in window
    window_days = config.get("scoring_window_days", 30)
    resolved_in_window = db.execute(
        """
        SELECT COUNT(*) as cnt FROM positions p
        JOIN markets m ON m.condition_id = p.market_id
        WHERE p.resolved = 1
          AND m.niche_slug = :niche
          AND p.last_trade_timestamp >= datetime('now', '-' || :window_days || ' days')
        """,
        {"niche": niche, "window_days": window_days},
    ).fetchone()[0]

    if resolved_in_window == 0:
        raise click.ClickException(
            f"No resolved positions found within {window_days}-day window for niche '{niche}'. "
            "Ensure backfill, build-positions, and resolve-positions have run."
        )

    # Load config
    min_positions = config.get("min_positions", 30)

    # Calculate window_end as current timestamp
    window_end = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Run pipeline with Rich progress
    start_time = datetime.now(timezone.utc)

    with console.status("[bold green]Extracting resolved positions...", spinner="dots"):
        positions_df = extract_resolved_positions(db, niche, window_days)

    if positions_df.empty:
        console.print(
            "[yellow]No resolved positions found in window. Exiting early.[/yellow]"
        )
        return

    with console.status(
        "[bold green]Calculating metrics (CLV, ROI, Sharpe)...", spinner="dots"
    ):
        metrics_df = calculate_all_metrics(positions_df)

    with console.status(
        "[bold green]Computing normalized scores and quintiles...", spinner="dots"
    ):
        scores_df = compute_normalized_scores(metrics_df)

    # Filter to min_positions AFTER z-scores computed (per 05-RESEARCH.md Pitfall 5)
    traders_with_enough_positions = scores_df[
        scores_df["position_count"] >= min_positions
    ].copy()

    if traders_with_enough_positions.empty:
        console.print(
            f"[yellow]No traders with >= {min_positions} resolved positions. "
            "Lower min_positions in niche config or collect more data.[/yellow]"
        )
        return

    with console.status(
        "[bold green]Writing lift_scores to database...", spinner="dots"
    ):
        upserted = write_lift_scores(
            db, traders_with_enough_positions, niche, window_days, window_end
        )

    end_time = datetime.now(timezone.utc)
    elapsed = (end_time - start_time).total_seconds()

    # Print summary
    console.print(f"\n[green]Scoring complete ({elapsed:.1f}s)[/green]")
    console.print(
        f"  [bold]Traders scored:[/bold] {len(traders_with_enough_positions):,}"
    )
    console.print(f"  [bold]Min positions threshold:[/bold] {min_positions}")
    console.print(f"  [bold]Scoring window:[/bold] {window_days} days")
    console.print(f"  [bold]Window end:[/bold] {window_end[:10]}")
    console.print(f"  [bold]Records upserted:[/bold] {upserted:,}")


@cli.command()
@click.option(
    "--db-path",
    default="data/analytics.db",
    help="Path to SQLite database (default: data/analytics.db)",
)
@click.pass_context
def score(ctx: Any, db_path: str) -> None:
    """Compute trader lift_scores for the specified niche.

    This command:
    1. Asserts dependencies exist (positions, markets tables, outcomes, resolved positions)
    2. Extracts resolved positions within the scoring window
    3. Calculates CLV, ROI, and Sharpe ratio per trader
    4. Computes z-score normalized scores
    5. Assigns quintiles (Q5 = top 20% = smart money)
    6. Filters to traders with >= min_positions AFTER z-scores computed
    7. Upserts results to lift_scores table

    Args:
        ctx: Click context with niche and config
        db_path: Path to SQLite database
    """
    asyncio.run(_score_async(ctx, db_path))
