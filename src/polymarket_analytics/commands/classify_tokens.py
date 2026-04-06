"""classify-tokens CLI command for building token catalog from database market data.

This command reads markets from the database (populated by ingest-events) and populates
the token_catalog table with condition_id and clobTokenIds mappings.
"""

import json
from datetime import datetime
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
def classify_tokens(ctx, db_path: str):
    """Build token catalog for the specified niche from DB.

    Reads markets from database (populated by ingest-events command) and
    populates token_catalog with condition_id and clobTokenIds mappings.
    """
    _classify_tokens_from_db(ctx, db_path)


def _classify_tokens_from_db(ctx, db_path: str):
    """Build token catalog from database markets."""
    config = ctx.obj["config"]
    niche_slug = config.slug

    click.echo(f"Building token catalog for niche: {niche_slug}")

    # Initialize database
    db_path_obj = Path(db_path)
    if not db_path_obj.parent.exists():
        db_path_obj.parent.mkdir(parents=True, exist_ok=True)
    db = init_database(db_path_obj)

    # Assert dependency: markets table exists (RESL-01)
    if "markets" not in db.table_names():
        raise click.ClickException(
            "No 'markets' table found. Run 'ingest-events' command first to create it."
        )

    # Fetch markets from database (already populated by ingest-events)
    click.echo(f"Fetching markets from database for niche: {niche_slug}")

    markets_rows = db.execute(
        """
        SELECT condition_id, question, outcome, category, clob_token_ids
        FROM markets
        WHERE niche_slug = ?
        """,
        [niche_slug],
    ).fetchall()

    # Assert data exists (RESL-02)
    if not markets_rows:
        raise click.ClickException(
            f"No markets found for niche '{niche_slug}'. "
            "Run 'ingest-events' command first to populate markets table."
        )

    click.echo(f"Found {len(markets_rows)} markets in database")

    # Build token_catalog entries from DB rows
    token_catalog_records = []

    for row in markets_rows:
        condition_id = row[0]
        question = row[1]
        outcomes = row[2] or "YES,NO"
        category = row[3] or niche_slug
        clob_token_ids_raw = row[4]

        # Parse clob_token_ids from JSON string
        if clob_token_ids_raw:
            try:
                clob_token_ids = json.loads(clob_token_ids_raw)
            except (json.JSONDecodeError, ValueError):
                clob_token_ids = []
        else:
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

    # Filter to condition_ids that exist in markets (FK constraint)
    known_cids = set(
        row[0] for row in db.execute("SELECT condition_id FROM markets").fetchall()
    )
    filtered_records = [
        r for r in token_catalog_records if r["condition_id"] in known_cids
    ]
    skipped = len(token_catalog_records) - len(filtered_records)

    with db.conn:
        db.conn.executemany(
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
            filtered_records,
        )

    click.echo(
        f"Built token catalog with {len(filtered_records)} entries for niche '{niche_slug}'"
        + (f" ({skipped} skipped — not yet in markets table)" if skipped else "")
    )
