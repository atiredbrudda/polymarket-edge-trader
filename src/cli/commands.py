"""Click command group and subcommands for Polymarket CLI.

Commands:
- markets: List active markets with optional category filter
- trader: Display trader profile by address
- signals: Show expert consensus signals
- leaderboard: Display game leaderboard rankings
- sweep: Run signal detection sweep

All commands delegate formatting to src.cli.formatters for clean separation.
"""

import sys
from decimal import Decimal

import click
from loguru import logger
from rich.console import Console
from sqlalchemy import select

from src.cli.formatters import (
    format_markets_table,
    format_trader_profile,
    format_signals_table,
    format_leaderboard_table,
    format_sweep_summary,
)
from src.db.models import Trader, TaxonomyNode, Market, MarketClassification
from src.db.session import get_session


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


@click.group()
def cli():
    """Polymarket Smart Money Tracker CLI.

    Track expert trader consensus and market signals in eSports prediction markets.
    """
    pass


@cli.command()
@click.option("--category", "-c", default=None, help="Filter by category (e.g., eSports)")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def markets(category, verbose):
    """List active markets with optional category filter.

    Example:
        polymarket markets
        polymarket markets --category eSports
    """
    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()

    with console.status("[bold green]Fetching markets...", spinner="dots"):
        session = get_session()

        # Import queries here to avoid circular imports
        from src.pipeline.queries import get_active_markets

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

        session.close()

    # Format and display
    table = format_markets_table(market_data)
    console.print(table)


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
    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()

    with console.status("[bold green]Fetching trader profile...", spinner="dots"):
        session = get_session()

        # Resolve partial address
        full_address = find_trader_by_prefix(session, address)
        if not full_address:
            session.close()
            return

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

        session.close()

    # Format and display
    profile = format_trader_profile(full_address, summaries_data, positions_data, scores_data)
    console.print(profile)


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
    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()

    with console.status("[bold green]Fetching signals...", spinner="dots"):
        session = get_session()

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

        session.close()

    # Format and display
    table = format_signals_table(signals_data)
    console.print(table)


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
    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()

    with console.status("[bold green]Fetching leaderboard...", spinner="dots"):
        session = get_session()

        # Validate game slug exists
        query = select(TaxonomyNode.slug).where(
            TaxonomyNode.slug.like("esports.%"), TaxonomyNode.node_type == "game"
        )
        result = session.execute(query)
        valid_games = result.scalars().all()

        if game_slug not in valid_games:
            session.close()
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

        session.close()

    # Format and display
    table = format_leaderboard_table(entries_data, game_slug)
    console.print(table)


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
    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    console = Console()

    with console.status("[bold green]Running sweep...", spinner="dots"):
        import time
        start_time = time.time()

        session = get_session()

        # Import pipeline here
        from src.signals.pipeline import refresh_all_signals

        # Run sweep
        results = refresh_all_signals(session, window_hours=window)

        processing_time = time.time() - start_time

        # Count markets and alerts (simplified - no actual alerting in sweep command)
        markets_count = len(set(r.market_id for r in results))
        signals_count = len(results)
        alerts_sent = 0  # Placeholder - sweep doesn't send alerts

        session.close()

    # Format and display
    summary = format_sweep_summary({
        "processing_time": processing_time,
        "markets_count": markets_count,
        "signals_count": signals_count,
        "alerts_sent": alerts_sent,
    })
    console.print(summary)


if __name__ == "__main__":
    cli()
