"""build-token-catalog CLI command stub."""

import click
from pathlib import Path

from src.polymarket_analytics.cli import cli
from src.polymarket_analytics.db.schema import init_database
from src.polymarket_analytics.token_catalog.builder import TokenCatalogBuilder


@cli.command()
@click.option(
    "--db-path",
    default="data/analytics.db",
    help="Path to SQLite database (default: data/analytics.db)",
)
@click.pass_context
def build_token_catalog(ctx, db_path: str):
    """Build token catalog for the specified niche.

    Creates token_id to condition_id mappings for all markets in the niche.
    """
    config = ctx.obj["config"]
    niche_slug = config.slug

    click.echo(f"Building token catalog for niche: {niche_slug}")

    # Initialize database
    db = init_database(Path(db_path))

    # Create TokenCatalogBuilder instance
    builder = TokenCatalogBuilder(db)

    # Build catalog (stub implementation - returns 0 entries for now)
    count = builder.build(niche=niche_slug)

    click.echo(f"Built token catalog with {count} entries")
