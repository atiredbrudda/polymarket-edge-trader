"""ingest-events CLI command for fetching and storing Polymarket markets.

This command fetches markets from the Gamma API for a configured niche
and populates the gamma_events and markets tables.
"""

import asyncio
import hashlib
import json
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
def ingest_events(ctx, db_path: str):
    """Ingest markets from Gamma API for the specified niche.

    Fetches all markets for the niche's tag_id and populates:
    - gamma_events: Raw market data from Gamma API
    - markets: Market metadata for downstream processing
    """
    asyncio.run(_ingest_events_async(ctx, db_path))


async def _ingest_events_async(ctx, db_path: str):
    """Async implementation of ingest-events command."""
    config = ctx.obj["config"]
    niche_slug = config.slug

    click.echo(f"Ingesting events for niche: {niche_slug}")

    # Assert dependency: config.tag_id exists (RESL-01)
    if not hasattr(config, "tag_id") or config.tag_id is None:
        raise click.ClickException(
            f"No tag_id found in config for niche '{niche_slug}'. "
            "Ensure the niche YAML has a 'tag_id' field (integer)."
        )

    # Initialize database
    db = init_database(Path(db_path))

    # Create Gamma API client
    client = GammaAPIClient()

    try:
        # Get tag_id from config (already int from Phase 1 fix)
        tag_id = config.tag_id
        click.echo(f"Fetching markets for tag_id: {tag_id}")

        # Fetch markets from Gamma API
        markets = await client.fetch_markets(tag_id)

        # Assert data fetched (RESL-02)
        if not markets:
            raise click.ClickException(
                f"No markets found for tag_id={tag_id}. "
                "Check tag_id is correct and niche has active markets."
            )

        click.echo(f"Fetched {len(markets)} markets from Gamma API")

        # Prepare records for gamma_events
        gamma_events_records = []
        markets_records = []

        for market in markets:
            condition_id = market.get("conditionId", "")
            question = market.get("question", "")
            outcomes = market.get("outcomes", "YES,NO")
            end_date = market.get("endDate")
            tags = market.get("tags", [])
            active = market.get("active", False)
            closed = market.get("closed", False)
            category = market.get("category", niche_slug)

            # Extract outcome for binary markets (YES from "YES,NO")
            outcome_list = outcomes.split(",") if outcomes else []
            outcome = (
                outcome_list[0]
                if len(outcome_list) == 2 and outcome_list[0] == "YES"
                else None
            )

            # Generate hash ID for gamma_events
            event_id = hashlib.sha256(condition_id.encode()).hexdigest()

            # gamma_events record
            gamma_events_records.append(
                {
                    "id": event_id,
                    "condition_id": condition_id,
                    "question": question,
                    "outcome": outcome,
                    "end_date": end_date,
                    "tags": json.dumps(tags),
                    "active": active,
                    "niche_slug": niche_slug,
                    "created_at": datetime.now().isoformat(),
                }
            )

            # markets record
            markets_records.append(
                {
                    "condition_id": condition_id,
                    "question": question,
                    "outcome": outcome,
                    "resolved": closed,
                    "niche_slug": niche_slug,
                    "created_at": datetime.now().isoformat(),
                    "end_date": end_date,
                    "category": category,
                    "active": active,
                    "tokens": json.dumps([]),
                }
            )

        # Insert into gamma_events
        db["gamma_events"].upsert_all(
            gamma_events_records,
            pk="id",
            alter=True,
        )

        # Insert into markets
        db["markets"].upsert_all(
            markets_records,
            pk="condition_id",
            alter=True,
        )

        click.echo(f"Ingested {len(markets)} markets for niche '{niche_slug}'")
        click.echo(f"  - gamma_events: {len(gamma_events_records)} records")
        click.echo(f"  - markets: {len(markets_records)} records")

    finally:
        await client.close()
