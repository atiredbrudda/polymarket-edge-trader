"""Sweep orchestration and polling loop for automated signal detection.

This module connects all pipeline stages into a single "sweep" operation:
1. Ingest active markets
2. Compute expertise scores
3. Detect expert consensus signals
4. Deliver alerts (optional)

run_sweep: Single full pipeline pass with stats
run_polling_loop: Repeating sweep with graceful shutdown

Design principles:
- Each stage wrapped in try/except - failures logged, don't block subsequent stages
- Graceful SIGINT/SIGTERM shutdown with flag-based loop control
- Dense one-line cycle logging for operational monitoring
"""

import signal
import time
import random
from pathlib import Path
from datetime import datetime, UTC
from decimal import Decimal

from loguru import logger
from sqlalchemy.orm import sessionmaker

from src.api.client import PolymarketClient
from src.pipeline.filters import CategoryFilter
from src.pipeline.ingest import IngestionPipeline
from src.pipeline.scoring_pipeline import compute_all_game_scores
from src.signals.pipeline import refresh_all_signals
from src.alerts.delivery import deliver_signal_alerts
from src.alerts.telegram import TelegramAlerter
from src.db.models import Market, Trade, ExpertiseScore


def _generate_sweep_debug_report(session_factory: sessionmaker, stats: dict) -> None:
    """Generate debug report after sweep for testing/monitoring.

    Creates logs/last_sweep_debug.md with:
    - Markets scanned
    - List of traders involved
    - Random 3 traders with their trade history and scores

    Args:
        session_factory: SQLAlchemy session factory
        stats: Stats dict from run_sweep
    """
    try:
        with session_factory() as session:
            # Get recent markets
            markets = session.query(Market).order_by(Market.id.desc()).limit(10).all()

            # Get all traders with trades (from last sweep)
            traders_with_trades = (
                session.query(Trade.trader_address)
                .distinct()
                .order_by(Trade.id.desc())
                .limit(100)
                .all()
            )
            trader_addresses = [t[0] for t in traders_with_trades]

            # Pick random 3 traders
            sample_size = min(3, len(trader_addresses))
            sample_traders = random.sample(trader_addresses, sample_size) if trader_addresses else []

            # Build report
            report_lines = [
                "# Sweep Debug Report",
                f"**Generated:** {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}",
                "",
                "## Sweep Summary",
                f"- Markets ingested: {stats.get('markets_ingested', 0)}",
                f"- Traders discovered: {stats.get('traders_discovered', 0)}",
                f"- Scores computed: {stats.get('scores_computed', 0)}",
                f"- Signals detected: {stats.get('signals_detected', 0)}",
                f"- Duration: {stats.get('duration_seconds', 0):.1f}s",
                "",
                "## Recent Markets Scanned",
            ]

            if markets:
                for market in markets[:5]:
                    report_lines.append(f"- **{market.question}**")
                    report_lines.append(f"  - Condition ID: `{market.condition_id}`")
                    report_lines.append(f"  - Category: {market.category or 'N/A'}")
                    report_lines.append("")
            else:
                report_lines.append("- No markets found")
                report_lines.append("")

            report_lines.extend([
                f"## All Traders Involved ({len(trader_addresses)} total)",
                "",
            ])

            # Show first 20 traders
            for addr in trader_addresses[:20]:
                report_lines.append(f"- `{addr}`")
            if len(trader_addresses) > 20:
                report_lines.append(f"- ... and {len(trader_addresses) - 20} more")
            report_lines.append("")

            # Detail for sample traders
            report_lines.extend([
                f"## Sample Traders Detail (Random {sample_size})",
                "",
            ])

            for addr in sample_traders:
                report_lines.append(f"### Trader: `{addr}`")
                report_lines.append("")

                # Get recent trades
                trades = (
                    session.query(Trade)
                    .filter(Trade.trader_address == addr)
                    .order_by(Trade.timestamp.desc())
                    .limit(10)
                    .all()
                )

                report_lines.append(f"**Recent Trades ({len(trades)} shown):**")
                report_lines.append("")
                for trade in trades:
                    report_lines.append(
                        f"- {trade.timestamp.strftime('%Y-%m-%d %H:%M')} | "
                        f"{trade.side} | Size: {trade.size} | Price: {trade.price}"
                    )
                report_lines.append("")

                # Get expertise scores
                scores = (
                    session.query(ExpertiseScore)
                    .filter(ExpertiseScore.trader_address == addr)
                    .order_by(ExpertiseScore.computed_at.desc())
                    .limit(5)
                    .all()
                )

                if scores:
                    report_lines.append("**Expertise Scores:**")
                    report_lines.append("")
                    for score in scores:
                        report_lines.append(
                            f"- Category: `{score.category_slug}` | "
                            f"Raw Score: {score.raw_score:.1f} | "
                            f"Percentile: {score.percentile_rank or 'N/A'} | "
                            f"Win Rate: {score.win_rate:.2f}"
                        )
                else:
                    report_lines.append("**Expertise Scores:** None computed yet")

                report_lines.append("")
                report_lines.append("---")
                report_lines.append("")

            # Write to file
            report_path = Path("logs/last_sweep_debug.md")
            report_path.parent.mkdir(exist_ok=True)
            report_path.write_text("\n".join(report_lines))

            logger.info(f"Debug report written to {report_path}")

    except Exception as e:
        logger.error(f"Failed to generate debug report: {e}")


def run_sweep(
    session_factory: sessionmaker,
    client: PolymarketClient,
    category_filter: CategoryFilter,
    alerter: TelegramAlerter | None = None,
    skip_alerts: bool = False,
) -> dict:
    """Execute single full pipeline sweep.

    Pipeline stages:
    1. Ingest active markets (IngestionPipeline.run_full_sweep)
    2. Compute expertise scores (compute_all_game_scores)
    3. Detect signals (refresh_all_signals)
    4. Deliver alerts (deliver_signal_alerts) [optional]

    Each stage wrapped in try/except - failure logs error and continues.

    Args:
        session_factory: SQLAlchemy session factory
        client: PolymarketClient for API data fetching
        category_filter: CategoryFilter for trade routing
        alerter: Optional TelegramAlerter for alert delivery
        skip_alerts: If True, skip alert delivery even if alerter provided

    Returns:
        Stats dict with keys:
        - markets_ingested: Count of markets processed
        - traders_discovered: Count of new traders found
        - scores_computed: Count of leaderboard entries computed
        - signals_detected: Count of signals detected
        - alerts_sent: Count of alerts delivered successfully
        - alerts_failed: Count of alerts that failed to deliver
        - duration_seconds: Total sweep duration

    Example:
        from src.db.session import get_session_factory
        from src.config.settings import get_settings
        from src.api.client import PolymarketClient
        from src.pipeline.filters import CategoryFilter

        settings = get_settings()
        session_factory = get_session_factory()
        client = PolymarketClient(settings.polymarket_api_host)
        category_filter = CategoryFilter(settings.detail_categories)

        stats = run_sweep(session_factory, client, category_filter)
        print(f"Processed {stats['markets_ingested']} markets, detected {stats['signals_detected']} signals")
    """
    start_time = time.time()
    stats = {
        "markets_ingested": 0,
        "traders_discovered": 0,
        "scores_computed": 0,
        "signals_detected": 0,
        "alerts_sent": 0,
        "alerts_failed": 0,
        "duration_seconds": 0,
    }

    logger.info("Starting sweep")

    # Stage 1: Ingest active markets
    try:
        logger.info("Stage 1/4: Ingesting markets")
        pipeline = IngestionPipeline(client, session_factory, category_filter)
        ingest_stats = pipeline.run_full_sweep()
        stats["markets_ingested"] = ingest_stats.get("markets_ingested", 0)
        stats["traders_discovered"] = ingest_stats.get("traders_discovered", 0)
        logger.info(f"Ingestion complete: {stats['markets_ingested']} markets, {stats['traders_discovered']} traders")
    except Exception as e:
        logger.error(f"Ingestion stage failed: {e}")

    # Stage 2: Compute expertise scores
    try:
        logger.info("Stage 2/4: Computing expertise scores")
        with session_factory() as session:
            leaderboards = compute_all_game_scores(session)
            session.commit()
            # Count total leaderboard entries across all games
            stats["scores_computed"] = sum(len(entries) for entries in leaderboards.values())
        logger.info(f"Scoring complete: {stats['scores_computed']} scores computed across {len(leaderboards)} games")
    except Exception as e:
        logger.error(f"Scoring stage failed: {e}")

    # Stage 3: Detect signals
    try:
        logger.info("Stage 3/4: Detecting signals")
        with session_factory() as session:
            signals = refresh_all_signals(session)
            session.commit()
            stats["signals_detected"] = len(signals)
        logger.info(f"Signal detection complete: {stats['signals_detected']} signals")
    except Exception as e:
        logger.error(f"Signal detection stage failed: {e}")

    # Stage 4: Deliver alerts (optional)
    if alerter and not skip_alerts:
        try:
            logger.info("Stage 4/4: Delivering alerts")
            with session_factory() as session:
                results = deliver_signal_alerts(session, alerter)
                session.commit()
                stats["alerts_sent"] = sum(1 for r in results if r.success)
                stats["alerts_failed"] = sum(1 for r in results if not r.success)
            logger.info(f"Alert delivery complete: {stats['alerts_sent']} sent, {stats['alerts_failed']} failed")
        except Exception as e:
            logger.error(f"Alert delivery stage failed: {e}")
    else:
        logger.info("Stage 4/4: Skipping alerts (alerter not configured or skip_alerts=True)")

    # Calculate duration
    stats["duration_seconds"] = time.time() - start_time

    logger.info(f"Sweep complete in {stats['duration_seconds']:.1f}s")

    # Generate debug report for testing/monitoring
    _generate_sweep_debug_report(session_factory, stats)

    return stats


# Global shutdown flag for signal handling
_shutdown_flag = False


def _signal_handler(signum, frame):
    """Handle SIGINT and SIGTERM by setting shutdown flag."""
    global _shutdown_flag
    logger.info(f"Received signal {signum}, initiating graceful shutdown")
    _shutdown_flag = True


def run_polling_loop(
    session_factory: sessionmaker,
    client: PolymarketClient,
    category_filter: CategoryFilter,
    alerter: TelegramAlerter | None = None,
    interval_minutes: int = 60,
) -> None:
    """Run polling loop with graceful shutdown handling.

    Loop behavior:
    1. Register SIGINT/SIGTERM handlers
    2. While not shutdown:
       a. Run sweep (call run_sweep)
       b. Log dense one-line summary
       c. Sleep for interval_minutes (check shutdown flag periodically)
    3. Log "Polling stopped gracefully"

    Graceful sleep: Break sleep into 1-second intervals, checking shutdown flag each iteration.

    Args:
        session_factory: SQLAlchemy session factory
        client: PolymarketClient for API data fetching
        category_filter: CategoryFilter for trade routing
        alerter: Optional TelegramAlerter for alert delivery
        interval_minutes: Polling interval in minutes (default: 60)

    Example:
        from src.db.session import get_session_factory
        from src.config.settings import get_settings
        from src.api.client import PolymarketClient
        from src.pipeline.filters import CategoryFilter

        settings = get_settings()
        session_factory = get_session_factory()
        client = PolymarketClient(settings.polymarket_api_host)
        category_filter = CategoryFilter(settings.detail_categories)

        # Run until SIGINT (Ctrl+C)
        run_polling_loop(session_factory, client, category_filter, interval_minutes=60)
    """
    global _shutdown_flag

    # Register signal handlers
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    logger.info(f"Starting polling loop (interval: {interval_minutes} minutes)")

    cycle_count = 0

    while not _shutdown_flag:
        cycle_count += 1
        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

        # Run sweep
        stats = run_sweep(session_factory, client, category_filter, alerter)

        # Log dense one-line summary
        logger.info(
            f"[{timestamp}] Cycle {cycle_count}: "
            f"{stats['markets_ingested']} mkts, "
            f"{stats['signals_detected']} sigs, "
            f"{stats['alerts_sent']} alerts "
            f"({stats['duration_seconds']:.1f}s)"
        )

        # Graceful sleep with shutdown check every second
        if not _shutdown_flag:
            logger.info(f"Sleeping for {interval_minutes} minutes until next cycle")
            sleep_seconds = interval_minutes * 60
            for _ in range(sleep_seconds):
                if _shutdown_flag:
                    break
                time.sleep(1)

    logger.info("Polling stopped gracefully")
