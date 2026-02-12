"""Click command group and subcommands for Polymarket CLI.

Commands:
- markets: List active markets with optional category filter
- trader: Display trader profile by address
- signals: Show expert consensus signals
- leaderboard: Display game leaderboard rankings
- sweep: Run signal detection sweep
- poll: Run automated polling loop

All commands delegate formatting to src.cli.formatters for clean separation.
"""

import csv
import json
import sys
from decimal import Decimal
from pathlib import Path

import click
from loguru import logger
from rich.console import Console
from sqlalchemy import create_engine, select

from src.cli.formatters import (
    format_markets_table,
    format_trader_profile,
    format_signals_table,
    format_leaderboard_table,
    format_sweep_summary,
    format_research_table,
    format_batch_summary,
)
from src.db.models import Base, Trader, TaxonomyNode, Market, MarketClassification
from src.db.session import get_session, get_session_factory
from src.config.settings import get_settings
from src.api.client import PolymarketClient
from src.pipeline.filters import CategoryFilter
from src.alerts.telegram import TelegramAlerter


def _get_dependencies(settings=None):
    """Create all pipeline dependencies from settings.

    Creates database engine, session factory, API client, category filter,
    and optional Telegram alerter. Auto-creates database tables if needed.

    Args:
        settings: Optional Settings instance (defaults to get_settings())

    Returns:
        Tuple of (session_factory, client, category_filter, alerter)

    Example:
        session_factory, client, category_filter, alerter = _get_dependencies()
        with get_session(session_factory) as session:
            # use session
    """
    settings = settings or get_settings()

    # Create engine and auto-create tables if needed
    engine = create_engine(settings.database_url)
    Base.metadata.create_all(engine)
    session_factory = get_session_factory(engine)

    # Create API client
    client = PolymarketClient(settings=settings)

    # Create category filter
    category_filter = CategoryFilter(settings.detail_categories)

    # Optional Telegram alerter (returns None if not configured)
    alerter = None
    try:
        alerter = TelegramAlerter.from_settings(settings)
    except ValueError as e:
        logger.warning(f"Telegram configuration invalid: {e}")

    return session_factory, client, category_filter, alerter


def find_trader_by_prefix(session, partial_address: str) -> str | None:
    """Find trader by partial address match.

    Normalizes input (lowercase, strip, add 0x prefix) and queries
    trader_address using LIKE query: address LIKE '{input}%'

    Args:
        session: SQLAlchemy session
        partial_address: Partial wallet address

    Returns:
        Full address if exactly 1 match found, None otherwise (prints error)

    Example:
        >>> find_trader_by_prefix(session, "0xAbc")
        '0xAbCdEf1234567890...'
    """
    # Normalize input
    normalized = partial_address.strip().lower()
    if not normalized.startswith("0x"):
        normalized = f"0x{normalized}"

    # Query traders
    query = select(Trader.address).where(Trader.address.like(f"{normalized}%"))
    result = session.execute(query)
    matches = result.scalars().all()

    if len(matches) == 0:
        print(f"Error: No trader found matching '{partial_address}'")
        return None
    elif len(matches) == 1:
        return matches[0]
    else:
        print(
            f"Error: Ambiguous address '{partial_address}' matches {len(matches)} traders. Provide more characters."
        )
        return None


def _setup_cli_logging():
    """Setup CLI session logging to file for debugging.

    Creates logs directory if needed and configures loguru to write:
    - All CLI output to logs/cli_session.log (rotating, persistent across sessions)
    - Includes timestamps, command names, and full output
    """
    from src.config.settings import get_settings
    settings = get_settings()

    # Create logs directory if it doesn't exist
    log_path = Path(settings.cli_log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Configure loguru for CLI session logging
    # Remove default handler to avoid duplicate stderr output
    logger.remove()

    # Add file handler with rotation (10 MB max, keep 3 files)
    logger.add(
        settings.cli_log_file,
        rotation="10 MB",
        retention=3,
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        enqueue=True,  # Thread-safe
    )

    # Add stderr handler for WARNING and above (don't clutter terminal with DEBUG/INFO)
    logger.add(
        sys.stderr,
        level="WARNING",
        format="<red>{level}</red>: {message}",
    )

    logger.info("=" * 80)
    logger.info("CLI SESSION START")
    logger.info("=" * 80)


@click.group()
@click.pass_context
def cli(ctx):
    """Polymarket Smart Money Tracker CLI.

    Track expert trader consensus and market signals in eSports prediction markets.
    """
    # Only setup logging if not --help
    if ctx.invoked_subcommand is not None or '--help' not in sys.argv:
        _setup_cli_logging()
        logger.info(f"Command invoked: {' '.join(sys.argv)}")


@cli.command()
@click.option("--category", "-c", default=None, help="Filter by category (e.g., eSports)")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def markets(category, verbose):
    """List active markets with optional category filter.

    Example:
        polymarket markets
        polymarket markets --category eSports
    """
    logger.info(f"MARKETS command started (category={category}, verbose={verbose})")

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()

    with console.status("[bold green]Fetching markets...", spinner="dots"):
        # Get dependencies
        session_factory, _, _, _ = _get_dependencies()

        # Import queries here to avoid circular imports
        from src.pipeline.queries import get_active_markets

        with get_session(session_factory) as session:
            # Get active markets
            markets_orm = get_active_markets(session, category=category)

            # Join with MarketClassification to get taxonomy slugs
            market_data = []
            for market in markets_orm:
                query = (
                    select(TaxonomyNode.slug)
                    .join(MarketClassification, MarketClassification.taxonomy_node_id == TaxonomyNode.id)
                    .where(MarketClassification.market_id == market.condition_id)
                )
                result = session.execute(query)
                slug = result.scalar()

                market_data.append({
                    "question": market.question,
                    "slug": slug,
                    "active": market.active,
                })

    logger.info(f"Found {len(market_data)} active markets")
    for market in market_data:
        logger.debug(f"  - {market['slug']}: {market['question'][:80]}")

    # Format and display
    table = format_markets_table(market_data)
    console.print(table)
    logger.info("MARKETS command completed")


@cli.command()
@click.argument("address")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def trader(address, verbose):
    """Display trader profile by address.

    ADDRESS can be full address or prefix (e.g., 0xAbc will match 0xAbCdEf...).

    Example:
        polymarket trader 0xTrader123456
        polymarket trader 0xAbc
    """
    logger.info(f"TRADER command started (address={address}, verbose={verbose})")

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()

    with console.status("[bold green]Fetching trader profile...", spinner="dots"):
        # Get dependencies
        session_factory, _, _, _ = _get_dependencies()

        with get_session(session_factory) as session:
            # Resolve partial address
            full_address = find_trader_by_prefix(session, address)
            if not full_address:
                logger.warning(f"Trader not found: {address}")
                return
            logger.info(f"Resolved trader address: {full_address}")

            # Import queries here to avoid circular imports
            from src.pipeline.queries import (
                get_trader_summary,
                get_positions_by_timeframe,
                get_trader_score_history,
            )

            # Get trader data
            summaries = get_trader_summary(session, full_address)
            positions = get_positions_by_timeframe(session, full_address, "all")
            scores = get_trader_score_history(session, full_address, limit=10)

            # Convert ORM objects to dicts for formatter
            summaries_data = [
                {
                    "category": s.category,
                    "volume": s.total_volume,
                    "trade_count": s.trade_count,
                }
                for s in summaries
            ]

            positions_data = []
            for p in positions:
                # Get market question
                market = session.query(Market).filter(Market.condition_id == p.market_id).first()
                market_question = market.question if market else p.market_id
                positions_data.append({
                    "market_question": market_question,
                    "direction": p.direction,
                    "size": p.size,
                    "avg_entry_price": p.avg_entry_price,
                })

            scores_data = [
                {
                    "game": s.game_slug,
                    "score": s.raw_score,
                    "percentile": s.percentile_rank or Decimal("0"),
                    "specialization": "specialist" if s.is_specialist else "generalist",
                }
                for s in scores
            ]

    logger.info(f"Trader profile loaded: {len(summaries_data)} categories, {len(positions_data)} positions, {len(scores_data)} scores")

    # Format and display
    profile = format_trader_profile(full_address, summaries_data, positions_data, scores_data)
    console.print(profile)
    logger.info("TRADER command completed")


@cli.command()
@click.option("--window", "-w", default=24, help="Time window in hours (1, 6, 24)")
@click.option("--min-confidence", "-c", default=None, type=float, help="Minimum confidence score")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def signals(window, min_confidence, verbose):
    """Show expert consensus signals.

    Example:
        polymarket signals
        polymarket signals --window 6
        polymarket signals --min-confidence 80
    """
    logger.info(f"SIGNALS command started (window={window}h, min_confidence={min_confidence}, verbose={verbose})")

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()

    with console.status("[bold green]Fetching signals...", spinner="dots"):
        # Get dependencies
        session_factory, _, _, _ = _get_dependencies()

        with get_session(session_factory) as session:
            # Import signal queries here
            from src.signals.pipeline import get_ranked_signals

            # Convert min_confidence to Decimal if provided
            min_conf_decimal = Decimal(str(min_confidence)) if min_confidence else None

            # Get ranked signals
            signals_results = get_ranked_signals(
                session, window_hours=window, min_confidence=min_conf_decimal, limit=50
            )

            # Convert SignalResult objects to dicts for formatter
            signals_data = []
            for signal in signals_results:
                # Get market question
                market = session.query(Market).filter(Market.condition_id == signal.market_id).first()
                market_question = market.question if market else signal.market_id

                signals_data.append({
                    "market_question": market_question,
                    "direction": signal.direction,
                    "confidence": signal.confidence_score,
                    "expert_count": signal.expert_count,
                    "first_mover_address": signal.first_mover_address,
                })

    logger.info(f"Found {len(signals_data)} signals")
    for signal in signals_data[:5]:  # Log first 5
        logger.debug(f"  - {signal['market_question'][:60]}: {signal['direction']} (conf={signal['confidence']}, experts={signal['expert_count']})")

    # Format and display
    table = format_signals_table(signals_data)
    console.print(table)
    logger.info("SIGNALS command completed")


@cli.command()
@click.argument("game_slug")
@click.option("--top-n", "-n", default=20, help="Number of entries to display")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def leaderboard(game_slug, top_n, verbose):
    """Display game leaderboard rankings.

    GAME_SLUG is the game identifier (e.g., esports.cs2, esports.lol).

    Example:
        polymarket leaderboard esports.cs2
        polymarket leaderboard esports.lol --top-n 10
    """
    logger.info(f"LEADERBOARD command started (game_slug={game_slug}, top_n={top_n}, verbose={verbose})")

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()

    with console.status("[bold green]Fetching leaderboard...", spinner="dots"):
        # Get dependencies
        session_factory, _, _, _ = _get_dependencies()

        with get_session(session_factory) as session:
            # Validate game slug exists
            query = select(TaxonomyNode.slug).where(
                TaxonomyNode.slug.like("esports.%"), TaxonomyNode.node_type == "game"
            )
            result = session.execute(query)
            valid_games = result.scalars().all()

            if game_slug not in valid_games:
                logger.error(f"Invalid game slug: {game_slug}. Valid games: {valid_games}")
                console.print(f"[bold red]Error: Game '{game_slug}' not found.[/bold red]")
                console.print("\n[bold]Available games:[/bold]")
                for game in sorted(valid_games):
                    console.print(f"  - {game}")
                return

            # Import queries here
            from src.pipeline.queries import get_game_leaderboard

            # Get leaderboard
            leaderboard_entries = get_game_leaderboard(session, game_slug, top_n=top_n)

            # Convert to dicts for formatter
            entries_data = [
                {
                    "rank": idx + 1,
                    "trader_address": entry.trader_address,
                    "score": entry.raw_score,
                    "win_rate": entry.win_rate or Decimal("0"),
                }
                for idx, entry in enumerate(leaderboard_entries)
            ]

    logger.info(f"Leaderboard loaded: {len(entries_data)} entries for {game_slug}")

    # Format and display
    table = format_leaderboard_table(entries_data, game_slug)
    console.print(table)
    logger.info("LEADERBOARD command completed")


@cli.command()
@click.option("--window", "-w", default=24, help="Time window in hours for expert activity")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def sweep(window, verbose):
    """Run signal detection sweep.

    Refreshes all signals for markets with expert activity.

    Example:
        polymarket sweep
        polymarket sweep --window 6
    """
    logger.info(f"SWEEP command started (window={window}h, verbose={verbose})")

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()

    with console.status("[bold green]Running sweep...", spinner="dots"):
        import time
        start_time = time.time()

        # Get dependencies
        session_factory, client, category_filter, alerter = _get_dependencies()

        # Import pipeline here
        from src.cli.scheduler import run_sweep

        # Run full sweep (skip_alerts=True since this is manual command)
        stats = run_sweep(session_factory, client, category_filter, alerter, skip_alerts=True)

        processing_time = time.time() - start_time

    logger.info(f"Sweep completed: {stats['markets_ingested']} markets, {stats['signals_detected']} signals, {stats['alerts_sent']} alerts in {processing_time:.2f}s")

    # Format and display
    summary = format_sweep_summary({
        "processing_time": processing_time,
        "markets_count": stats["markets_ingested"],
        "signals_count": stats["signals_detected"],
        "alerts_sent": stats["alerts_sent"],
    })
    console.print(summary)
    logger.info("SWEEP command completed")


@cli.command()
@click.option("--interval", "-i", default=None, type=int, help="Polling interval in minutes")
@click.option("--no-alerts", is_flag=True, help="Skip alert delivery")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def poll(interval, no_alerts, verbose):
    """Run automated polling loop.

    Executes full sweep (ingest → score → detect → alert) at regular intervals.
    Press Ctrl+C for graceful shutdown.

    Example:
        polymarket poll
        polymarket poll --interval 30
        polymarket poll --no-alerts
    """
    logger.info(f"POLL command started (interval={interval}min, no_alerts={no_alerts}, verbose={verbose})")

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    # Get dependencies
    settings = get_settings()
    session_factory, client, category_filter, alerter = _get_dependencies(settings)

    # Disable alerter if --no-alerts flag is set
    if no_alerts:
        alerter = None

    # Use interval from flag if provided, else from settings
    poll_interval = interval if interval is not None else settings.poll_interval_minutes

    console = Console()
    console.print(f"[bold green]Starting polling loop[/bold green] (interval: {poll_interval} minutes)")

    # Show alert status
    if alerter:
        logger.info("Alerts enabled (Telegram configured)")
        console.print("[bold blue]Alerts enabled[/bold blue] (Telegram configured)")
    else:
        logger.info("Alerts disabled (Telegram not configured or --no-alerts)")
        console.print("[bold yellow]Alerts disabled[/bold yellow] (Telegram not configured or --no-alerts)")

    # Import scheduler
    from src.cli.scheduler import run_polling_loop

    # Run polling loop (blocks until SIGINT/SIGTERM)
    logger.info(f"Entering polling loop (interval={poll_interval}min)")
    run_polling_loop(session_factory, client, category_filter, alerter, interval_minutes=poll_interval)
    logger.info("POLL command completed (graceful shutdown)")


@cli.command()
@click.argument("address")
@click.option("--format", "-f", "output_format", type=click.Choice(["table", "json", "csv"]), default="table",
              help="Output format")
@click.option("--limit", "-l", default=50, type=int, help="Max trades to display (default 50)")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def research(address, output_format, limit, verbose):
    """Query full trade history from JBecker dataset.

    Queries the complete historical dataset (2020-2026) offline without API rate limits.
    Requires JBecker dataset downloaded and JBECKER_DATA_PATH configured.

    ADDRESS can be full address or prefix (e.g., 0xeffd76).

    \b
    Examples:
        polymarket research 0xeffd76
        polymarket research 0xeffd76 --format json
        polymarket research 0xeffd76 --format csv --limit 1000
    """
    logger.info(f"RESEARCH command started (address={address}, format={output_format}, limit={limit}, verbose={verbose})")

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()
    settings = get_settings()

    # Import JBeckerDataset
    from src.datasources.jbecker import JBeckerDataset

    # Create JBecker client
    jbecker = JBeckerDataset(settings.jbecker_data_path)

    # Check if dataset is available
    if not jbecker.is_available():
        console.print("[red]JBecker dataset not available.[/red]\n")
        console.print("[yellow]To download and setup:[/yellow]")
        console.print("1. wget https://s3.jbecker.dev/data.tar.zst  (33.5 GB)")
        console.print("2. tar --use-compress-program=zstd -xvf data.tar.zst")
        console.print("3. Set JBECKER_DATA_PATH in .env to point to the data/ directory")
        console.print("4. Verify: ls $JBECKER_DATA_PATH/polymarket/trades/")
        logger.warning("JBecker dataset not available, exiting")
        return

    # Resolve address (try DB lookup if available, otherwise use as-is)
    full_address = address
    try:
        session_factory, _, _, _ = _get_dependencies(settings)
        with get_session(session_factory) as session:
            resolved = find_trader_by_prefix(session, address)
            if resolved:
                full_address = resolved
                logger.info(f"Resolved address from DB: {full_address}")
    except Exception as e:
        logger.debug(f"DB lookup failed, using address as-is: {e}")

    with console.status(f"[bold green]Querying {limit} trades for {full_address[:10]}...", spinner="dots"):
        # Get total count
        total_count = jbecker.get_trade_count(full_address)
        logger.info(f"Total trades found: {total_count}")

        # Query trades with limit
        trades = jbecker.query_trader_history(full_address, limit=limit)
        logger.info(f"Fetched {len(trades)} trades")

    # Format output based on --format
    if output_format == "table":
        table = format_research_table(trades, full_address, total_count)
        console.print(table)
    elif output_format == "json":
        output = json.dumps(trades, indent=2, default=str)
        console.print(output)
    elif output_format == "csv":
        if trades:
            writer = csv.DictWriter(sys.stdout, fieldnames=trades[0].keys())
            writer.writeheader()
            writer.writerows(trades)
        else:
            console.print("[yellow]No trades found[/yellow]")

    logger.info("RESEARCH command completed")


@cli.command("batch-analyze")
@click.option("--addresses", "-a", multiple=True, help="Trader addresses to analyze")
@click.option("--file", "-f", "address_file", type=click.Path(exists=True), help="File with addresses (one per line)")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def batch_analyze(addresses, address_file, verbose):
    """Bulk ingest trader histories from JBecker dataset.

    Ingests complete trade histories for multiple traders at once,
    storing them in the database for analysis. Uses batch deduplication.

    Provide addresses via --addresses flag (repeatable) or --file flag.

    \b
    Examples:
        polymarket batch-analyze -a 0xeffd76... -a 0xeefa8e...
        polymarket batch-analyze --file traders.txt
    """
    logger.info(f"BATCH-ANALYZE command started (addresses={len(addresses)}, file={address_file}, verbose={verbose})")

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()
    settings = get_settings()

    # Collect addresses from both sources
    all_addresses = list(addresses)

    if address_file:
        with open(address_file, 'r') as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments
                if line and not line.startswith('#'):
                    all_addresses.append(line)
        logger.info(f"Loaded {len(all_addresses) - len(addresses)} addresses from file")

    if not all_addresses:
        console.print("[red]Error: No addresses provided. Use --addresses or --file.[/red]")
        logger.error("No addresses provided")
        return

    logger.info(f"Total addresses to process: {len(all_addresses)}")

    # Import JBeckerDataset
    from src.datasources.jbecker import JBeckerDataset

    # Create JBecker client
    jbecker = JBeckerDataset(settings.jbecker_data_path)

    # Check if dataset is available
    if not jbecker.is_available():
        console.print("[red]JBecker dataset not available.[/red]\n")
        console.print("[yellow]To download and setup:[/yellow]")
        console.print("1. wget https://s3.jbecker.dev/data.tar.zst  (33.5 GB)")
        console.print("2. tar --use-compress-program=zstd -xvf data.tar.zst")
        console.print("3. Set JBECKER_DATA_PATH in .env to point to the data/ directory")
        console.print("4. Verify: ls $JBECKER_DATA_PATH/polymarket/trades/")
        logger.warning("JBecker dataset not available, exiting")
        return

    # Get dependencies
    session_factory, client, category_filter, _ = _get_dependencies(settings)

    # Import pipeline
    from src.pipeline.ingest import IngestionPipeline

    # Create pipeline with JBecker client
    pipeline = IngestionPipeline(client, session_factory, category_filter, jbecker_client=jbecker)

    # Process each trader
    results = []
    total_inserted = 0
    total_skipped = 0
    total_errors = 0

    with console.status("[bold green]Processing traders...", spinner="dots") as status:
        for idx, addr in enumerate(all_addresses, start=1):
            status.update(f"[bold green]Processing {idx}/{len(all_addresses)}: {addr[:10]}...")
            logger.info(f"Processing trader {idx}/{len(all_addresses)}: {addr}")

            try:
                stats = pipeline.ingest_trader_history_jbecker(addr)
                results.append({
                    "address": addr,
                    "found": stats.get("detail_count", 0),
                    "inserted": stats.get("trades_inserted", 0),
                    "skipped": stats.get("duplicates_skipped", 0),
                    "error": None,
                })
                total_inserted += stats.get("trades_inserted", 0)
                total_skipped += stats.get("duplicates_skipped", 0)
                logger.info(f"Success: {stats.get('trades_inserted', 0)} inserted, {stats.get('duplicates_skipped', 0)} skipped")
            except Exception as e:
                logger.warning(f"Error processing {addr}: {e}")
                results.append({
                    "address": addr,
                    "found": 0,
                    "inserted": 0,
                    "skipped": 0,
                    "error": str(e),
                })
                total_errors += 1

    # Display summary table
    table = format_batch_summary(results)
    console.print(table)

    # Print totals
    console.print(f"\n[bold]Totals:[/bold]")
    console.print(f"  Inserted: [green]{total_inserted}[/green]")
    console.print(f"  Skipped:  [yellow]{total_skipped}[/yellow]")
    console.print(f"  Errors:   [red]{total_errors}[/red]")

    logger.info(f"BATCH-ANALYZE command completed: {total_inserted} inserted, {total_skipped} skipped, {total_errors} errors")


if __name__ == "__main__":
    cli()
