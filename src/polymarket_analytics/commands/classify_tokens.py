"""classify-tokens CLI command for building token catalog from Gamma API market data.

This command fetches markets from the Gamma API and populates the token_catalog
table with condition_id mappings for all markets in the niche.
"""

import asyncio
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
    db_path_obj = Path(db_path)
    if not db_path_obj.parent.exists():
        db_path_obj.parent.mkdir(parents=True, exist_ok=True)
    db = init_database(db_path_obj)

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
        # Each binary market has two real token IDs (YES and NO tokens)
        token_catalog_records = []

        for market in markets:
            condition_id = market.get("conditionId", "")
            question = market.get("question", "")
            outcomes = market.get("outcomes", "YES,NO")
            category = market.get("category", niche_slug)
            tags = market.get("tags", [])

            # Gamma API returns token IDs in clobTokenIds field (not outcomeTokens)
            clob_token_ids = market.get("clobTokenIds", [])
            # Handle case where it's a JSON string
            if isinstance(clob_token_ids, str):
                try:
                    clob_token_ids = json.loads(clob_token_ids)
                except (json.JSONDecodeError, ValueError):
                    clob_token_ids = []

            # Determine market_type from outcomes
            outcome_list = outcomes.split(",") if outcomes else []
            market_type = "binary" if outcome_list == ["YES", "NO"] else "categorical"

            # Build node_path from category/tags
            node_path = f"{niche_slug}/{category}"

            # Use real token IDs from clobTokenIds, fallback only if empty
            if clob_token_ids and len(clob_token_ids) >= 2:
                token_ids = clob_token_ids[:2]  # Take first 2 for binary markets
            else:
                # Fallback: generate synthetic IDs (will never match real trades)
                # Log warning so user knows catalog won't work with real data
                click.echo(
                    f"Warning: No clobTokenIds for {condition_id[:16]}... - "
                    "using synthetic token IDs (won't match real trades)",
                    err=True,
                )
                token_ids = [
                    f"{condition_id}:0",
                    f"{condition_id}:1",
                ]

            # Insert one row per token (YES and NO)
            for idx, token_id in enumerate(token_ids):
                outcome_name = (
                    outcome_list[idx] if idx < len(outcome_list) else f"OUTCOME_{idx}"
                )
                token_catalog_records.append(
                    {
                        "token_id": token_id,
                        "condition_id": condition_id,
                        "question": question,
                        "niche_slug": niche_slug,
                        "node_path": node_path,
                        "market_type": market_type,
                        "created_at": datetime.now().isoformat(),
                    }
                )

        # Insert into token_catalog using raw SQL to preserve created_at on re-runs
        for record in token_catalog_records:
            db.execute(
                """
                INSERT INTO token_catalog (token_id, condition_id, question, niche_slug, node_path, market_type, created_at)
                VALUES (:token_id, :condition_id, :question, :niche_slug, :node_path, :market_type, :created_at)
                ON CONFLICT(token_id) DO UPDATE SET
                    condition_id = excluded.condition_id,
                    question = excluded.question,
                    niche_slug = excluded.niche_slug,
                    node_path = excluded.node_path,
                    market_type = excluded.market_type
                """,
                record,
            )

        click.echo(
            f"Built token catalog with {len(token_catalog_records)} entries for niche '{niche_slug}'"
        )

    finally:
        await client.close()
