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
from rich.console import Console

from polymarket_analytics.cli import cli
from polymarket_analytics.db.schema import init_database
from polymarket_analytics.api.gamma import GammaAPIClient

console = Console()


@cli.command()
@click.option(
    "--db-path",
    default="data/analytics.db",
    help="Path to SQLite database (default: data/analytics.db)",
)
@click.option(
    "--full",
    is_flag=True,
    default=False,
    help="Force full fetch regardless of existing data (use after failures or for resolution sweep)",
)
@click.pass_context
def ingest_events(ctx, db_path: str, full: bool):
    """Ingest markets from Gamma API for the specified niche.

    Fetches all markets for the niche's tag_id and populates:
    - gamma_events: Raw market data from Gamma API
    - markets: Market metadata for downstream processing

    By default, uses incremental mode on re-runs (fetches only active markets).
    Use --full to force a complete fetch of all markets.
    """
    asyncio.run(_ingest_events_async(ctx, db_path, full))


async def _ingest_events_async(ctx, db_path: str, full: bool):
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
    db_path_obj = Path(db_path)
    if not db_path_obj.parent.exists():
        db_path_obj.parent.mkdir(parents=True, exist_ok=True)
    db = init_database(db_path_obj)

    # Create Gamma API client
    client = GammaAPIClient()

    try:
        # Get tag_id from config (already int from Phase 1 fix)
        tag_id = config.tag_id

        # Check if this is first run or re-run
        existing_count = db.execute(
            "SELECT COUNT(*) FROM markets WHERE niche_slug = ?", [niche_slug]
        ).fetchone()[0]

        # Incremental mode: first run fetches all, re-runs fetch only active
        if full or existing_count == 0:
            click.echo(f"Full fetch mode: fetching all markets for tag_id: {tag_id}")
            markets_to_fetch_closed = None  # Fetch all
        else:
            click.echo(
                f"Incremental mode: fetching active markets for tag_id: {tag_id}"
            )
            click.echo(
                f"  (existing markets: {existing_count}, use --full to force full fetch)"
            )
            markets_to_fetch_closed = False  # Fetch only active

        # Fetch markets from Gamma API with page progress
        def on_page(page: int, total: int) -> None:
            console.print(
                f"  Fetching... page {page} ({total} markets so far)", end="\r"
            )

        markets = await client.fetch_markets(
            tag_id, closed=markets_to_fetch_closed, on_page=on_page
        )
        console.print()  # newline after \r progress

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

            # Determine outcome for resolved markets.
            # Gamma API encodes resolution in outcomePrices: ["1","0"] = first outcome won.
            # Falls back to result/winner fields if present.
            outcome = None
            if closed or not active:
                result = market.get("result")
                winner = market.get("winner")
                outcome_prices_raw = market.get("outcomePrices")

                if result and isinstance(result, str):
                    outcome = result.upper()
                elif winner and isinstance(winner, str):
                    outcome = winner.upper()
                elif outcome_prices_raw:
                    try:
                        prices = (
                            json.loads(outcome_prices_raw)
                            if isinstance(outcome_prices_raw, str)
                            else outcome_prices_raw
                        )
                        if isinstance(outcomes, str) and outcomes.startswith("["):
                            outcome_list = json.loads(outcomes)
                        elif isinstance(outcomes, str):
                            outcome_list = [o.strip() for o in outcomes.split(",")]
                        else:
                            outcome_list = outcomes
                        for i, price in enumerate(prices):
                            if float(price) >= 0.99 and i < len(outcome_list):
                                outcome = outcome_list[i].strip().upper()
                                break
                    except (ValueError, TypeError, json.JSONDecodeError):
                        pass

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
            events = market.get("events", [])
            event_slug = None
            event_title = None
            if events and len(events) > 0:
                event_slug = events[0].get("slug")
                event_title = events[0].get("title")

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
                    "event_slug": event_slug,
                    "event_title": event_title,
                }
            )

        with db.conn:
            db.conn.executemany(
                """
                INSERT INTO gamma_events (id, condition_id, question, outcome, end_date, tags, active, niche_slug, created_at)
                VALUES (:id, :condition_id, :question, :outcome, :end_date, :tags, :active, :niche_slug, :created_at)
                ON CONFLICT(id) DO UPDATE SET
                    condition_id = excluded.condition_id,
                    question = excluded.question,
                    outcome = excluded.outcome,
                    end_date = excluded.end_date,
                    tags = excluded.tags,
                    active = excluded.active,
                    niche_slug = excluded.niche_slug
                """,
                gamma_events_records,
            )
            db.conn.executemany(
                """
                INSERT INTO markets (condition_id, question, outcome, resolved, niche_slug, created_at, end_date, category, active, tokens, event_slug, event_title)
                VALUES (:condition_id, :question, :outcome, :resolved, :niche_slug, :created_at, :end_date, :category, :active, :tokens, :event_slug, :event_title)
                ON CONFLICT(condition_id) DO UPDATE SET
                    question = excluded.question,
                    outcome = excluded.outcome,
                    resolved = excluded.resolved,
                    niche_slug = excluded.niche_slug,
                    end_date = excluded.end_date,
                    category = excluded.category,
                    active = excluded.active,
                    tokens = excluded.tokens,
                    event_slug = excluded.event_slug,
                    event_title = excluded.event_title
                """,
                markets_records,
            )

        click.echo(f"Ingested {len(markets)} markets for niche '{niche_slug}'")
        click.echo(f"  - gamma_events: {len(gamma_events_records)} records")
        click.echo(f"  - markets: {len(markets_records)} records")

    finally:
        await client.close()
