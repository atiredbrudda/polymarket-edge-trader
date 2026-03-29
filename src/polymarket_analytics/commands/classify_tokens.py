"""classify-tokens CLI command for building token catalog from Gamma API market data.

This command fetches markets from the Gamma API and populates the token_catalog
table with condition_id mappings for all markets in the niche.
"""

import asyncio
from datetime import datetime
from pathlib import Path

import click

from src.polymarket_analytics.cli import cli
from src.polymarket_analytics.db.schema import init_database
from src.polymarket_analytics.api.gamma import GammaAPIClient


@cli.command()
@click.option(
    "--db-path",
    default="data/analytics.db",
    help="Path to SQLite database (default: data/analytics.db)",
)
@click.pass_context
def classify_tokens(ctx, db_path: str):
    """Build token catalog for the specified niche.

    Fetches markets from Gamma API and populates token_catalog with
    condition_id mappings for all markets in the niche.
    """
    asyncio.run(_classify_tokens_async(ctx, db_path))


async def _classify_tokens_async(ctx, db_path: str):
    """Async implementation of classify-tokens command."""
    config = ctx.obj["config"]
    niche_slug = config.slug

    click.echo(f"Building token catalog for niche: {niche_slug}")

    # Initialize database
    db = init_database(Path(db_path))

    # Assert dependency: markets table exists (RESL-01)
    if not db.table_exists("markets"):
        raise click.ClickException(
            "No 'markets' table found. Run 'ingest-events' command first to create it."
        )

    # Create Gamma API client
    client = GammaAPIClient()

    try:
        # Get tag_id from config
        tag_id = config.tag_id
        click.echo(f"Fetching markets from Gamma API for tag_id: {tag_id}")

        # Fetch markets from Gamma API (fresh data, not from existing markets table)
        markets = await client.fetch_markets(tag_id)

        # Assert data fetched (RESL-02)
        if not markets:
            raise click.ClickException(
                f"No markets found for tag_id={tag_id}. "
                "Check tag_id is correct and niche has active markets."
            )

        click.echo(f"Fetched {len(markets)} markets from Gamma API")

        # Build token_catalog entries from markets
        token_catalog_records = []

        for market in markets:
            condition_id = market.get("conditionId", "")
            question = market.get("question", "")
            outcomes = market.get("outcomes", "YES,NO")
            category = market.get("category", niche_slug)
            tags = market.get("tags", [])

            # Determine market_type from outcomes
            outcome_list = outcomes.split(",") if outcomes else []
            market_type = "binary" if outcome_list == ["YES", "NO"] else "categorical"

            # Build node_path from category/tags
            # Example: "esports/cs2/match_winner" or "esports/{category}"
            node_path = f"{niche_slug}/{category}"

            # token_catalog record
            token_catalog_records.append(
                {
                    "token_id": condition_id,  # Same as condition_id for binary markets
                    "condition_id": condition_id,
                    "question": question,
                    "niche_slug": niche_slug,
                    "node_path": node_path,
                    "market_type": market_type,
                    "created_at": datetime.now().isoformat(),
                }
            )

        # Insert into token_catalog
        db["token_catalog"].upsert_all(
            token_catalog_records,
            pk="token_id",
            alter=True,
        )

        click.echo(
            f"Built token catalog with {len(token_catalog_records)} entries for niche '{niche_slug}'"
        )

    finally:
        await client.close()
