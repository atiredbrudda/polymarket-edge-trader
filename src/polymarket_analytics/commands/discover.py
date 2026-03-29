"""Discover command for populating traders and market_entities tables.

This command extracts entities from market questions and discovers traders
from Polymarket Data API trades.

Usage:
    polymarket --niche esports discover [--use-llm] [--db-path PATH]
"""

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import click

from src.polymarket_analytics.cli import cli
from src.polymarket_analytics.api.data import DataAPIClient
from src.polymarket_analytics.db.schema import init_database
from src.polymarket_analytics.extraction.llm import LLMFallback
from src.polymarket_analytics.extraction.patterns import EntityPatternMatcher


def generate_entity_id(condition_id: str, entities: Dict[str, Any]) -> str:
    """Generate stable entity ID from condition_id and extracted entities.

    Args:
        condition_id: Market condition ID
        entities: Extracted entity dict with game, team_a, team_b, etc.

    Returns:
        SHA256 hash (first 16 chars) as stable entity ID
    """
    # Create deterministic string from entities
    entity_str = json.dumps(entities, sort_keys=True)
    combined = f"{condition_id}:{entity_str}"
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


@cli.command()
@click.option(
    "--db-path",
    default="data/analytics.db",
    help="Path to SQLite database (default: data/analytics.db)",
)
@click.option(
    "--use-llm",
    is_flag=True,
    default=True,
    help="Enable LLM fallback for entity extraction (default: enabled)",
)
@click.pass_context
def discover(ctx, db_path: str, use_llm: bool) -> None:
    """Discover traders and extract entities for niche markets.

    This command:
    1. Fetches markets for niche from database
    2. Extracts entities using pattern matcher (LLM fallback if enabled)
    3. Populates market_entities table
    4. Fetches trades from Data API
    5. Populates traders table with unique traders

    Args:
        ctx: Click context with niche and config
        db_path: Path to SQLite database
        use_llm: Whether to use LLM fallback for entity extraction
    """
    niche = ctx.obj.get("niche", "esports")
    config = ctx.obj.get("config")

    if not config:
        raise click.ClickException(f"No config found for niche: {niche}")

    # Initialize database
    db_path_obj = Path(db_path)
    if not db_path_obj.parent.exists():
        db_path_obj.parent.mkdir(parents=True, exist_ok=True)

    db = init_database(db_path_obj)

    # Assert markets table exists (RESL-01)
    if not db["markets"].exists():
        raise click.ClickException(
            "markets table does not exist. Run ingest-events command first."
        )

    # Fetch markets for niche from database (not API)
    markets_query = """
        SELECT condition_id, question FROM markets WHERE niche_slug = :niche_slug
    """
    markets = list(db.query(markets_query, {"niche_slug": niche}))

    # Assert markets exist (RESL-02)
    if not markets:
        raise click.ClickException(
            f"No markets found for niche='{niche}' in database. "
            f"Run ingest-events command first."
        )

    # Initialize extractors
    pattern_matcher = EntityPatternMatcher()
    llm_fallback: Optional[LLMFallback] = None

    if use_llm:
        try:
            llm_fallback = LLMFallback()
        except ValueError as e:
            # LLM enabled but API key not set - warn and continue without LLM
            click.echo(f"Warning: {e}. Disabling LLM fallback.", err=True)
            llm_fallback = None

    # Process entity extraction
    entity_count = 0
    llm_count = 0
    pattern_count = 0

    for market in markets:
        condition_id = market["condition_id"]
        question = market["question"]

        # Try pattern matcher first
        entities = pattern_matcher.extract(question)

        # Check if critical fields missing
        needs_llm = (
            use_llm
            and llm_fallback is not None
            and (entities["game"] is None or entities["team_a"] is None)
        )

        if needs_llm:
            try:
                entities = llm_fallback.extract(question)
                llm_count += 1
            except Exception as e:
                click.echo(
                    f"Warning: LLM extraction failed for {condition_id[:8]}...: {e}",
                    err=True,
                )

        if entities["game"] is not None or entities["team_a"] is not None:
            pattern_count += 1

        # Generate stable entity ID
        entity_id = generate_entity_id(condition_id, entities)

        # Upsert into market_entities
        db["market_entities"].upsert(
            {
                "id": entity_id,
                "condition_id": condition_id,
                "game": entities.get("game"),
                "team_a": entities.get("team_a"),
                "team_b": entities.get("team_b"),
                "tournament": entities.get("tournament"),
                "market_type": entities.get("market_type"),
            },
            pk="id",
            replace=True,
        )
        entity_count += 1

    # Fetch traders from Data API
    condition_ids = [m["condition_id"] for m in markets]

    async def fetch_traders():
        """Fetch trades and extract unique traders."""
        client = DataAPIClient()
        try:
            trades = await client.fetch_trades(condition_ids, limit=1000)

            # Extract unique traders from trades
            traders: Dict[str, Dict[str, Any]] = {}
            now = datetime.now(timezone.utc).isoformat()

            for trade in trades:
                address = trade.get("proxyWallet")
                if not address:
                    continue

                timestamp = trade.get("timestamp")
                if timestamp:
                    # Convert Unix timestamp to ISO format
                    try:
                        ts_iso = datetime.fromtimestamp(
                            timestamp, tz=timezone.utc
                        ).isoformat()
                    except (ValueError, OSError):
                        ts_iso = now
                else:
                    ts_iso = now

                if address not in traders:
                    traders[address] = {
                        "address": address,
                        "first_seen": ts_iso,
                        "last_seen": ts_iso,
                        "backfill_complete": False,
                        "created_at": now,
                    }
                else:
                    # Update first_seen and last_seen
                    if ts_iso < traders[address]["first_seen"]:
                        traders[address]["first_seen"] = ts_iso
                    if ts_iso > traders[address]["last_seen"]:
                        traders[address]["last_seen"] = ts_iso

            # Upsert traders
            for trader_data in traders.values():
                db["traders"].upsert(trader_data, pk="address", replace=True)

            return len(traders)
        finally:
            await client.close()

    trader_count = asyncio.run(fetch_traders())

    # Print summary
    click.echo(
        f"Discovered {trader_count} traders, extracted entities for {entity_count} markets"
    )
    click.echo(f"  Pattern matcher success: {pattern_count}")
    click.echo(f"  LLM fallback used: {llm_count}")
