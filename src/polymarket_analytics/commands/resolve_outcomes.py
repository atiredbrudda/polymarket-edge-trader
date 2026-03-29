"""resolve-outcomes CLI command for updating market outcomes from gamma_events.

This command updates the markets.outcome field to YES/NO for resolved markets
by reading from the gamma_events table.
"""

import asyncio
from pathlib import Path
import click

from polymarket_analytics.cli import cli
from polymarket_analytics.db.schema import init_database


@cli.command()
@click.option(
    "--db-path",
    default="data/analytics.db",
    help="Path to SQLite database (default: data/analytics.db)",
)
@click.pass_context
def resolve_outcomes(ctx, db_path: str):
    """Resolve market outcomes from gamma_events for the specified niche.

    Updates markets.outcome to YES/NO from gamma_events for resolved
    (inactive) markets.
    """
    asyncio.run(_resolve_outcomes_async(ctx, db_path))


async def _resolve_outcomes_async(ctx, db_path: str):
    """Async implementation of resolve-outcomes command."""
    config = ctx.obj["config"]
    niche_slug = config.slug

    click.echo(f"Resolving outcomes for niche: {niche_slug}")

    # Initialize database (creates schema if not exists)
    db_path_obj = Path(db_path)
    if not db_path_obj.parent.exists():
        db_path_obj.parent.mkdir(parents=True, exist_ok=True)
    db = init_database(db_path_obj)

    # Assert gamma_events has data (RESL-01)
    # Check if gamma_events table has any rows
    gamma_events_count = db["gamma_events"].count
    if gamma_events_count == 0:
        raise click.ClickException(
            "gamma_events table is empty. "
            "Run 'ingest-events' first to populate gamma_events."
        )

    # Update markets.outcome from gamma_events for resolved markets.
    # JOIN-style UPDATE avoids correlated subquery (single pass vs one lookup per row).
    result = db.execute(
        """
        UPDATE markets
        SET outcome = ge.outcome,
            resolved = 1
        FROM gamma_events ge
        WHERE markets.condition_id = ge.condition_id
          AND ge.niche_slug = :niche_slug
          AND ge.outcome IS NOT NULL
        """,
        {"niche_slug": niche_slug},
    )

    db.conn.commit()

    # Get count of updated rows
    updated_count = result.rowcount

    click.echo(f"Resolved {updated_count} markets for niche '{niche_slug}'")
