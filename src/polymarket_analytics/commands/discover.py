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
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TaskProgressColumn, TimeElapsedColumn, TextColumn

from polymarket_analytics.cli import cli
from polymarket_analytics.api.data import DataAPIClient
from polymarket_analytics.db.schema import init_database
from polymarket_analytics.extraction.llm import LLMFallback
from polymarket_analytics.extraction.patterns import EntityPatternMatcher

console = Console()


def generate_entity_id(condition_id: str, entities: Dict[str, Any]) -> str:
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
    """Discover traders and extract entities for niche markets."""
    niche = ctx.obj.get("niche", "esports")
    config = ctx.obj.get("config")

    if not config:
        raise click.ClickException(f"No config found for niche: {niche}")

    db_path_obj = Path(db_path)
    if not db_path_obj.parent.exists():
        db_path_obj.parent.mkdir(parents=True, exist_ok=True)

    db = init_database(db_path_obj)

    if not db["markets"].exists():
        raise click.ClickException(
            "markets table does not exist. Run ingest-events command first."
        )

    markets = list(db.query(
        "SELECT condition_id, question FROM markets WHERE niche_slug = :niche_slug",
        {"niche_slug": niche},
    ))

    if not markets:
        raise click.ClickException(
            f"No markets found for niche='{niche}' in database. "
            f"Run ingest-events command first."
        )

    console.print(f"[bold]=== Discovering for {niche} ===[/bold]")
    console.print(f"Found {len(markets):,} markets\n")

    pattern_matcher = EntityPatternMatcher()
    llm_fallback: Optional[LLMFallback] = None

    if use_llm:
        try:
            llm_fallback = LLMFallback()
        except ValueError as e:
            console.print(f"[yellow]Warning: {e}. Disabling LLM fallback.[/yellow]")
            llm_fallback = None

    # --- Entity extraction with progress bar ---
    entity_records = []
    llm_count = 0
    pattern_count = 0

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("[cyan]Extracting entities", total=len(markets))

        for market in markets:
            condition_id = market["condition_id"]
            question = market["question"]

            entities = pattern_matcher.extract(question)

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
                    console.print(
                        f"  [red]LLM failed for {condition_id[:8]}...: {e}[/red]"
                    )

            if entities["game"] is not None or entities["team_a"] is not None:
                pattern_count += 1

            entity_id = generate_entity_id(condition_id, entities)
            entity_records.append({
                "id": entity_id,
                "condition_id": condition_id,
                "game": entities.get("game"),
                "team_a": entities.get("team_a"),
                "team_b": entities.get("team_b"),
                "tournament": entities.get("tournament"),
                "market_type": entities.get("market_type"),
            })

            progress.advance(task)

    # Batch upsert market_entities
    with db.conn:
        db.conn.executemany(
            """
            INSERT INTO market_entities (id, condition_id, game, team_a, team_b, tournament, market_type)
            VALUES (:id, :condition_id, :game, :team_a, :team_b, :tournament, :market_type)
            ON CONFLICT(condition_id) DO UPDATE SET
                id = excluded.id,
                game = excluded.game,
                team_a = excluded.team_a,
                team_b = excluded.team_b,
                tournament = excluded.tournament,
                market_type = excluded.market_type
            """,
            entity_records,
        )

    console.print(f"\n[green]Entities:[/green] {len(entity_records):,} written "
                  f"(pattern: {pattern_count:,}, LLM: {llm_count:,})\n")

    # --- Trader discovery ---
    condition_ids = [m["condition_id"] for m in markets]

    async def fetch_traders():
        client = DataAPIClient()
        try:
            console.print("[cyan]Fetching traders from Data API...[/cyan]")
            trades = await client.fetch_trades(condition_ids, limit=1000)

            traders: Dict[str, Dict[str, Any]] = {}
            now = datetime.now(timezone.utc).isoformat()

            for trade in trades:
                address = trade.get("proxyWallet")
                if not address:
                    continue

                timestamp = trade.get("timestamp")
                if timestamp:
                    try:
                        ts_iso = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
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
                    if ts_iso < traders[address]["first_seen"]:
                        traders[address]["first_seen"] = ts_iso
                    if ts_iso > traders[address]["last_seen"]:
                        traders[address]["last_seen"] = ts_iso

            # Batch upsert traders
            if traders:
                with db.conn:
                    db.conn.executemany(
                        """
                        INSERT INTO traders (address, first_seen, last_seen, backfill_complete, created_at)
                        VALUES (:address, :first_seen, :last_seen, :backfill_complete, :created_at)
                        ON CONFLICT(address) DO UPDATE SET
                            first_seen = MIN(excluded.first_seen, traders.first_seen),
                            last_seen = MAX(excluded.last_seen, traders.last_seen)
                        """,
                        list(traders.values()),
                    )

            return len(traders)
        finally:
            await client.close()

    trader_count = asyncio.run(fetch_traders())

    console.print(f"[green]Traders:[/green] {trader_count:,} discovered")
