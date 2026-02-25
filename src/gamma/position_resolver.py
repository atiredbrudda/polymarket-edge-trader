"""Position resolution from resolved market outcomes.

Populates Position.resolved, outcome, and pnl fields based on
the market's resolved outcome (set by resolve-outcomes command).
"""

from decimal import Decimal

from loguru import logger
from sqlalchemy.orm import Session

from src.db.models import Market, Position


def resolve_positions(session: Session) -> dict[str, int]:
    """Populate Position.resolved, outcome, pnl for positions on resolved markets.

    Joins positions with markets where markets.outcome is non-NULL.
    For each unresolved position:
    - LONG + YES market -> win (pnl = size * (1.0 - avg_entry_price))
    - LONG + NO market -> loss (pnl = size * (0.0 - avg_entry_price))
    - SHORT + NO market -> win (pnl = size * (avg_entry_price - 0.0))
    - SHORT + YES market -> loss (pnl = size * (avg_entry_price - 1.0))
    - FLAT direction or size=0 -> flat, pnl=0
    - NULL avg_entry_price -> flat, pnl=0
    - market.outcome not in (YES, NO) -> void, pnl=0

    Caller must commit after calling this function.

    Returns:
        dict with keys:
            - resolved: count of positions resolved in this run
            - skipped_no_outcome: count of positions skipped due to NULL market outcome
            - skipped_already_resolved: count of positions already resolved (not re-processed)
    """
    resolved = 0
    skipped_no_outcome = 0
    skipped_already_resolved = 0

    # Query all unresolved positions first, then check their markets
    positions = session.query(Position).filter(Position.resolved == False).all()

    logger.info(f"Found {len(positions)} unresolved positions to process")

    for position in positions:
        # Get the market to check its outcome
        market = (
            session.query(Market)
            .filter_by(condition_id=position.market_id)
            .one_or_none()
        )

        # Skip if market not found or has no outcome
        if market is None or market.outcome is None:
            skipped_no_outcome += 1
            continue

        market_outcome = market.outcome

        # Handle VOID or other unexpected outcomes
        if market_outcome not in ("YES", "NO"):
            position.resolved = True
            position.outcome = "void"
            position.pnl = Decimal("0")
            resolved += 1
            continue

        # Handle FLAT positions or zero size
        if position.direction == "FLAT" or position.size == Decimal("0"):
            position.resolved = True
            position.outcome = "flat"
            position.pnl = Decimal("0")
            resolved += 1
            continue

        # Handle NULL avg_entry_price - cannot compute meaningful PnL
        if position.avg_entry_price is None:
            position.resolved = True
            position.outcome = "flat"
            position.pnl = Decimal("0")
            resolved += 1
            continue

        # Calculate resolution price: 1.0 for YES, 0.0 for NO
        resolution_price = Decimal("1.0") if market_outcome == "YES" else Decimal("0.0")

        # Calculate PnL based on direction
        if position.direction == "LONG":
            pnl = position.size * (resolution_price - position.avg_entry_price)
        elif position.direction == "SHORT":
            pnl = position.size * (position.avg_entry_price - resolution_price)
        else:
            # Should not reach here due to FLAT check above
            pnl = Decimal("0")

        # Determine outcome based on PnL
        if pnl > Decimal("0"):
            outcome = "win"
        elif pnl < Decimal("0"):
            outcome = "loss"
        else:
            outcome = "flat"

        # Update position
        position.resolved = True
        position.outcome = outcome
        position.pnl = pnl
        resolved += 1

    logger.info(
        f"Position resolution complete: {resolved} resolved, "
        f"{skipped_no_outcome} skipped (no market outcome), "
        f"{skipped_already_resolved} skipped (already resolved)"
    )

    return {
        "resolved": resolved,
        "skipped_no_outcome": skipped_no_outcome,
        "skipped_already_resolved": skipped_already_resolved,
    }
