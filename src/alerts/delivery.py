"""Alert delivery orchestration with deduplication.

This module ties together signal detection, event classification, formatting,
and Telegram delivery into a complete end-to-end alert pipeline.

Pipeline flow:
1. Get ranked signals (from signal detection pipeline)
2. For each signal, detect event type (NEW/STRENGTHENING/WEAKENING/LOST)
3. Check deduplication cache (skip if duplicate within TTL)
4. Query market question from Market table
5. Query expert position details
6. Format alert message (HTML for Telegram)
7. Send via TelegramAlerter with retry logic
8. Log result (success or failure)
9. Continue on failure (don't block pipeline)

Design principles:
- In-memory TTL-based deduplication (no persistence needed)
- Failures logged but don't block subsequent alerts
- Returns list of AlertDeliveryResult for monitoring
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, UTC
from decimal import Decimal

from loguru import logger
from sqlalchemy.orm import Session

from src.db.models import Market
from src.signals.pipeline import get_ranked_signals
from src.alerts.detector import detect_signal_event
from src.alerts.formatter import format_signal_alert, get_expert_position_details
from src.alerts.telegram import TelegramAlerter


@dataclass(frozen=True)
class AlertDeliveryResult:
    """Result of a single alert delivery attempt.

    Attributes:
        success: Whether alert was sent successfully
        market_id: Market identifier
        direction: Signal direction
        event_type: Event type (NEW, STRENGTHENING, etc.)
        error: Error message if failed, None if succeeded
    """

    success: bool
    market_id: str
    direction: str
    event_type: str
    error: str | None = None


class AlertDeduplicator:
    """In-memory TTL-based alert deduplication.

    Prevents duplicate alerts for the same (market_id, direction, event_type, computed_at)
    within a TTL window. Cleans expired entries on each should_send call.

    Design:
    - Set-based storage for O(1) lookup
    - TTL cleanup on every call (no background thread needed)
    - Tuple key: (market_id, direction, event_type, computed_at)

    Args:
        ttl_minutes: Time-to-live in minutes for deduplication cache (default: 60)
    """

    def __init__(self, ttl_minutes: int = 60):
        """Initialize deduplicator with TTL configuration."""
        self.ttl_minutes = ttl_minutes
        self._cache: dict[tuple, datetime] = {}  # Key -> insertion timestamp

    def should_send(
        self, market_id: str, direction: str, event_type: str, computed_at: datetime
    ) -> bool:
        """Check if alert should be sent (not a duplicate within TTL).

        Cleans expired entries before checking.

        Args:
            market_id: Market identifier
            direction: Signal direction
            event_type: Event type (NEW, STRENGTHENING, etc.)
            computed_at: Signal computation timestamp

        Returns:
            True if alert should be sent, False if duplicate within TTL
        """
        # Clean expired entries first
        self._clean_expired()

        # Build key
        # Truncate computed_at to minute precision to avoid false negatives
        # from sub-second timestamp differences
        computed_at_min = computed_at.replace(second=0, microsecond=0)
        key = (market_id, direction, event_type, computed_at_min)

        # Check if exists
        if key in self._cache:
            logger.debug(f"Duplicate alert detected: {key}")
            return False

        # Add to cache with current timestamp
        self._cache[key] = datetime.now(UTC)
        return True

    def _clean_expired(self) -> None:
        """Remove expired entries from cache.

        Runs on every should_send call. This is efficient because:
        - Dictionary iteration is fast
        - Expected cache size is small (only active alerts within TTL)
        - Avoids complexity of background threads
        """
        now = datetime.now(UTC)
        cutoff = now - timedelta(minutes=self.ttl_minutes)

        # Build list of expired keys
        expired_keys = [key for key, timestamp in self._cache.items() if timestamp < cutoff]

        # Remove expired keys
        for key in expired_keys:
            del self._cache[key]

        if expired_keys:
            logger.debug(f"Cleaned {len(expired_keys)} expired deduplication entries")


def deliver_signal_alerts(
    session: Session,
    alerter: TelegramAlerter,
    deduplicator: AlertDeduplicator | None = None,
    window_hours: int = 24,
) -> list[AlertDeliveryResult]:
    """Deliver alerts for detected signal events.

    End-to-end pipeline:
    1. Get ranked signals from signal detection pipeline
    2. For each signal:
       a. Detect event type (compare to previous snapshot)
       b. Skip if no event or duplicate (via deduplicator)
       c. Query market question
       d. Query expert position details
       e. Format alert message
       f. Send via TelegramAlerter
       g. Log success or failure
       h. Continue on failure (don't block pipeline)
    3. Return list of results for monitoring

    Args:
        session: SQLAlchemy session
        alerter: TelegramAlerter instance for sending messages
        deduplicator: Optional AlertDeduplicator for preventing duplicates
        window_hours: Time window for signal query (default: 24)

    Returns:
        List of AlertDeliveryResult objects (one per alert attempt)

    Example:
        # Deliver alerts for signals in last 24 hours
        from src.config.settings import get_settings
        from src.alerts.telegram import TelegramAlerter

        settings = get_settings()
        alerter = TelegramAlerter.from_settings(settings)
        dedup = AlertDeduplicator(ttl_minutes=60)

        results = deliver_signal_alerts(session, alerter, dedup)
        successful = sum(1 for r in results if r.success)
        print(f"Delivered {successful}/{len(results)} alerts")
    """
    results = []

    # 1. Get ranked signals
    signals = get_ranked_signals(session, window_hours=window_hours, limit=100)

    logger.info(f"Processing {len(signals)} signals for alert delivery")

    # 2. Process each signal
    for signal in signals:
        # a. Detect event type
        event_type = detect_signal_event(session, signal.market_id, signal.direction)

        # Skip if no event
        if event_type is None:
            logger.debug(f"No event for {signal.market_id} {signal.direction}, skipping")
            continue

        # b. Check deduplication
        if deduplicator and not deduplicator.should_send(
            signal.market_id, signal.direction, event_type, signal.computed_at
        ):
            logger.info(
                f"Skipping duplicate alert: {signal.market_id} {signal.direction} {event_type}"
            )
            continue

        # c. Query market question
        market = session.query(Market).filter_by(condition_id=signal.market_id).first()
        if not market:
            logger.warning(f"Market not found for {signal.market_id}, skipping alert")
            results.append(
                AlertDeliveryResult(
                    success=False,
                    market_id=signal.market_id,
                    direction=signal.direction,
                    event_type=event_type,
                    error="Market not found",
                )
            )
            continue

        market_question = market.question

        # d. Query expert position details
        expert_positions = get_expert_position_details(
            session, signal.market_id, signal.expert_addresses
        )

        # e. Format alert message
        message = format_signal_alert(event_type, market_question, signal, expert_positions)

        # f. Send via TelegramAlerter (with retry logic)
        try:
            alerter.send(message)
            logger.info(
                f"Alert delivered: {event_type} for {signal.market_id} {signal.direction}"
            )
            results.append(
                AlertDeliveryResult(
                    success=True,
                    market_id=signal.market_id,
                    direction=signal.direction,
                    event_type=event_type,
                )
            )
        except Exception as e:
            # g. Log failure and continue (don't block pipeline)
            logger.error(
                f"Failed to deliver alert for {signal.market_id} {signal.direction}: {e}"
            )
            results.append(
                AlertDeliveryResult(
                    success=False,
                    market_id=signal.market_id,
                    direction=signal.direction,
                    event_type=event_type,
                    error=str(e),
                )
            )
            # Continue processing remaining alerts

    # 3. Log summary
    successful = sum(1 for r in results if r.success)
    logger.info(f"Alert delivery complete: {successful}/{len(results)} successful")

    return results
