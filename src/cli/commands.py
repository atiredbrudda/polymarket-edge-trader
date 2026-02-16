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
from src.db.models import Base, Trader, TaxonomyNode, Market, MarketClassification
from src.db.session import get_session, get_session_factory
from src.config.settings import get_settings
from src.api.client import PolymarketClient
from src.api.gamma_client import GammaMarketClient
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
                    "specialization": "specialist" if s.is_specialist else "generalist",
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
                    "win_rate": entry.win_rate or Decimal("0"),
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
    "--window", "-w", default=24, help="Time window in hours for expert activity"
)
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
def sweep(window, niche, closing_within, verbose):
    """Run signal detection sweep.

    Refreshes all signals for markets with expert activity.

    Example:
        polymarket sweep
        polymarket sweep --window 6
        polymarket sweep --niche esports
        polymarket sweep --niche esports --niche crypto --closing-within 48h
    """
    logger.info(
        f"SWEEP command started (window={window}h, niches={niche}, closing_within={closing_within}, verbose={verbose})"
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

    with console.status("[bold green]Running sweep...", spinner="dots"):
        import time

        start_time = time.time()

        session_factory, client, category_filter, alerter, gamma_client = (
            _get_dependencies()
        )

        from src.cli.scheduler import run_sweep

        stats = run_sweep(
            session_factory,
            client,
            category_filter,
            alerter,
            skip_alerts=True,
            gamma_client=gamma_client,
            niches=niche,
            closing_within=closing_within,
            skip_trader_backfill=True,
        )

        processing_time = time.time() - start_time

    logger.info(
        f"Sweep completed: {stats['markets_ingested']} markets, {stats['signals_detected']} signals, {stats['alerts_sent']} alerts in {processing_time:.2f}s"
    )

    summary = format_sweep_summary(
        {
            "processing_time": processing_time,
            "markets_count": stats["markets_ingested"],
            "signals_count": stats["signals_detected"],
            "alerts_sent": stats["alerts_sent"],
        }
    )
    console.print(summary)
    logger.info("SWEEP command completed")


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

    Executes full sweep (ingest → score → detect → alert) at regular intervals.
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
            markets_orm = session.query(Market).filter_by(active=True).all()
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

    pipeline = IngestionPipeline(
        client, session_factory, category_filter, gamma_client=gamma_client
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

        with console.status(
            "[bold green]Backfilling traders...", spinner="dots"
        ) as status:
            for idx, addr in enumerate(trader_addresses, 1):
                status.update(
                    f"[bold green]Backfilling {idx}/{len(trader_addresses)}: {addr[:10]}..."
                )
                try:
                    pipeline.ingest_trader_history_hybrid(addr)
                    success_count += 1
                except Exception as e:
                    logger.warning(f"Backfill failed for {addr[:10]}...: {e}")
                    error_count += 1
                    continue

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

    with get_session(session_factory) as session:
        pending_count = session.query(Trader).filter_by(profile_resolved=False).count()

    if pending_count == 0:
        console.print("[green]No traders pending profile resolution.[/green]")
        logger.info("No traders pending profile resolution")
        return

    console.print(
        f"[bold blue]Resolving profiles...[/bold blue] {pending_count} traders pending"
    )

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

    total_resolved = limit if limit and limit < pending_count else pending_count
    no_profile_count = total_resolved - profiles_found

    console.print(
        f"\n[bold green]Profile resolution complete[/bold green] ({processing_time:.1f}s)"
    )
    console.print(f"  Found profiles:   [green]{profiles_found}[/green]")
    console.print(f"  No profile:      [yellow]{no_profile_count}[/yellow]")
    logger.info(
        f"RESOLVE-PROFILES completed: {profiles_found} profiles, {no_profile_count} no profile ({processing_time:.1f}s)"
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


if __name__ == "__main__":
    cli()
