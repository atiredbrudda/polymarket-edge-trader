"""Signal event detection via snapshot comparison.

Compares the latest SignalSnapshot to the previous snapshot for the same
market+direction pair and classifies the change as NEW, STRENGTHENING,
WEAKENING, or LOST based on confidence score deltas and status transitions.

Implements noise filtering with a 5-point confidence threshold to avoid
alerting on insignificant fluctuations.
"""

from decimal import Decimal

from loguru import logger
from sqlalchemy.orm import Session

from src.signals.queries import get_signal_history


# Confidence change threshold for noise filtering
CONFIDENCE_CHANGE_THRESHOLD = Decimal("5")


def detect_signal_event(
    session: Session,
    market_id: str,
    direction: str,
) -> str | None:
    """Detect signal event by comparing latest and previous snapshots.

    Retrieves the two most recent SignalSnapshot rows for the given
    market_id and direction, then classifies the change based on:
    - Status transitions (active/inactive)
    - Confidence score deltas (>= 5 point threshold)

    Event classification rules:
    - NEW: First snapshot is active, OR previous inactive and latest active
    - STRENGTHENING: Both active, confidence increased >= 5 points
    - WEAKENING: Both active, confidence decreased >= 5 points
    - LOST: Previous active, latest inactive
    - None: No significant change (confidence delta < 5 points), or no history

    Args:
        session: SQLAlchemy session
        market_id: Market condition_id
        direction: Signal direction ("LONG" or "SHORT")

    Returns:
        Event type string ("NEW", "STRENGTHENING", "WEAKENING", "LOST") or None

    Example:
        # Detect event for a market
        event = detect_signal_event(session, "0xMarket123", "LONG")
        if event == "NEW":
            send_alert(f"New {direction} signal detected")
        elif event == "STRENGTHENING":
            send_alert(f"{direction} signal strengthening")
    """
    # Get latest 2 snapshots (ordered by computed_at DESC)
    history = get_signal_history(session, market_id, direction=direction, limit=2)

    # Case: No history at all
    if len(history) == 0:
        logger.debug(f"No signal history for {market_id} {direction}")
        return None

    # Case: Single snapshot (first ever)
    if len(history) == 1:
        latest = history[0]
        if latest.status == "active":
            logger.debug(f"First active snapshot for {market_id} {direction} -> NEW")
            return "NEW"
        else:
            logger.debug(f"First snapshot is inactive for {market_id} {direction} -> None")
            return None

    # Case: Two or more snapshots - compare latest and previous
    latest = history[0]
    previous = history[1]

    # Status transition: inactive -> active (re-emergence)
    if previous.status == "inactive" and latest.status == "active":
        logger.debug(
            f"Signal re-emerged for {market_id} {direction}: "
            f"inactive -> active (confidence={latest.confidence_score}) -> NEW"
        )
        return "NEW"

    # Status transition: active -> inactive (signal lost)
    if previous.status == "active" and latest.status == "inactive":
        logger.debug(
            f"Signal lost for {market_id} {direction}: "
            f"active (confidence={previous.confidence_score}) -> inactive -> LOST"
        )
        return "LOST"

    # Both inactive -> no change
    if previous.status == "inactive" and latest.status == "inactive":
        logger.debug(f"Both snapshots inactive for {market_id} {direction} -> None")
        return None

    # Both active -> check confidence delta
    confidence_delta = latest.confidence_score - previous.confidence_score

    if confidence_delta >= CONFIDENCE_CHANGE_THRESHOLD:
        logger.debug(
            f"Signal strengthening for {market_id} {direction}: "
            f"{previous.confidence_score} -> {latest.confidence_score} "
            f"(delta={confidence_delta}) -> STRENGTHENING"
        )
        return "STRENGTHENING"
    elif confidence_delta <= -CONFIDENCE_CHANGE_THRESHOLD:
        logger.debug(
            f"Signal weakening for {market_id} {direction}: "
            f"{previous.confidence_score} -> {latest.confidence_score} "
            f"(delta={confidence_delta}) -> WEAKENING"
        )
        return "WEAKENING"
    else:
        logger.debug(
            f"Confidence change below threshold for {market_id} {direction}: "
            f"{previous.confidence_score} -> {latest.confidence_score} "
            f"(delta={confidence_delta}, threshold={CONFIDENCE_CHANGE_THRESHOLD}) -> None (noise)"
        )
        return None
