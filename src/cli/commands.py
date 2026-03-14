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
    format_pipeline_status,
)
from src.db.models import (
    Base,
    Trader,
    TaxonomyNode,
    Market,
    MarketClassification,
    TokenCatalog,
    Trade,
)
from src.db.session import get_session, get_session_factory
from src.config.settings import get_settings
from src.api.client import PolymarketClient
from src.api.gamma_client import GammaMarketClient
from src.pipeline.filters import CategoryFilter
from src.alerts.telegram import TelegramAlerter
from src.gamma.persist import upsert_gamma_events
from src.gamma.resolution import resolve_market_outcomes
from src.gamma.classification import (
    classify_tokens_from_gamma_events,
    backfill_market_classifications,
)
from src.gamma.position_resolver import resolve_positions


def _get_dependencies(settings=None):
    """Create all pipeline dependencies from settings.

    Creates database engine, session factory, API client, category filter,
    and optional Telegram alerter. Auto-creates database tables if needed.

    Args:
        settings: Optional Settings instance (defaults to get_settings())

    Returns:
        Tuple of (session_factory, client, category_filter, alerter)

    Example:
        session_factory, client, category_filter, alerter, _ = _get_dependencies()
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

    gamma_client = GammaMarketClient(rate_limiter=client.rate_limiter)

    return session_factory, client, category_filter, alerter, gamma_client


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

    # Add file handler with rotation (midnight daily)
    logger.add(
        settings.cli_log_file,
        rotation="00:00",
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
    if ctx.invoked_subcommand is not None or "--help" not in sys.argv:
        _setup_cli_logging()
        logger.info(f"Command invoked: {' '.join(sys.argv)}")


@cli.command()
@click.option(
    "--category", "-c", default=None, help="Filter by category (e.g., eSports)"
)
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
        session_factory, _, _, _, _ = _get_dependencies()

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
                    .join(
                        MarketClassification,
                        MarketClassification.taxonomy_node_id == TaxonomyNode.id,
                    )
                    .where(MarketClassification.market_id == market.condition_id)
                )
                result = session.execute(query)
                slug = result.scalar()

                market_data.append(
                    {
                        "question": market.question,
                        "slug": slug,
                        "active": market.active,
                    }
                )

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
        session_factory, _, _, _, _ = _get_dependencies()

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
                market = (
                    session.query(Market)
                    .filter(Market.condition_id == p.market_id)
                    .first()
                )
                market_question = market.question if market else p.market_id
                positions_data.append(
                    {
                        "market_question": market_question,
                        "direction": p.direction,
                        "size": p.size,
                        "avg_entry_price": p.avg_entry_price,
                    }
                )

            scores_data = [
                {
                    "game": s.game_slug,
                    "score": s.raw_score,
                    "percentile": s.percentile_rank or Decimal("0"),
                    "specialization": s.specialization_label,
                }
                for s in scores
            ]

    logger.info(
        f"Trader profile loaded: {len(summaries_data)} categories, {len(positions_data)} positions, {len(scores_data)} scores"
    )

    # Format and display
    profile = format_trader_profile(
        full_address, summaries_data, positions_data, scores_data
    )
    console.print(profile)
    logger.info("TRADER command completed")


@cli.command()
@click.option("--window", "-w", default=24, help="Time window in hours (1, 6, 24)")
@click.option(
    "--min-confidence", "-c", default=None, type=float, help="Minimum confidence score"
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def signals(window, min_confidence, verbose):
    """Show expert consensus signals.

    Example:
        polymarket signals
        polymarket signals --window 6
        polymarket signals --min-confidence 80
    """
    logger.info(
        f"SIGNALS command started (window={window}h, min_confidence={min_confidence}, verbose={verbose})"
    )

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()

    with console.status("[bold green]Fetching signals...", spinner="dots"):
        # Get dependencies
        session_factory, _, _, _, _ = _get_dependencies()

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
                market = (
                    session.query(Market)
                    .filter(Market.condition_id == signal.market_id)
                    .first()
                )
                market_question = market.question if market else signal.market_id

                signals_data.append(
                    {
                        "market_question": market_question,
                        "direction": signal.direction,
                        "confidence": signal.confidence_score,
                        "expert_count": signal.expert_count,
                        "first_mover_address": signal.first_mover_address,
                    }
                )

    logger.info(f"Found {len(signals_data)} signals")
    for signal in signals_data[:5]:  # Log first 5
        logger.debug(
            f"  - {signal['market_question'][:60]}: {signal['direction']} (conf={signal['confidence']}, experts={signal['expert_count']})"
        )

    # Format and display
    table = format_signals_table(signals_data)
    console.print(table)
    logger.info("SIGNALS command completed")


@cli.command()
@click.argument("slug")
@click.option("--top-n", "-n", default=20, help="Number of entries to display")
@click.option(
    "--depth",
    "-d",
    type=click.Choice(["game", "tournament", "team"]),
    default="game",
    help="Taxonomy depth: game (default), tournament, or team",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def leaderboard(slug, top_n, depth, verbose):
    """Display rankings at game, tournament, or team level.

    SLUG is the taxonomy identifier (game, tournament, or team slug).
    Use --depth to specify the taxonomy level.

    Examples:
        polymarket leaderboard esports.cs2
        polymarket leaderboard esports.cs2.iem-katowice --depth tournament
        polymarket leaderboard esports.cs2.iem-katowice.navi --depth team
    """
    logger.info(
        f"LEADERBOARD command started (slug={slug}, top_n={top_n}, depth={depth}, verbose={verbose})"
    )

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    depth_map = {"game": 1, "tournament": 2, "team": 3}
    depth_int = depth_map[depth]

    console = Console()

    with console.status("[bold green]Fetching leaderboard...", spinner="dots"):
        session_factory, _, _, _, _ = _get_dependencies()

        with get_session(session_factory) as session:
            from src.pipeline.queries import (
                get_game_leaderboard,
                get_taxonomy_leaderboard,
            )

            if depth == "game":
                query = select(TaxonomyNode.slug).where(
                    TaxonomyNode.slug.like("esports.%"),
                    TaxonomyNode.node_type == "game",
                )
                result = session.execute(query)
                valid_slugs = result.scalars().all()

                if slug not in valid_slugs:
                    logger.error(
                        f"Invalid game slug: {slug}. Valid games: {valid_slugs}"
                    )
                    console.print(
                        f"[bold red]Error: Game '{slug}' not found.[/bold red]"
                    )
                    console.print("\n[bold]Available games:[/bold]")
                    for game in sorted(valid_slugs):
                        console.print(f"  - {game}")
                    return

                leaderboard_entries = get_game_leaderboard(session, slug, top_n=top_n)
            else:
                query = select(TaxonomyNode.slug).where(
                    TaxonomyNode.slug == slug, TaxonomyNode.depth == depth_int
                )
                result = session.execute(query)
                valid_slugs = result.scalars().all()

                if slug not in valid_slugs:
                    logger.error(f"Invalid {depth} slug: {slug}")
                    console.print(
                        f"[bold red]Error: {depth.title()} '{slug}' not found.[/bold red]"
                    )
                    return

                leaderboard_entries = get_taxonomy_leaderboard(
                    session, slug, depth_int, top_n=top_n
                )

            entries_data = [
                {
                    "rank": idx + 1,
                    "trader_address": entry.trader_address,
                    "score": entry.raw_score,
                    "win_rate": entry.win_rate_component or Decimal("0"),
                }
                for idx, entry in enumerate(leaderboard_entries)
            ]

    logger.info(f"Leaderboard loaded: {len(entries_data)} entries for {slug}")

    depth_label = depth.title() if depth != "game" else "Game"
    table = format_leaderboard_table(entries_data, slug, depth_label=depth_label)
    console.print(table)
    logger.info("LEADERBOARD command completed")


@cli.command()
@click.argument("address")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def expertise(address, verbose):
    """Show trader expertise breakdown across all taxonomy depths.

    Displays scores at game, tournament, and team levels to reveal
    where a trader truly specializes.

    Example:
        polymarket expertise 0xTrader123
    """
    logger.info(f"EXPERTISE command started (address={address}, verbose={verbose})")

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()

    with console.status("[bold green]Fetching expertise breakdown...", spinner="dots"):
        session_factory, _, _, _, _ = _get_dependencies()

        with get_session(session_factory) as session:
            address = find_trader_by_prefix(session, address)
            if not address:
                console.print("[bold red]Error: Trader not found.[/bold red]")
                return

            from sqlalchemy import func
            from src.db.models import ExpertiseScore
            from src.pipeline.scoring_pipeline import LeaderboardEntry

            scores_by_depth: dict[int, list] = {1: [], 2: [], 3: []}

            for depth in [1, 2, 3]:
                subquery = (
                    select(
                        ExpertiseScore.trader_address,
                        ExpertiseScore.game_slug,
                        func.max(ExpertiseScore.computed_at).label("max_computed_at"),
                    )
                    .where(ExpertiseScore.trader_address == address)
                    .where(ExpertiseScore.taxonomy_depth == depth)
                    .group_by(ExpertiseScore.trader_address, ExpertiseScore.game_slug)
                    .subquery()
                )

                query = (
                    select(ExpertiseScore)
                    .join(
                        subquery,
                        (ExpertiseScore.trader_address == subquery.c.trader_address)
                        & (ExpertiseScore.computed_at == subquery.c.max_computed_at),
                    )
                    .where(ExpertiseScore.trader_address == address)
                    .where(ExpertiseScore.taxonomy_depth == depth)
                )

                results = session.execute(query).scalars().all()

                for score in results:
                    scores_by_depth[depth].append(
                        {
                            "slug": score.game_slug,
                            "score": score.raw_score,
                            "percentile": score.percentile_rank or score.raw_score,
                            "specialization": score.specialization_label,
                        }
                    )

    logger.info(f"Expertise loaded for {address}")

    from src.cli.formatters import format_expertise_breakdown

    output = format_expertise_breakdown(address, scores_by_depth)
    console.print(output)
    logger.info("EXPERTISE command completed")


@cli.command()
@click.argument("game_slug")
@click.option(
    "--game-threshold", default=60.0, help="Max game score for 'average' (default 60)"
)
@click.option(
    "--deep-threshold",
    default=75.0,
    help="Min deep score for 'specialist' (default 75)",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def specialists(game_slug, game_threshold, deep_threshold, verbose):
    """Discover hidden specialists in a game.

    Finds traders with average game-level scores but high tournament/team scores.
    These are niche experts who specialize deeply.

    Example:
        polymarket specialists esports.cs2
        polymarket specialists esports.cs2 --game-threshold 50 --deep-threshold 80
    """
    logger.info(
        f"SPECIALISTS command started (game_slug={game_slug}, "
        f"game_threshold={game_threshold}, deep_threshold={deep_threshold}, verbose={verbose})"
    )

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()

    with console.status(
        "[bold green]Discovering hidden specialists...", spinner="dots"
    ):
        session_factory, _, _, _, _ = _get_dependencies()

        with get_session(session_factory) as session:
            from src.pipeline.scoring_pipeline import identify_hidden_specialists

            specialists_list = identify_hidden_specialists(
                session,
                game_slug,
                game_score_threshold=Decimal(str(game_threshold)),
                deep_score_threshold=Decimal(str(deep_threshold)),
            )

    logger.info(f"Found {len(specialists_list)} hidden specialists")

    from src.cli.formatters import format_specialists_table

    table = format_specialists_table(specialists_list, game_slug)
    console.print(table)
    logger.info("SPECIALISTS command completed")



@cli.command()
@click.option(
    "--interval", "-i", default=None, type=int, help="Polling interval in minutes"
)
@click.option(
    "--niche",
    "-n",
    multiple=True,
    help="Niche category to scan (repeatable)",
)
@click.option(
    "--closing-within",
    default=None,
    help="Only scan markets closing within time window (e.g., 48h, 2d)",
)
@click.option("--no-alerts", is_flag=True, help="Skip alert delivery")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def poll(interval, niche, closing_within, no_alerts, verbose):
    """Run automated polling loop.

    Executes market refresh → score → detect → alert at regular intervals.
    Does NOT discover or backfill new traders — run those separately.
    Press Ctrl+C for graceful shutdown.

    Example:
        polymarket poll
        polymarket poll --interval 30
        polymarket poll --no-alerts
        polymarket poll --niche esports
        polymarket poll --niche esports --closing-within 48h
    """
    logger.info(
        f"POLL command started (interval={interval}min, niches={niche}, closing_within={closing_within}, no_alerts={no_alerts}, verbose={verbose})"
    )

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()

    if niche:
        console.print(f"[bold blue]Scanning niches:[/bold blue] {', '.join(niche)}")
    if closing_within:
        from src.pipeline.time_utils import parse_closing_within

        try:
            threshold = parse_closing_within(closing_within)
            console.print(
                f"[bold blue]Closing within:[/bold blue] {closing_within} (before {threshold})"
            )
        except ValueError as e:
            console.print(f"[bold red]Error: {e}[/bold red]")
            return

    settings = get_settings()
    session_factory, client, category_filter, alerter, gamma_client = _get_dependencies(
        settings
    )

    if no_alerts:
        alerter = None

    poll_interval = interval if interval is not None else settings.poll_interval_minutes

    console = Console()
    console.print(
        f"[bold green]Starting polling loop[/bold green] (interval: {poll_interval} minutes)"
    )

    if alerter:
        logger.info("Alerts enabled (Telegram configured)")
        console.print("[bold blue]Alerts enabled[/bold blue] (Telegram configured)")
    else:
        logger.info("Alerts disabled (Telegram not configured or --no-alerts)")
        console.print(
            "[bold yellow]Alerts disabled[/bold yellow] (Telegram not configured or --no-alerts)"
        )

    from src.cli.scheduler import run_polling_loop

    logger.info(f"Entering polling loop (interval={poll_interval}min)")
    run_polling_loop(
        session_factory,
        client,
        category_filter,
        alerter,
        interval_minutes=poll_interval,
        gamma_client=gamma_client,
        niches=niche,
        closing_within=closing_within,
    )
    logger.info("POLL command completed (graceful shutdown)")


@cli.command()
@click.argument("address")
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "csv"]),
    default="table",
    help="Output format",
)
@click.option(
    "--limit", "-l", default=50, type=int, help="Max trades to display (default 50)"
)
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
    logger.info(
        f"RESEARCH command started (address={address}, format={output_format}, limit={limit}, verbose={verbose})"
    )

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
        console.print(
            "3. Set JBECKER_DATA_PATH in .env to point to the data/ directory"
        )
        console.print("4. Verify: ls $JBECKER_DATA_PATH/polymarket/trades/")
        logger.warning("JBecker dataset not available, exiting")
        return

    # Resolve address (try DB lookup if available, otherwise use as-is)
    full_address = address
    try:
        session_factory, _, _, _, _ = _get_dependencies(settings)
        with get_session(session_factory) as session:
            resolved = find_trader_by_prefix(session, address)
            if resolved:
                full_address = resolved
                logger.info(f"Resolved address from DB: {full_address}")
    except Exception as e:
        logger.debug(f"DB lookup failed, using address as-is: {e}")

    with console.status(
        f"[bold green]Querying {limit} trades for {full_address[:10]}...",
        spinner="dots",
    ):
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
@click.option(
    "--file",
    "-f",
    "address_file",
    type=click.Path(exists=True),
    help="File with addresses (one per line)",
)
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
    logger.info(
        f"BATCH-ANALYZE command started (addresses={len(addresses)}, file={address_file}, verbose={verbose})"
    )

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()
    settings = get_settings()

    # Collect addresses from both sources
    all_addresses = list(addresses)

    if address_file:
        with open(address_file, "r") as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments
                if line and not line.startswith("#"):
                    all_addresses.append(line)
        logger.info(f"Loaded {len(all_addresses) - len(addresses)} addresses from file")

    if not all_addresses:
        console.print(
            "[red]Error: No addresses provided. Use --addresses or --file.[/red]"
        )
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
        console.print(
            "3. Set JBECKER_DATA_PATH in .env to point to the data/ directory"
        )
        console.print("4. Verify: ls $JBECKER_DATA_PATH/polymarket/trades/")
        logger.warning("JBecker dataset not available, exiting")
        return

    # Get dependencies
    session_factory, client, category_filter, _, _ = _get_dependencies(settings)

    # Import pipeline
    from src.pipeline.ingest import IngestionPipeline

    # Create pipeline with JBecker client
    pipeline = IngestionPipeline(
        client, session_factory, category_filter, jbecker_client=jbecker
    )

    # Process each trader
    results = []
    total_inserted = 0
    total_skipped = 0
    total_errors = 0

    with console.status("[bold green]Processing traders...", spinner="dots") as status:
        for idx, addr in enumerate(all_addresses, start=1):
            status.update(
                f"[bold green]Processing {idx}/{len(all_addresses)}: {addr[:10]}..."
            )
            logger.info(f"Processing trader {idx}/{len(all_addresses)}: {addr}")

            try:
                stats = pipeline.ingest_trader_history_jbecker(addr)
                results.append(
                    {
                        "address": addr,
                        "found": stats.get("detail_count", 0),
                        "inserted": stats.get("trades_inserted", 0),
                        "skipped": stats.get("duplicates_skipped", 0),
                        "error": None,
                    }
                )
                total_inserted += stats.get("trades_inserted", 0)
                total_skipped += stats.get("duplicates_skipped", 0)
                logger.info(
                    f"Success: {stats.get('trades_inserted', 0)} inserted, {stats.get('duplicates_skipped', 0)} skipped"
                )
            except Exception as e:
                logger.warning(f"Error processing {addr}: {e}")
                results.append(
                    {
                        "address": addr,
                        "found": 0,
                        "inserted": 0,
                        "skipped": 0,
                        "error": str(e),
                    }
                )
                total_errors += 1

    # Display summary table
    table = format_batch_summary(results)
    console.print(table)

    # Print totals
    console.print(f"\n[bold]Totals:[/bold]")
    console.print(f"  Inserted: [green]{total_inserted}[/green]")
    console.print(f"  Skipped:  [yellow]{total_skipped}[/yellow]")
    console.print(f"  Errors:   [red]{total_errors}[/red]")

    logger.info(
        f"BATCH-ANALYZE command completed: {total_inserted} inserted, {total_skipped} skipped, {total_errors} errors"
    )


@cli.command()
@click.option(
    "--niche",
    "-n",
    multiple=True,
    help="Niche category to scan (repeatable, e.g., --niche esports --niche crypto)",
)
@click.option(
    "--closing-within",
    default=None,
    help="Only scan markets closing within this time window (e.g., 48h, 2d)",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def discover(niche, closing_within, verbose):
    """Discover traders from active markets without backfilling history.

    Finds new trader addresses from market trade data and stores them
    with backfill_complete=False. Does NOT fetch their full trade history.
    Use 'backfill' command separately to fetch history.

    \b
    Examples:
        polymarket discover
        polymarket discover --niche esports
        polymarket discover --niche esports --closing-within 48h
    """
    logger.info(
        f"DISCOVER command started (niches={niche}, closing_within={closing_within})"
    )

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()

    if niche:
        console.print(f"[bold blue]Scanning niches:[/bold blue] {', '.join(niche)}")
    if closing_within:
        from src.pipeline.time_utils import parse_closing_within

        try:
            threshold = parse_closing_within(closing_within)
            console.print(
                f"[bold blue]Closing within:[/bold blue] {closing_within} (before {threshold})"
            )
        except ValueError as e:
            console.print(f"[bold red]Error: {e}[/bold red]")
            return

    with console.status("[bold green]Discovering traders...", spinner="dots"):
        import time

        start_time = time.time()

        session_factory, client, category_filter, _, gamma_client = _get_dependencies()

        from src.pipeline.ingest import IngestionPipeline

        pipeline = IngestionPipeline(
            client, session_factory, category_filter, gamma_client=gamma_client
        )

        end_date_max = None
        if closing_within:
            from src.pipeline.time_utils import parse_closing_within

            end_date_max = parse_closing_within(closing_within)

        if niche or end_date_max:
            markets_count = pipeline.ingest_targeted_markets(
                niches=niche, end_date_max=end_date_max
            )
        else:
            markets_count = pipeline.ingest_active_markets()

        traders_discovered = 0
        with get_session(session_factory) as session:
            query = session.query(Market).filter_by(active=True)
            if niche:
                from sqlalchemy import or_

                query = query.filter(
                    or_(*[Market.category.ilike(f"%{n}%") for n in niche])
                )
            if end_date_max:
                query = query.filter(Market.end_date <= end_date_max)
            markets_orm = query.all()
            detail_markets = [
                m for m in markets_orm if category_filter.requires_detail(m.category)
            ]

            for market in detail_markets:
                try:
                    new_traders = pipeline.discover_traders_from_market(
                        market.condition_id
                    )
                    traders_discovered += len(new_traders)
                except Exception as e:
                    logger.warning(
                        f"Failed to discover traders from {market.condition_id}: {e}"
                    )
                    continue

        processing_time = time.time() - start_time

    console.print(
        f"\n[bold green]Discovery complete[/bold green] ({processing_time:.1f}s)"
    )
    console.print(f"  Markets scanned: {markets_count}")
    console.print(f"  Detail markets:  {len(detail_markets)}")
    console.print(f"  New traders:     [green]{traders_discovered}[/green]")
    console.print(
        "\n[dim]Run 'polymarket backfill' to fetch history for discovered traders.[/dim]"
    )
    logger.info(
        f"DISCOVER completed: {markets_count} markets, {traders_discovered} traders ({processing_time:.1f}s)"
    )


def _build_dynamic_batches(
    trader_addresses: list[str],
    files_per_trader: dict[str, list[str]],
    max_files: int,
    max_traders: int,
) -> list[list[str]]:
    """Group traders into variable-size batches bounded by total unique parquet file count.

    Ensures each batch's DuckDB query opens at most max_files files simultaneously,
    keeping memory usage bounded regardless of individual trader trade volume.

    Whale traders (file count > max_files) get solo batches — their files are
    then sub-batched inside query_trader_history_subbatched().

    Args:
        trader_addresses: Ordered list of addresses to batch.
        files_per_trader: {normalized_address: [file_paths]} from lookup_per_trader().
        max_files: Max unique parquet files per batch.
        max_traders: Secondary cap on batch size (for traders with few/no files).

    Returns:
        List of batches, each batch being a list of trader addresses.
    """

    def _norm(addr: str) -> str:
        a = addr.lower()
        return a if a.startswith("0x") else f"0x{a}"

    batches: list[list[str]] = []
    current_batch: list[str] = []
    current_files: set[str] = set()

    for addr in trader_addresses:
        trader_files = set(files_per_trader.get(_norm(addr), []))

        if len(trader_files) > max_files:
            # Whale: flush current batch first, then give whale its own solo batch
            if current_batch:
                batches.append(current_batch)
                current_batch = []
                current_files = set()
            batches.append([addr])
            continue

        combined = current_files | trader_files
        at_file_limit = len(combined) > max_files and current_batch
        at_trader_limit = len(current_batch) >= max_traders

        if (at_file_limit or at_trader_limit) and current_batch:
            batches.append(current_batch)
            current_batch = [addr]
            current_files = trader_files
        else:
            current_batch.append(addr)
            current_files = combined

    if current_batch:
        batches.append(current_batch)

    return batches


@cli.command()
@click.argument("address", required=False, default=None)
@click.option(
    "--limit",
    "-l",
    default=None,
    type=int,
    help="Maximum number of traders to backfill (default: all pending)",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def backfill(address, limit, verbose):
    """Backfill trade history for discovered traders.

    Without ADDRESS, backfills all traders with pending history.
    With ADDRESS, backfills only that specific trader.

    Uses the 4-tier cost-optimized hierarchy:
    JBecker (free) > API (free) > Graph (paid) > Blockchain (slow)

    \b
    Examples:
        polymarket backfill
        polymarket backfill --limit 10
        polymarket backfill 0xeffd76
    """
    logger.info(f"BACKFILL command started (address={address}, limit={limit})")

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()

    session_factory, client, category_filter, _, gamma_client = _get_dependencies()

    from src.pipeline.ingest import IngestionPipeline
    from src.pipeline.queries import get_traders_by_backfill_status
    from src.datasources.jbecker import JBeckerDataset

    settings = get_settings()
    jbecker_client = None
    try:
        jbecker = JBeckerDataset(settings.jbecker_data_path)
        if jbecker.is_available():
            jbecker_client = jbecker
            logger.info("JBecker dataset available — will use as primary source")
    except Exception as e:
        logger.warning(f"JBecker dataset not available: {e}")

    pipeline = IngestionPipeline(
        client,
        session_factory,
        category_filter,
        gamma_client=gamma_client,
        jbecker_client=jbecker_client,
    )

    if address:
        with get_session(session_factory) as session:
            full_address = find_trader_by_prefix(session, address)
            if not full_address:
                return

        console.print(f"[bold blue]Backfilling:[/bold blue] {full_address}")
        with console.status(
            f"[bold green]Backfilling {full_address[:10]}...", spinner="dots"
        ):
            try:
                stats = pipeline.ingest_trader_history_hybrid(full_address)
                console.print(f"[green]Backfill complete[/green]")
                console.print(f"  Tiers used: {', '.join(stats.get('tiers_used', []))}")
                console.print(f"  Detail trades: {stats.get('detail_count', 0)}")
                _run_catalog_patch(session_factory, gamma_client, console)
            except Exception as e:
                console.print(f"[red]Backfill failed: {e}[/red]")
                logger.error(f"Single trader backfill failed: {e}")
    else:
        with get_session(session_factory) as session:
            pending = get_traders_by_backfill_status(session, backfilled=False)
            trader_addresses = [t.address for t in pending]

        if not trader_addresses:
            console.print("[green]No traders pending backfill.[/green]")
            logger.info("No traders pending backfill")
            return

        if limit:
            trader_addresses = trader_addresses[:limit]

        console.print(
            f"[bold blue]Backfilling {len(trader_addresses)} traders[/bold blue]"
            + (f" (limited to {limit})" if limit else "")
        )

        import time

        start_time = time.time()
        success_count = 0
        error_count = 0

        # Build token cache once for all traders (avoids N per-trader DB scans)
        token_cache = None
        if jbecker_client and jbecker_client.is_available():
            with get_session(session_factory) as session:
                token_cache = pipeline._build_token_cache(session)
            logger.info(
                f"Built token cache: {len(token_cache[0])} tokens, {len(token_cache[1])} conditions"
            )

        use_jbecker_batch = jbecker_client and jbecker_client.is_available()

        # Build memory-aware batches bounded by parquet file count.
        # Each batch opens at most MAX_FILES_PER_BATCH files in DuckDB simultaneously.
        # Whale traders (file count > limit) get solo batches with internal sub-batching.
        MAX_FILES_PER_BATCH = 1500
        MAX_TRADERS_PER_BATCH = 100

        def _norm(addr: str) -> str:
            a = addr.lower()
            return a if a.startswith("0x") else f"0x{a}"

        if use_jbecker_batch and jbecker_client._index.is_built:
            console.print(
                f"[dim]Scanning file index for {len(trader_addresses)} traders...[/dim]"
            )
            files_per_trader = jbecker_client._index.lookup_per_trader(trader_addresses)
            batches = _build_dynamic_batches(
                trader_addresses,
                files_per_trader,
                MAX_FILES_PER_BATCH,
                MAX_TRADERS_PER_BATCH,
            )
            whale_count = sum(
                1
                for addr in trader_addresses
                if len(files_per_trader.get(_norm(addr), [])) > MAX_FILES_PER_BATCH
            )
            console.print(
                f"[dim]{len(batches)} batches built "
                f"({whale_count} whale traders will be sub-batched)[/dim]"
            )
            logger.info(
                f"Dynamic batching: {len(batches)} batches, {whale_count} whales, "
                f"max {MAX_FILES_PER_BATCH} files/batch"
            )
        else:
            files_per_trader = {}
            batches = [
                trader_addresses[i : i + MAX_TRADERS_PER_BATCH]
                for i in range(0, len(trader_addresses), MAX_TRADERS_PER_BATCH)
            ]
            whale_count = 0
            console.print(f"[dim]{len(batches)} fixed batches (no file index)[/dim]")

        num_batches = len(batches)

        with console.status(
            "[bold green]Backfilling traders...", spinner="dots"
        ) as status:
            global_idx = 0
            for batch_num, batch in enumerate(batches, 1):
                prefetched_by_address: dict[str, list[dict]] = {}

                if use_jbecker_batch:
                    is_solo_whale = (
                        len(batch) == 1
                        and jbecker_client._index.is_built
                        and len(files_per_trader.get(_norm(batch[0]), []))
                        > MAX_FILES_PER_BATCH
                    )
                    label = " — whale sub-batch" if is_solo_whale else ""
                    status.update(
                        f"[bold green]JBecker fetch: batch {batch_num}/{num_batches} "
                        f"({len(batch)} traders{label})..."
                    )
                    logger.info(
                        f"JBecker batch {batch_num}/{num_batches}: "
                        f"{len(batch)} traders{label}"
                    )
                    try:
                        if is_solo_whale:
                            addr = batch[0]
                            trades = jbecker_client.query_trader_history_subbatched(
                                addr, max_files_per_batch=MAX_FILES_PER_BATCH
                            )
                            prefetched_by_address = {addr.lower(): trades}
                            logger.info(
                                f"Whale prefetch: {len(trades)} trades for {addr[:10]}..."
                            )
                        else:
                            prefetched_by_address = (
                                jbecker_client.batch_query_traders_history(batch)
                            )
                            logger.info(
                                f"Prefetched {len(prefetched_by_address)} traders "
                                f"(batch {batch_num}/{num_batches})"
                            )
                    except Exception as e:
                        logger.warning(f"JBecker batch {batch_num} failed: {e}")

                for addr in batch:
                    global_idx += 1
                    status.update(
                        f"[bold green]Backfilling {global_idx}/{len(trader_addresses)}: "
                        f"{addr[:10]}... (batch {batch_num}/{num_batches})"
                    )
                    try:
                        prefetched = prefetched_by_address.get(addr.lower())
                        pipeline.ingest_trader_history_hybrid(
                            addr,
                            prefetched_jbecker_trades=prefetched,
                            token_cache=token_cache,
                        )
                        success_count += 1
                    except Exception as e:
                        logger.warning(f"Backfill failed for {addr[:10]}...: {e}")
                        error_count += 1
                        continue

                # Free memory before next batch
                prefetched_by_address.clear()

        processing_time = time.time() - start_time

        console.print(
            f"\n[bold green]Backfill complete[/bold green] ({processing_time:.1f}s)"
        )
        console.print(f"  Successful: [green]{success_count}[/green]")
        if error_count:
            console.print(f"  Failed:     [red]{error_count}[/red]")
        logger.info(
            f"BACKFILL completed: {success_count} ok, {error_count} failed ({processing_time:.1f}s)"
        )
        _run_catalog_patch(session_factory, gamma_client, console)


def _run_catalog_patch(session_factory, gamma_client, console):
    """Run catalog gap detection and patch. Called after backfill completes."""
    from src.catalog.patcher import patch_missing_catalog_entries
    with get_session(session_factory) as session:
        patch_stats = patch_missing_catalog_entries(session, gamma_client)
    if patch_stats["patched"] > 0:
        console.print(
            f"  Catalog patched: [cyan]{patch_stats['patched']} markets[/cyan]"
            f" (local={patch_stats['local']}, api={patch_stats['api']},"
            f" fallback={patch_stats['fallback']})"
        )
    return patch_stats


@cli.command("patch-catalog")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def patch_catalog_cmd(verbose):
    """Detect and patch token_catalog gaps.

    Finds trades.market_id values with no token_catalog entry and patches
    them via local gamma_events join, Gamma API, or category-only fallback.

    Safe to re-run -- idempotent (INSERT OR IGNORE).

    \b
    Examples:
        polymarket patch-catalog
        polymarket patch-catalog --verbose
    """
    logger.info("PATCH-CATALOG command started")

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()
    session_factory, _, _, _, gamma_client = _get_dependencies()

    from src.catalog.patcher import patch_missing_catalog_entries
    with get_session(session_factory) as session:
        stats = patch_missing_catalog_entries(session, gamma_client)

    if stats["patched"] == 0:
        console.print("[green]No catalog gaps detected.[/green]")
    else:
        console.print(f"[bold green]Catalog patched:[/bold green] {stats['patched']} markets")
        console.print(f"  Local (gamma_events): {stats['local']}")
        console.print(f"  API lookup:           {stats['api']}")
        console.print(f"  Category fallback:    {stats['fallback']}")

    logger.info(
        f"PATCH-CATALOG completed: patched={stats['patched']}, "
        f"local={stats['local']}, api={stats['api']}, fallback={stats['fallback']}"
    )


@cli.command("recover-catalog")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def recover_catalog_cmd(verbose):
    """Populate markets.tokens for null-token eSports gap markets, then re-patch.

    Fetches eSports events from Gamma API (tag_id=64), extracts token IDs for
    null-token markets, populates markets.tokens, and runs the patcher.

    Safe to re-run -- idempotent (skips already-populated markets).

    \b
    Examples:
        polymarket recover-catalog
        polymarket recover-catalog --verbose
    """
    logger.info("RECOVER-CATALOG command started")

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()
    session_factory, _, _, _, gamma_client = _get_dependencies()

    from src.catalog.recovery import recover_esports_token_gaps
    with get_session(session_factory) as session:
        stats = recover_esports_token_gaps(session)

    if stats["found"] == 0:
        console.print("[green]No null-token eSports gap markets found.[/green]")
    else:
        console.print(f"[bold green]Recovery complete:[/bold green]")
        console.print(f"  Gap markets found:    {stats['found']}")
        console.print(f"  Tokens populated:     {stats['populated']}")
        console.print(f"  Already done (skip):  {stats['already_done']}")
        console.print(f"  Catalog patched:      {stats.get('patched', 0)} markets")
        console.print(f"    Local (gamma_events): {stats.get('local', 0)}")
        console.print(f"    API lookup:           {stats.get('api', 0)}")
        console.print(f"    Category fallback:    {stats.get('fallback', 0)}")

    logger.info(
        f"RECOVER-CATALOG completed: found={stats['found']}, "
        f"populated={stats['populated']}, already_done={stats['already_done']}, "
        f"patched={stats.get('patched', 0)}"
    )


@cli.command()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def score(verbose):
    """Compute expertise scores for all traders.

    Calculates game-level expertise scores across all traders with trade history.
    Scores are stored in the expertise_scores table and used for signal detection.

    \b
    Examples:
        polymarket score
    """
    logger.info("SCORE command started")

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()

    import time

    start_time = time.time()

    session_factory, _, _, _, _ = _get_dependencies()

    with console.status("[bold green]Computing positions from trades...", spinner="dots"):
        from src.discovery.trader_discovery import refresh_all_positions

        with get_session(session_factory) as session:
            pos_stats = refresh_all_positions(session)

    console.print(f"  Positions computed: {pos_stats['positions_computed']} ({pos_stats['traders_processed']} traders)")

    with console.status("[bold green]Computing expertise scores...", spinner="dots"):
        from src.pipeline.scoring_pipeline import compute_all_game_scores

        with get_session(session_factory) as session:
            leaderboards = compute_all_game_scores(session)
            session.commit()

    elapsed = time.time() - start_time
    total_entries = sum(len(entries) for entries in leaderboards.values())

    console.print(f"\n[bold green]Scoring complete[/bold green] ({elapsed:.1f}s)")
    console.print(f"  Games scored:    {len(leaderboards)}")
    console.print(f"  Total entries:   {total_entries}")
    console.print(
        "\n[dim]Run 'polymarket detect' to refresh signals, or 'polymarket signals' to view existing signals.[/dim]"
    )
    logger.info(
        f"SCORE completed: {len(leaderboards)} games, {total_entries} entries ({elapsed:.1f}s)"
    )


@cli.command()
@click.option(
    "--window",
    "-w",
    default=24,
    help="Time window in hours for expert activity (default: 24)",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def detect(window, verbose):
    """Detect and refresh expert consensus signals.

    Recomputes signal detection across all active markets where experts have
    traded. Results are stored and can be viewed with 'polymarket signals'.

    \b
    Examples:
        polymarket detect
        polymarket detect --window 6
    """
    logger.info(f"DETECT command started (window={window}h)")

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()

    import time

    start_time = time.time()

    session_factory, _, _, _, _ = _get_dependencies()

    with console.status("[bold green]Detecting signals...", spinner="dots"):
        from src.signals.pipeline import refresh_all_signals

        with get_session(session_factory) as session:
            detected = refresh_all_signals(session, window_hours=window)
            session.commit()

    elapsed = time.time() - start_time

    console.print(f"\n[bold green]Detection complete[/bold green] ({elapsed:.1f}s)")
    console.print(f"  Signals detected: {len(detected)}")
    console.print("\n[dim]Run 'polymarket signals' to view detected signals.[/dim]")
    logger.info(f"DETECT completed: {len(detected)} signals ({elapsed:.1f}s)")


@cli.command()
@click.option(
    "--window",
    "-w",
    default=24,
    help="Time window in hours for signals to alert (default: 24)",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def alert(window, verbose):
    """Deliver pending signal alerts via Telegram.

    Sends expert consensus signals to configured Telegram chat.
    Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env.

    \b
    Examples:
        polymarket alert
        polymarket alert --window 6
    """
    logger.info(f"ALERT command started (window={window}h)")

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()

    session_factory, _, _, alerter, _ = _get_dependencies()

    if alerter is None:
        console.print(
            "[yellow]No alerter configured.[/yellow] "
            "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env to enable alerts."
        )
        return

    import time

    start_time = time.time()

    with console.status("[bold green]Delivering alerts...", spinner="dots"):
        from src.alerts.delivery import deliver_signal_alerts

        with get_session(session_factory) as session:
            results = deliver_signal_alerts(session, alerter, window_hours=window)

    elapsed = time.time() - start_time

    sent = sum(1 for r in results if r.success)
    failed = sum(1 for r in results if not r.success)

    console.print(f"\n[bold green]Alerts delivered[/bold green] ({elapsed:.1f}s)")
    console.print(f"  Sent:   [green]{sent}[/green]")
    console.print(f"  Failed: [red]{failed}[/red]")
    logger.info(f"ALERT completed: {sent} sent, {failed} failed ({elapsed:.1f}s)")


@cli.command("resolve-profiles")
@click.option(
    "--limit",
    "-l",
    default=None,
    type=int,
    help="Maximum number of traders to resolve (default: all pending)",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def resolve_profiles(limit, verbose):
    """Resolve Polymarket profiles for discovered traders.

    Queries the Polymarket public profile API to resolve proxy wallet
    addresses to real user profiles. This helps identify:
    - Traders with actual Polymarket profiles (not just proxy contracts)
    - Display names for verified traders
    - Filter out bots/contracts without profiles

    \b
    Examples:
        polymarket resolve-profiles
        polymarket resolve-profiles --limit 50
    """
    logger.info(f"RESOLVE-PROFILES command started (limit={limit})")

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()

    session_factory, client, category_filter, _, gamma_client = _get_dependencies()

    if gamma_client is None:
        console.print("[red]Error: Gamma client not configured.[/red]")
        logger.error("Gamma client not available")
        return

    from src.pipeline.ingest import IngestionPipeline
    from src.db.models import Trader
    from src.db.session import get_session

    pipeline = IngestionPipeline(
        client, session_factory, category_filter, gamma_client=gamma_client
    )

    console.print("[bold blue]Running database migration...[/bold blue]")

    import time

    start_time = time.time()

    with console.status("[bold green]Resolving profiles...", spinner="dots"):
        try:
            profiles_found = pipeline.resolve_trader_profiles(limit=limit)
        except Exception as e:
            console.print(f"[red]Profile resolution failed: {e}[/red]")
            logger.error(f"Profile resolution failed: {e}")
            return

    processing_time = time.time() - start_time

    try:
        with get_session(session_factory) as session:
            pending_count = (
                session.query(Trader).filter_by(profile_resolved=False).count()
            )
    except Exception:
        pending_count = 0

    if pending_count == 0:
        console.print("[green]All traders have been resolved already.[/green]")
        logger.info("All traders already resolved")
    else:
        console.print(
            f"[bold green]Profile resolution complete[/bold green] ({processing_time:.1f}s)"
        )
        console.print(f"  Profiles found:    [green]{profiles_found}[/green]")
        console.print(f"  Still unresolved: [yellow]{pending_count}[/yellow]")

    logger.info(
        f"RESOLVE-PROFILES completed: {profiles_found} profiles ({processing_time:.1f}s)"
    )


@cli.command()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def status(verbose):
    """View pipeline discovery and backfill status.

    Shows how many traders have been discovered vs. backfilled,
    and lists traders pending backfill.

    \b
    Example:
        polymarket status
    """
    logger.info("STATUS command started")

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()

    with console.status("[bold green]Fetching status...", spinner="dots"):
        session_factory, _, _, _, _ = _get_dependencies()

        from src.pipeline.queries import (
            get_trader_counts_by_status,
            get_traders_by_backfill_status,
        )

        with get_session(session_factory) as session:
            counts = get_trader_counts_by_status(session)
            pending = get_traders_by_backfill_status(session, backfilled=False)

            pending_data = [
                {
                    "address": t.address,
                    "first_seen": t.first_seen.strftime("%Y-%m-%d %H:%M")
                    if t.first_seen
                    else "",
                }
                for t in pending[:50]
            ]

    output = format_pipeline_status(counts, pending_data)
    console.print(output)
    logger.info(
        f"STATUS completed: {counts['total']} total, {counts['discovered']} pending, {counts['backfilled']} backfilled"
    )


@cli.command("catalog-stats")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def catalog_stats(verbose):
    """Show token catalog statistics.

    Displays total rows, esports coverage, per-game breakdown,
    and unclassified market count from the token_catalog table.

    \b
    Example:
        polymarket catalog-stats
    """
    logger.info("CATALOG-STATS command started")

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()

    with console.status("[bold green]Querying token catalog...", spinner="dots"):
        session_factory, _, _, _, _ = _get_dependencies()

        with get_session(session_factory) as session:
            from sqlalchemy import func

            # Total rows
            total = session.query(func.count(TokenCatalog.token_id)).scalar() or 0

            # Esports rows
            esports_total = (
                session.query(func.count(TokenCatalog.token_id))
                .filter(TokenCatalog.niche_slug == "esports")
                .scalar()
                or 0
            )

            # Unclassified rows (niche_slug IS NULL)
            unclassified = (
                session.query(func.count(TokenCatalog.token_id))
                .filter(TokenCatalog.niche_slug.is_(None))
                .scalar()
                or 0
            )

            # Per-game breakdown from node_path (extract game segment: "eSports.CS2" -> "CS2")
            game_rows = (
                session.query(TokenCatalog.node_path, func.count(TokenCatalog.token_id))
                .filter(TokenCatalog.niche_slug == "esports")
                .filter(TokenCatalog.node_path.isnot(None))
                .group_by(TokenCatalog.node_path)
                .all()
            )

            # Aggregate by game (first non-root path segment)
            game_counts: dict[str, int] = {}
            for node_path, count in game_rows:
                if node_path:
                    parts = node_path.split(".")
                    game = parts[1] if len(parts) >= 2 else node_path
                    game_counts[game] = game_counts.get(game, 0) + count

    # Display summary stats
    from rich.table import Table

    console.print(f"\n[bold]Token Catalog Statistics[/bold]")
    console.print(f"  Total rows:        [cyan]{total:,}[/cyan]")
    console.print(f"  Esports rows:      [green]{esports_total:,}[/green]")
    console.print(f"  Unclassified rows: [yellow]{unclassified:,}[/yellow]")

    if total == 0:
        console.print(
            "\n[dim]Catalog is empty. Run 'polymarket backfill' to auto-build it.[/dim]"
        )
        logger.info("CATALOG-STATS completed: catalog empty")
        return

    if game_counts:
        console.print("\n[bold]Esports Coverage by Game[/bold]")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Game", style="cyan", min_width=20)
        table.add_column("Token Rows", justify="right")

        for game, count in sorted(game_counts.items(), key=lambda x: -x[1]):
            table.add_row(game, f"{count:,}")

        console.print(table)

    logger.info(
        f"CATALOG-STATS completed: {total} total, {esports_total} esports, "
        f"{unclassified} unclassified, {len(game_counts)} games"
    )


@cli.command("build-index")
@click.option(
    "--batch-size",
    default=100,
    type=int,
    show_default=True,
    help="Parquet files per DuckDB query during build (~120MB per batch at default).",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def build_index(batch_size, verbose):
    """Build trader-to-file index for fast JBecker queries.

    Scans all parquet files once and records which files each trader appears in.
    After building, backfill queries scan only the relevant 5-50 files per trader
    instead of all 40,000 — eliminating the OOM issue on 8GB machines.

    Run this once before using 'polymarket backfill'. Takes ~20 minutes.

    \b
    Example:
        polymarket build-index
        polymarket build-index --batch-size 50   # more conservative for low RAM
    """
    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    import time
    from src.datasources.jbecker_index import TraderFileIndex
    from src.config.settings import get_settings

    console = Console()
    settings = get_settings()

    index = TraderFileIndex(settings.jbecker_data_path)

    if index.is_built:
        stats = index.stats()
        console.print(
            f"[yellow]Index already exists:[/yellow] "
            f"{stats['unique_traders']:,} traders, "
            f"{stats['unique_files']:,} files, "
            f"{stats['size_mb']}MB"
        )
        if not click.confirm("Rebuild from scratch?"):
            return
        index.index_path.unlink()

    console.print(
        f"[bold blue]Building JBecker trader index[/bold blue] "
        f"(batch_size={batch_size}, ~20 min)..."
    )
    console.print("[dim]Progress is logged to stderr. This runs once.[/dim]")

    start = time.time()
    try:
        total = index.build(batch_size=batch_size)
        elapsed = time.time() - start
        stats = index.stats()
        console.print(f"\n[bold green]Index built[/bold green] ({elapsed / 60:.1f}m)")
        console.print(f"  Traders indexed: [green]{stats['unique_traders']:,}[/green]")
        console.print(f"  Files covered:   [green]{stats['unique_files']:,}[/green]")
        console.print(f"  Total pairs:     [green]{total:,}[/green]")
        console.print(f"  Index size:      [green]{stats['size_mb']}MB[/green]")
        console.print(
            "\n[dim]Backfill will now scan only relevant files per trader.[/dim]"
        )
    except Exception as e:
        console.print(f"[red]Index build failed: {e}[/red]")
        logger.error(f"build-index failed: {e}")
        raise


@cli.command("reset-backfill")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def reset_backfill(confirm, verbose):
    """Clear JBecker trades and reset backfill status for re-ingestion.

    Deletes all JBecker-sourced trades from the database and marks affected
    traders as pending backfill (backfill_complete=False). Run this before
    re-running 'polymarket backfill' after a timestamp fix.

    \b
    Examples:
        polymarket reset-backfill
        polymarket reset-backfill --confirm
    """
    logger.info("RESET-BACKFILL command started")

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()

    session_factory, _, _, _, _ = _get_dependencies()

    with get_session(session_factory) as session:
        jbecker_count = (
            session.query(Trade).filter(Trade.trade_id.like("jbecker_%")).count()
        )

        if jbecker_count == 0:
            console.print("[green]No JBecker trades found — nothing to reset.[/green]")
            return

        console.print(
            f"[yellow]This will delete {jbecker_count:,} JBecker trades and reset backfill status.[/yellow]"
        )

        if not confirm and not click.confirm("Continue?"):
            console.print("[dim]Aborted.[/dim]")
            return

        affected_rows = (
            session.query(Trade.trader_address)
            .filter(Trade.trade_id.like("jbecker_%"))
            .distinct()
            .all()
        )
        affected_addresses = [row[0] for row in affected_rows]

        deleted = (
            session.query(Trade)
            .filter(Trade.trade_id.like("jbecker_%"))
            .delete(synchronize_session=False)
        )

        if affected_addresses:
            session.query(Trader).filter(Trader.address.in_(affected_addresses)).update(
                {"backfill_complete": False}, synchronize_session=False
            )

        session.commit()

    console.print(f"\n[bold green]Reset complete[/bold green]")
    console.print(f"  Trades deleted:   [red]{deleted:,}[/red]")
    console.print(f"  Traders reset:    [yellow]{len(affected_addresses)}[/yellow]")
    console.print(
        "\n[dim]Run 'polymarket backfill' to re-ingest with corrected timestamps.[/dim]"
    )
    logger.info(
        f"RESET-BACKFILL completed: {deleted} trades deleted, {len(affected_addresses)} traders reset"
    )


@cli.command("ingest-events")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def ingest_events(verbose):
    """Download and persist all closed eSports events from Gamma API.

    Downloads ~8,500 closed eSports events (tag_id=64) from
    gamma-api.polymarket.com/events and persists them to the local
    gamma_events table. Safe to re-run — existing events are updated
    in place (idempotent upsert).

    Takes ~30 seconds on first run. Subsequent runs refresh the data.
    """
    logger.info("INGEST-EVENTS command started")

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()

    try:
        settings = get_settings()
        session_factory, _, _, _, gamma_client = _get_dependencies(settings)

        console.print(
            "[bold]Downloading closed eSports events from Gamma API...[/bold]"
        )

        events = gamma_client.get_closed_esports_events()

        console.print(
            f"Downloaded [bold]{len(events)}[/bold] events. Persisting to database..."
        )

        with get_session(session_factory) as session:
            count = upsert_gamma_events(events, session)
            session.commit()

        console.print(
            f"[green]Done.[/green] {count} events upserted into gamma_events table."
        )
        logger.info(f"INGEST-EVENTS completed: {count} events upserted")

    except Exception as e:
        logger.error(f"ingest-events failed: {e}")
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)


@cli.command("resolve-outcomes")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def resolve_outcomes(verbose):
    """Populate markets.outcome for all resolved markets using Gamma event data.

    Reads gamma_events table (populated by ingest-events) and sets
    markets.outcome to 'YES' or 'NO' for each market whose token ID
    appears in a stored Gamma event.

    Resolution logic:
    - Parses clob_token_ids and outcome_prices from each gamma event
    - The token with price closest to 1.0 (and > 0.5) is the winner
    - Markets linked to the winning token get outcome='YES'
    - All other tokens in the event get outcome='NO'
    - Markets not linked to any gamma event remain outcome=NULL

    Safe to re-run — idempotent. Run after 'polymarket ingest-events'.

    Examples:
        polymarket resolve-outcomes
        polymarket resolve-outcomes --verbose
    """
    logger.info("RESOLVE-OUTCOMES command started")

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()

    try:
        settings = get_settings()
        session_factory, _, _, _, _ = _get_dependencies(settings)

        console.print("[bold]Resolving market outcomes from Gamma event data...[/bold]")

        with get_session(session_factory) as session:
            counts = resolve_market_outcomes(session)
            session.commit()

        resolved = counts["resolved"]
        markets_resolved = counts["markets_resolved"]
        skipped_events = counts["skipped_events"]
        skipped_tokens = counts["skipped_tokens"]

        console.print(
            f"[green]Done.[/green] {markets_resolved} markets resolved ({resolved} token updates)."
        )
        console.print(
            f"  Events skipped (no clear winner): [yellow]{skipped_events}[/yellow]"
        )
        console.print(
            f"  Tokens skipped (not in catalog):  [yellow]{skipped_tokens}[/yellow]"
        )
        logger.info(
            f"RESOLVE-OUTCOMES completed: {markets_resolved} markets resolved ({resolved} token updates), "
            f"{skipped_events} events skipped, {skipped_tokens} tokens skipped"
        )

    except Exception as e:
        logger.error(f"resolve-outcomes failed: {e}")
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)


@cli.command("resolve-positions")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def resolve_positions_cmd(verbose):
    """Populate Position.resolved, outcome, and pnl from resolved market outcomes.

    Reads positions table and joins with markets where markets.outcome is
    non-NULL (populated by resolve-outcomes). For each such position,
    computes win/loss/flat based on position direction and market result.

    Resolution logic:
    - LONG + YES market -> win (pnl = size * (1.0 - avg_entry_price))
    - LONG + NO market -> loss (pnl = size * (0.0 - avg_entry_price))
    - SHORT + NO market -> win
    - SHORT + YES market -> loss
    - FLAT positions -> flat, pnl=0
    - Already-resolved positions are skipped (idempotent)

    Safe to re-run. Run after 'polymarket resolve-outcomes'.

    Examples:
        polymarket resolve-positions
        polymarket resolve-positions --verbose
    """
    logger.info("RESOLVE-POSITIONS command started")

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()

    try:
        settings = get_settings()
        session_factory, _, _, _, _ = _get_dependencies(settings)

        console.print("[bold]Resolving positions from market outcomes...[/bold]")

        with get_session(session_factory) as session:
            counts = resolve_positions(session)
            session.commit()

        resolved = counts["resolved"]
        skipped_no_outcome = counts["skipped_no_outcome"]

        console.print(f"[green]Done.[/green] {resolved} positions resolved.")
        console.print(
            f"  Positions skipped (no market outcome): [yellow]{skipped_no_outcome}[/yellow]"
        )
        logger.info(
            f"RESOLVE-POSITIONS completed: {resolved} resolved, "
            f"{skipped_no_outcome} skipped"
        )

    except Exception as e:
        logger.error(f"resolve-positions failed: {e}")
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)


@cli.command("classify-tokens")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def classify_tokens(verbose):
    """Classify tokens in token_catalog using Gamma event tags.

    Reads gamma_events table (populated by ingest-events) and sets
    token_catalog.node_path and token_catalog.depth for each token
    linked to a Gamma event with sub-classification tags (game, tournament, team).

    node_path format: slash-separated lowercase slugs (e.g., 'esports/cs2' or
    'esports/cs2/iem-katowice-2024'). depth: 1=game, 2=tournament, 3=team.

    Only updates tokens where the new depth is greater than existing depth,
    preserving deeper classifications if run multiple times (idempotent).

    Safe to re-run. Run after 'polymarket ingest-events'.

    Examples:
        polymarket classify-tokens
        polymarket classify-tokens --verbose
    """
    logger.info("CLASSIFY-TOKENS command started")

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()

    try:
        settings = get_settings()
        session_factory, _, _, _, _ = _get_dependencies(settings)

        console.print("[bold]Classifying tokens from Gamma event tags...[/bold]")

        with get_session(session_factory) as session:
            result = classify_tokens_from_gamma_events(session)
            session.commit()

        token_update_attempts = result["token_update_attempts"]
        skipped_shallow = result["skipped_shallow"]
        skipped_no_tags = result["skipped_no_tags"]
        skipped_no_tokens = result["skipped_no_tokens"]

        console.print(
            f"[green]Done.[/green] {token_update_attempts} classification attempts"
            f" (actual DB updates may be lower on re-runs)."
        )
        console.print(
            f"  Events skipped (no sub-classification tags): [yellow]{skipped_shallow}[/yellow]"
        )
        console.print(
            f"  Events skipped (no tags):      [yellow]{skipped_no_tags}[/yellow]"
        )
        console.print(
            f"  Events skipped (no token IDs): [yellow]{skipped_no_tokens}[/yellow]"
        )
        logger.info(
            f"CLASSIFY-TOKENS completed: {token_update_attempts} classification attempts, "
            f"{skipped_shallow} shallow, {skipped_no_tags} no_tags, "
            f"{skipped_no_tokens} no_tokens"
        )

    except Exception as e:
        logger.error(f"classify-tokens failed: {e}")
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)


@cli.command("backfill-classifications")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def backfill_classifications_cmd(verbose):
    """Update MarketClassification.taxonomy_node_id for rows where node_path
    exists but taxonomy_node_id doesn't point to a game-level node.

    Fixes the classification at tournament/team level to point to the
    correct game-level node (e.g., "eSports.League of Legends.LCS.100 Thieves"
    should point to game node "esports.league of legends").

    Safe to re-run — skips rows that already have correct taxonomy_node_id.

    Examples:
        polymarket backfill-classifications
        polymarket backfill-classifications --verbose
    """
    logger.info("BACKFILL-CLASSIFICATIONS command started")

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()

    try:
        settings = get_settings()
        session_factory, _, _, _, _ = _get_dependencies(settings)

        console.print(
            "[bold]Backfilling MarketClassification taxonomy node IDs...[/bold]"
        )

        with get_session(session_factory) as session:
            result = backfill_market_classifications(session)
            session.commit()

        updated = result["updated"]
        skipped = result["skipped_no_match"]

        console.print(f"[green]Done.[/green] {updated} classifications updated.")
        console.print(f"  Skipped (no matching game node): [yellow]{skipped}[/yellow]")
        logger.info(
            f"BACKFILL-CLASSIFICATIONS completed: {updated} updated, {skipped} skipped"
        )

    except Exception as e:
        logger.error(f"backfill-classifications failed: {e}")
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)


if __name__ == "__main__":
    cli()
