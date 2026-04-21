"""ingest-events CLI command for fetching and storing Polymarket markets.

This command fetches markets from the Gamma API for a configured niche
and populates the gamma_events and markets tables.
"""

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
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
        # Fetch markets from Gamma API with page progress
        def on_page(page: int, total: int) -> None:
            console.print(
                f"  Fetching... page {page} ({total} markets so far)", end="\r"
            )

        if full or existing_count == 0:
            click.echo(f"Full fetch mode: fetching all markets for tag_id: {tag_id}")
            # Gamma API defaults to active-only when closed is omitted,
            # so full mode must fetch active + closed separately.
            active_markets = await client.fetch_markets(
                tag_id, closed=False, on_page=on_page
            )
            console.print()
            click.echo(f"  Active: {len(active_markets):,} markets. Fetching closed...")
            # On re-runs (existing_count > 0), limit closed sweep to last 7 days —
            # cuts ~115k pages to ~52. No end_date_max so voided markets with future
            # endDate are still captured. On first run, fetch all historical closed
            # markets so the DB is fully populated from the start.
            closed_since = (
                (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
                if existing_count > 0
                else None
            )
            closed_markets = await client.fetch_markets(
                tag_id, closed=True, end_date_min=closed_since, on_page=on_page
            )
            console.print()
            click.echo(f"  Closed: {len(closed_markets):,} markets.")
            # Merge, dedup by conditionId (active wins if both)
            seen = {m["conditionId"] for m in active_markets}
            markets = active_markets + [
                m for m in closed_markets if m["conditionId"] not in seen
            ]
        else:
            click.echo(
                f"Incremental mode: fetching active markets for tag_id: {tag_id}"
            )
            click.echo(
                f"  (existing markets: {existing_count}, use --full to force full fetch)"
            )
            markets = await client.fetch_markets(
                tag_id, closed=False, on_page=on_page
            )
            console.print()

        # Assert data fetched (RESL-02)
        if not markets:
            raise click.ClickException(
                f"No markets found for tag_id={tag_id}. "
                "Check tag_id is correct and niche has active markets."
            )

        click.echo(f"Fetched {len(markets)} markets from Gamma API")

        # Prefix allowlist filter — reject markets whose event_slug prefix
        # is not in the config's event_slug_prefixes list.
        allowed_prefixes = set(getattr(config, "event_slug_prefixes", []) or [])
        if allowed_prefixes:
            accepted = []
            rejected_prefixes: dict[str, int] = {}
            for m in markets:
                events = m.get("events", [])
                slug = events[0].get("slug", "") if events else ""
                prefix = slug.split("-")[0] if slug else ""
                if prefix in allowed_prefixes:
                    accepted.append(m)
                else:
                    rejected_prefixes[prefix] = rejected_prefixes.get(prefix, 0) + 1
            rejected_count = len(markets) - len(accepted)
            markets = accepted
            if rejected_count:
                top = sorted(rejected_prefixes.items(), key=lambda x: -x[1])
                summary = ", ".join(f"{p} ({n})" for p, n in top[:10])
                click.echo(
                    f"  Skipped {rejected_count} market(s) with "
                    f"unknown prefix: {summary}"
                )

        # Prepare records for gamma_events
        gamma_events_records = []
        markets_records = []
        props_skipped_by_label: dict[str, int] = {}

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
            # Normalize to YES/NO: index 0 in outcomes/outcomePrices = YES,
            # index 1 = NO.  Gamma API encodes resolution in outcomePrices:
            # ["1","0"] = first outcome won = YES.
            outcome = None
            if closed or not active:
                # Parse the outcomes array once (needed by all paths).
                if isinstance(outcomes, str) and outcomes.startswith("["):
                    outcome_list = json.loads(outcomes)
                elif isinstance(outcomes, str):
                    outcome_list = [o.strip() for o in outcomes.split(",")]
                else:
                    outcome_list = list(outcomes) if outcomes else []
                outcome_list_upper = [o.strip().upper() for o in outcome_list]

                result = market.get("result")
                winner = market.get("winner")
                outcome_prices_raw = market.get("outcomePrices")

                # Path 1: result/winner field — map name to index then YES/NO
                raw_winner = (result or winner or "").strip().upper()
                if raw_winner and raw_winner in outcome_list_upper:
                    idx = outcome_list_upper.index(raw_winner)
                    outcome = "YES" if idx == 0 else "NO"
                elif raw_winner in ("YES", "NO"):
                    outcome = raw_winner

                # Path 2: outcomePrices — price >= 0.99 means that side won
                if outcome is None and outcome_prices_raw:
                    try:
                        prices = (
                            json.loads(outcome_prices_raw)
                            if isinstance(outcome_prices_raw, str)
                            else outcome_prices_raw
                        )
                        for i, price in enumerate(prices):
                            if float(price) >= 0.99:
                                outcome = "YES" if i == 0 else "NO"
                                break
                    except (ValueError, TypeError, json.JSONDecodeError):
                        pass

            # Prop-market filter — skip kill counts, first blood, etc. Wiki: prop-market-prune.
            from polymarket_analytics.filters.prop_filter import matched_prop_label
            _prop_label = matched_prop_label(question)
            if _prop_label is not None:
                props_skipped_by_label[_prop_label] = props_skipped_by_label.get(_prop_label, 0) + 1
                continue

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

            # Extract clobTokenIds from Gamma API response
            clob_token_ids = market.get("clobTokenIds", [])
            if isinstance(clob_token_ids, str):
                try:
                    clob_token_ids = json.loads(clob_token_ids)
                except (json.JSONDecodeError, ValueError):
                    clob_token_ids = []
            clob_token_ids_json = json.dumps(clob_token_ids) if clob_token_ids else None

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
                    "clob_token_ids": clob_token_ids_json,
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
                INSERT INTO markets (condition_id, question, outcome, resolved, niche_slug, created_at, end_date, category, active, tokens, event_slug, event_title, clob_token_ids)
                VALUES (:condition_id, :question, :outcome, :resolved, :niche_slug, :created_at, :end_date, :category, :active, :tokens, :event_slug, :event_title, :clob_token_ids)
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
                    event_title = excluded.event_title,
                    clob_token_ids = excluded.clob_token_ids
                """,
                markets_records,
            )

        click.echo(f"Ingested {len(markets)} markets for niche '{niche_slug}'")
        click.echo(f"  - gamma_events: {len(gamma_events_records)} records")
        click.echo(f"  - markets: {len(markets_records)} records")
        if props_skipped_by_label:
            total_skipped = sum(props_skipped_by_label.values())
            top = sorted(props_skipped_by_label.items(), key=lambda x: -x[1])
            summary = ", ".join(f"{label} ({n})" for label, n in top[:8])
            click.echo(f"  - props_skipped: {total_skipped} ({summary})")

    finally:
        await client.close()
