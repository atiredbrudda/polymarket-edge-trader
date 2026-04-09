"""Discover command — fetches live markets from Gamma API (closed=false).

Adapted from v1 discover pattern:
  1. Fetch active niche markets from Gamma API (closed=false)
  2. Upsert those markets into the DB
  3. For each market (per-market loop):
     a. Skip if already has trades, unless closing within 30 min
     b. Fetch trades from Data API → extract trader addresses
     c. Run entity extraction (pattern → LLM fallback)
     d. Upsert traders (backfill_complete=False) and market_entities
  4. Print summary

Usage:
    polymarket --niche esports discover [--closing-within HOURS] [--use-llm] [--db-path PATH]
"""

import asyncio
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional

import click
import httpx
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from polymarket_analytics.api.gamma import GammaAPIClient
from polymarket_analytics.cli import cli
from polymarket_analytics.db.schema import init_database
from polymarket_analytics.extraction.llm import LLMFallback
from polymarket_analytics.extraction.patterns import EntityPatternMatcher
from polymarket_analytics.extraction.slug_parser import parse_event_slug

console = Console()

DATA_API_URL = "https://data-api.polymarket.com/trades"


def _entity_id(condition_id: str, entities: Dict[str, Any]) -> str:
    entity_str = json.dumps(entities, sort_keys=True)
    return hashlib.sha256(f"{condition_id}:{entity_str}".encode()).hexdigest()[:16]


def _fetch_market_trades(condition_id: str, limit: int = 500) -> List[dict]:
    """Fetch trades for a single market from Data API (synchronous)."""
    response = httpx.get(
        DATA_API_URL,
        params={"market": condition_id, "limit": limit},
        timeout=30.0,
    )
    response.raise_for_status()
    trades = response.json()
    # Filter to this market only (API may return cross-market trades)
    return [
        t for t in trades if t.get("conditionId", "").lower() == condition_id.lower()
    ]


@cli.command()
@click.option(
    "--db-path",
    default="data/analytics.db",
    help="Path to SQLite database (default: data/analytics.db)",
)
@click.option(
    "--closing-within",
    "closing_within",
    default=None,
    type=int,
    help="Only process markets closing within N hours (optional)",
)
@click.option(
    "--use-llm",
    is_flag=True,
    default=True,
    help="Enable LLM fallback for entity extraction (default: enabled)",
)
@click.pass_context
def discover(ctx, db_path: str, closing_within: Optional[int], use_llm: bool) -> None:
    """Discover traders and extract entities for live niche markets."""
    niche = ctx.obj.get("niche", "esports")
    config = ctx.obj.get("config")

    if not config:
        raise click.ClickException(f"No config found for niche: {niche}")

    if not hasattr(config, "tag_id") or config.tag_id is None:
        raise click.ClickException(
            f"No tag_id in config for niche '{niche}'. Check niches/{niche}.yaml."
        )

    db_path_obj = Path(db_path)
    db_path_obj.parent.mkdir(parents=True, exist_ok=True)
    db = init_database(db_path_obj)

    start_time = time.time()
    console.print(f"[bold]=== Discovering for {niche} ===[/bold]")

    # -------------------------------------------------------------------------
    # Step 1: Fetch live markets from Gamma API (closed=false)
    # -------------------------------------------------------------------------
    console.print("[bold]Step 1/4[/bold] Fetching live markets from Gamma API...")

    gamma_markets: List[dict] = []
    _page_ref = [0]  # mutable for closure

    def on_page(page: int, total: int) -> None:
        _page_ref[0] = page
        console.print(f"  page {page} — {total:,} markets so far", end="\r")

    async def _fetch():
        client = GammaAPIClient()
        try:
            return await client.fetch_markets(
                config.tag_id, closed=False, on_page=on_page
            )
        finally:
            await client.close()

    gamma_markets = asyncio.run(_fetch())
    console.print()  # clear the \r line

    if not gamma_markets:
        raise click.ClickException(
            f"No open markets from Gamma API for tag_id={config.tag_id}."
        )

    console.print(
        f"  [green]✓[/green] {len(gamma_markets):,} live markets "
        f"({_page_ref[0]} pages, tag_id={config.tag_id})"
    )

    # Apply --closing-within filter
    now_utc = datetime.now(timezone.utc)
    refresh_cutoff = now_utc + timedelta(minutes=30)

    if closing_within is not None:
        cutoff = now_utc + timedelta(hours=closing_within)
        before = len(gamma_markets)
        gamma_markets = [
            m
            for m in gamma_markets
            if m.get("endDate")
            and now_utc
            <= datetime.fromisoformat(m["endDate"].replace("Z", "+00:00"))
            <= cutoff
        ]
        dropped = before - len(gamma_markets)
        console.print(
            f"  [dim]--closing-within {closing_within}h:[/dim] "
            f"{len(gamma_markets):,} kept, {dropped:,} dropped"
        )
        if not gamma_markets:
            console.print("[yellow]No markets match the filter. Exiting.[/yellow]")
            return

    # -------------------------------------------------------------------------
    # Step 2: Upsert live markets into DB
    # -------------------------------------------------------------------------
    console.print(
        f"[bold]Step 2/4[/bold] Saving {len(gamma_markets):,} markets to DB..."
    )

    now_iso = now_utc.isoformat()
    markets_records = []
    for m in gamma_markets:
        if not m.get("conditionId"):
            continue
        events = m.get("events", [])
        event_slug = None
        if events and len(events) > 0:
            event_slug = events[0].get("slug")
        markets_records.append(
            {
                "condition_id": m["conditionId"],
                "question": m.get("question", ""),
                "outcome": None,
                "resolved": False,
                "niche_slug": niche,
                "created_at": now_iso,
                "end_date": m.get("endDate"),
                "category": niche,
                "active": True,
                "tokens": json.dumps(m.get("tokens", [])),
                "event_slug": event_slug,
            }
        )

    with db.conn:
        db.conn.executemany(
            """
            INSERT INTO markets (condition_id, question, outcome, resolved, niche_slug,
                                 created_at, end_date, category, active, tokens, event_slug)
            VALUES (:condition_id, :question, :outcome, :resolved, :niche_slug,
                    :created_at, :end_date, :category, :active, :tokens, :event_slug)
            ON CONFLICT(condition_id) DO UPDATE SET
                question = excluded.question,
                end_date = excluded.end_date,
                active   = excluded.active,
                tokens   = excluded.tokens,
                event_slug = excluded.event_slug
            """,
            markets_records,
        )
    console.print(f"  [green]✓[/green] {len(markets_records):,} markets upserted")

    # -------------------------------------------------------------------------
    # Step 3: Check cache and load existing entity rows
    # -------------------------------------------------------------------------
    console.print("[bold]Step 3/4[/bold] Checking cache...")

    cid_list = [r["condition_id"] for r in markets_records]

    cached_cids: set = set()
    if cid_list:
        placeholders = ",".join("?" * len(cid_list))
        cached_cids = set(
            row[0]
            for row in db.execute(
                f"SELECT DISTINCT market_id FROM trades WHERE market_id IN ({placeholders})",
                cid_list,
            ).fetchall()
        )

    existing_entity_cids = set(
        row[0]
        for row in db.execute(
            "SELECT condition_id FROM market_entities WHERE game IS NOT NULL"
        ).fetchall()
    )

    # Pre-load token catalog for active markets (avoids per-trade DB lookup)
    catalog_by_token: Dict[str, str] = {}  # token_id → condition_id
    if cid_list:
        placeholders2 = ",".join("?" * len(cid_list))
        for row in db.execute(
            f"SELECT token_id, condition_id FROM token_catalog WHERE condition_id IN ({placeholders2})",
            cid_list,
        ).fetchall():
            catalog_by_token[row[0]] = row[1]

    to_process = len(cid_list) - len(cached_cids)
    console.print(
        f"  [green]✓[/green] {len(cached_cids):,} markets cached (have trades)  "
        f"→  {to_process:,} new to process"
    )
    console.print(
        f"  [green]✓[/green] {len(existing_entity_cids):,} markets already have entities extracted"
    )

    # Build cid → event_slug map from the markets we just upserted
    cid_to_event_slug: Dict[str, Optional[str]] = {
        r["condition_id"]: r["event_slug"] for r in markets_records
    }

    # Pre-seed event_slug → entities from DB (siblings extracted in prior runs)
    event_slug_entities: Dict[str, Dict[str, Any]] = {}
    rows = db.execute("""
        SELECT m.event_slug, me.game, me.team_a, me.team_b, me.tournament, me.market_type
        FROM market_entities me
        JOIN markets m ON me.condition_id = m.condition_id
        WHERE m.event_slug IS NOT NULL AND me.game IS NOT NULL
    """).fetchall()
    for row in rows:
        slug = row[0]
        if slug and slug not in event_slug_entities:
            event_slug_entities[slug] = {
                "game": row[1],
                "team_a": row[2],
                "team_b": row[3],
                "tournament": row[4],
                "market_type": row[5],
            }

    # Setup entity extraction
    pattern_matcher = EntityPatternMatcher()
    llm_fallback: Optional[LLMFallback] = None
    if use_llm:
        try:
            llm_fallback = LLMFallback()
            console.print("  [green]✓[/green] LLM fallback ready")
        except ValueError as e:
            console.print(f"  [yellow]⚠ LLM unavailable: {e}[/yellow]")

    # -------------------------------------------------------------------------
    # Step 4: Per-market loop — fetch trades + extract entities
    # -------------------------------------------------------------------------
    console.print(f"[bold]Step 4/4[/bold] Processing {to_process:,} new markets...")

    traders: Dict[str, Dict[str, Any]] = {}
    trade_records: List[Dict[str, Any]] = []
    entity_records: List[Dict[str, Any]] = []
    llm_count = 0
    pattern_count = 0
    event_slug_count = 0
    slug_parse_count = 0
    new_markets_count = 0
    skipped_count = 0
    error_count = 0

    def _desc() -> str:
        return (
            f"[cyan]Markets[/cyan]  "
            f"[dim]traders: {len(traders):,} | "
            f"trades: {len(trade_records):,} | "
            f"entities: {len(entity_records):,} | "
            f"skipped: {skipped_count:,} | "
            f"errors: {error_count:,}[/dim]"
        )

    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task(_desc(), total=len(gamma_markets))

        for m in gamma_markets:
            cid = m.get("conditionId", "")
            question = m.get("question", "")
            end_date_str = m.get("endDate")

            if not cid:
                progress.advance(task)
                continue

            # --- Cache skip ---
            if cid in cached_cids:
                closing_soon = False
                if end_date_str:
                    try:
                        end_dt = datetime.fromisoformat(
                            end_date_str.replace("Z", "+00:00")
                        )
                        closing_soon = end_dt <= refresh_cutoff
                    except ValueError:
                        pass

                if not closing_soon:
                    skipped_count += 1
                    progress.update(task, description=_desc())
                    progress.advance(task)
                    continue

            new_markets_count += 1

            # --- Fetch trades ---
            progress.update(
                task,
                description=f"[cyan]↓ trades[/cyan]  [dim]{question[:60]}[/dim]",
            )
            try:
                trades = _fetch_market_trades(cid)
            except Exception as e:
                error_count += 1
                console.print(f"  [red]✗ trade fetch {cid[:10]}...: {e}[/red]")
                progress.update(task, description=_desc())
                progress.advance(task)
                continue

            # --- Extract trader addresses and build trade records ---
            for trade in trades:
                address = trade.get("proxyWallet")
                if not address:
                    continue
                raw_ts = trade.get("timestamp")
                try:
                    ts_iso = (
                        datetime.fromtimestamp(raw_ts, tz=timezone.utc).isoformat()
                        if raw_ts
                        else now_iso
                    )
                except (ValueError, OSError):
                    ts_iso = now_iso

                if address not in traders:
                    traders[address] = {
                        "address": address,
                        "first_seen": ts_iso,
                        "last_seen": ts_iso,
                        "backfill_complete": False,
                        "created_at": now_iso,
                    }
                else:
                    if ts_iso < traders[address]["first_seen"]:
                        traders[address]["first_seen"] = ts_iso
                    if ts_iso > traders[address]["last_seen"]:
                        traders[address]["last_seen"] = ts_iso

                # Build trade record (same format as backfill)
                raw_token_id = trade.get("asset") or trade.get("asset_id")
                tx_hash = trade.get("transactionHash", "")
                trade_id = tx_hash or hashlib.sha256(
                    f"{address}:{raw_token_id}:{trade.get('side', '')}:{trade.get('price', '')}:{trade.get('size', '')}:{raw_ts}".encode()
                ).hexdigest()[:32]

                # Resolve market_id via token catalog; fall back to conditionId
                if raw_token_id and raw_token_id in catalog_by_token:
                    resolved_market_id = catalog_by_token[raw_token_id]
                    token_id_val = raw_token_id
                else:
                    resolved_market_id = cid  # conditionId is already known
                    token_id_val = None  # not in catalog yet; skip FK

                try:
                    price = Decimal(str(trade.get("price", "0")))
                    if price > 1:
                        price = Decimal("1") / price
                except InvalidOperation:
                    price = Decimal("0")

                try:
                    size = Decimal(str(trade.get("size", "0")))
                except InvalidOperation:
                    size = Decimal("0")

                trade_records.append(
                    {
                        "trade_id": trade_id,
                        "token_id": token_id_val,
                        "timestamp": ts_iso,
                        "side": "BUY" if trade.get("side") == "BUY" else "SELL",
                        "price": str(price),
                        "size": str(size),
                        "market_id": resolved_market_id,
                        "trader_address": address,
                    }
                )

            # --- Entity extraction ---
            if cid not in existing_entity_cids:
                progress.update(
                    task,
                    description=f"[cyan]⚙ entities[/cyan]  [dim]{question[:55]}[/dim]",
                )
                entities = pattern_matcher.extract(question)
                pattern_incomplete = (
                    entities.get("game") is None or entities.get("team_a") is None
                )

                # event_slug fallback: inherit entities from a sibling market
                if pattern_incomplete:
                    slug = cid_to_event_slug.get(cid)
                    if slug and slug in event_slug_entities:
                        entities = event_slug_entities[slug]
                        event_slug_count += 1
                        pattern_incomplete = False

                # slug parse fallback: extract game+teams from slug structure
                if pattern_incomplete:
                    slug = cid_to_event_slug.get(cid)
                    if slug:
                        parsed = parse_event_slug(slug)
                        if parsed.get("game"):
                            entities = parsed
                            slug_parse_count += 1
                            pattern_incomplete = False
                            if slug not in event_slug_entities:
                                event_slug_entities[slug] = entities

                # LLM fallback: only if pattern, event_slug, and slug parse all failed
                if (
                    pattern_incomplete
                    and use_llm
                    and llm_fallback is not None
                ):
                    progress.update(
                        task,
                        description=f"[cyan]⚙ LLM[/cyan]  [dim]{question[:58]}[/dim]",
                    )
                    try:
                        entities = llm_fallback.extract(question)
                        llm_count += 1
                    except Exception as e:
                        console.print(f"  [red]✗ LLM {cid[:10]}...: {e}[/red]")

                if (
                    entities.get("game") is not None
                    or entities.get("team_a") is not None
                ):
                    pattern_count += 1
                    # Cache for siblings processed later in this run
                    slug = cid_to_event_slug.get(cid)
                    if slug and slug not in event_slug_entities:
                        event_slug_entities[slug] = entities

                entity_records.append(
                    {
                        "id": _entity_id(cid, entities),
                        "condition_id": cid,
                        "game": entities.get("game"),
                        "team_a": entities.get("team_a"),
                        "team_b": entities.get("team_b"),
                        "tournament": entities.get("tournament"),
                        "market_type": entities.get("market_type"),
                    }
                )

            progress.update(task, description=_desc())
            progress.advance(task)

    # -------------------------------------------------------------------------
    # Step 5: Batch write to DB
    # -------------------------------------------------------------------------
    if trade_records:
        with console.status(
            f"[bold green]Writing {len(trade_records):,} trades to DB...",
            spinner="dots",
        ):
            with db.conn:
                db.conn.executemany(
                    """
                    INSERT INTO trades (trade_id, token_id, timestamp, side, price, size, market_id, trader_address)
                    VALUES (:trade_id, :token_id, :timestamp, :side, :price, :size, :market_id, :trader_address)
                    ON CONFLICT(trade_id) DO NOTHING
                    """,
                    trade_records,
                )
        console.print(f"  [green]✓[/green] {len(trade_records):,} trades written")

    if traders:
        with console.status(
            f"[bold green]Writing {len(traders):,} traders to DB...", spinner="dots"
        ):
            with db.conn:
                db.conn.executemany(
                    """
                    INSERT INTO traders (address, first_seen, last_seen, backfill_complete, created_at)
                    VALUES (:address, :first_seen, :last_seen, :backfill_complete, :created_at)
                    ON CONFLICT(address) DO UPDATE SET
                        first_seen = MIN(excluded.first_seen, traders.first_seen),
                        last_seen  = MAX(excluded.last_seen,  traders.last_seen)
                    """,
                    list(traders.values()),
                )
        console.print(f"  [green]✓[/green] {len(traders):,} traders written")

    if entity_records:
        with console.status(
            f"[bold green]Writing {len(entity_records):,} entities to DB...",
            spinner="dots",
        ):
            with db.conn:
                db.conn.executemany(
                    """
                    INSERT INTO market_entities (id, condition_id, game, team_a, team_b, tournament, market_type)
                    VALUES (:id, :condition_id, :game, :team_a, :team_b, :tournament, :market_type)
                    ON CONFLICT(condition_id) DO UPDATE SET
                        id          = excluded.id,
                        game        = excluded.game,
                        team_a      = excluded.team_a,
                        team_b      = excluded.team_b,
                        tournament  = excluded.tournament,
                        market_type = excluded.market_type
                    """,
                    entity_records,
                )
        console.print(f"  [green]✓[/green] {len(entity_records):,} entities written")

    elapsed = time.time() - start_time
    console.print(
        f"\n[bold green]Discover complete[/bold green] ({elapsed:.1f}s)\n"
        f"  Live markets fetched:  {len(gamma_markets):,}\n"
        f"  New markets processed: {new_markets_count:,}\n"
        f"  Cached (skipped):      {skipped_count:,}\n"
        f"  Errors:                {error_count:,}\n"
        f"  Trades stored:         {len(trade_records):,}\n"
        f"  Entities extracted:    {len(entity_records):,} "
        f"(pattern: {pattern_count - event_slug_count - slug_parse_count:,}, event_slug: {event_slug_count:,}, slug_parse: {slug_parse_count:,}, LLM: {llm_count:,})\n"
        f"  Traders discovered:    {len(traders):,}"
    )
