"""Position resolution logic for computing PnL from market outcomes.

This module resolves unresolved positions by computing PnL based on markets.outcome
(YES/NO) with correct formulas for all 4 direction/outcome combinations.

PnL Formulas (GUIDE.md §"Position Calculation"):
- LONG + YES: size * (1.0 - entry) → WIN
- LONG + NO: size * (0.0 - entry) → LOSS
- SHORT + NO: size * entry → WIN
- SHORT + YES: size * (entry - 1.0) → LOSS
- FLAT: 0 → FLAT
"""

from decimal import Decimal
from typing import Any

import click


def calculate_pnl(
    direction: str, outcome: str, size: Decimal, avg_entry_price: Decimal
) -> Decimal:
    """Calculate PnL for a single position using pure Python.

    Pure Python implementation for testing PnL formulas in isolation.
    Uses Decimal arithmetic (not float) for precision.
    Formula matches SQL CASE expression exactly.

    Args:
        direction: Position direction (LONG, SHORT, FLAT)
        outcome: Market outcome (YES, NO)
        size: Position size (absolute value)
        avg_entry_price: Average entry price (0.0 to 1.0)

    Returns:
        PnL as Decimal (positive = profit, negative = loss)
    """
    if direction == "FLAT":
        return Decimal("0")

    if direction == "LONG":
        if outcome == "YES":
            # Won: receive 1.0 per share, paid entry price
            return size * (Decimal("1.0") - avg_entry_price)
        elif outcome == "NO":
            # Lost: receive 0.0 per share, paid entry price
            return size * (Decimal("0.0") - avg_entry_price)

    if direction == "SHORT":
        if outcome == "NO":
            # Won: keep entry price per share (bet correctly against YES)
            return size * avg_entry_price
        elif outcome == "YES":
            # Lost: pay out 1.0 per share, received entry price
            return size * (avg_entry_price - Decimal("1.0"))

    # Fallback for unexpected combinations
    return Decimal("0")


def resolve_position_pnl(db: Any, niche_slug: str) -> int:
    """Resolve positions and compute PnL using markets.outcome.

    Updates all unresolved positions where the market has a known outcome.
    Sets resolved=1, outcome (WIN/LOSS/FLAT), and pnl.

    Args:
        db: sqlite-utils Database instance
        niche_slug: Niche slug to scope resolution (e.g., "esports")

    Returns:
        Count of positions resolved

    Raises:
        click.ClickException: If dependencies missing (no outcomes, no positions)
    """
    # Dependency assertions - fail loudly if prerequisites missing

    # 1. Assert positions table has unresolved positions
    unresolved_count = db.execute(
        "SELECT COUNT(*) as cnt FROM positions WHERE resolved = 0"
    ).fetchone()[0]

    if unresolved_count == 0:
        raise click.ClickException(
            "No unresolved positions found. All positions already resolved."
        )

    # 2. Assert markets table has outcomes set
    markets_with_outcomes = db.execute(
        """
        SELECT COUNT(*) as cnt
        FROM markets
        WHERE outcome IS NOT NULL
        """
    ).fetchone()[0]

    if markets_with_outcomes == 0:
        raise click.ClickException(
            "No market outcomes found. Run resolve-outcomes command first."
        )

    # 3. Assert at least one position can be resolved (JOIN produces results)
    resolvable_count = db.execute(
        """
        SELECT COUNT(*) as cnt
        FROM positions p
        JOIN markets m ON m.condition_id = p.market_id
        WHERE m.outcome IS NOT NULL AND p.resolved = 0
        """
    ).fetchone()[0]

    if resolvable_count == 0:
        raise click.ClickException(
            "No positions have resolvable markets. Either all resolved or markets lack outcomes."
        )

    # Execute SQL UPDATE with CASE expression
    # Updates resolved, outcome, and pnl in a single query
    db.execute(
        """
        UPDATE positions
        SET
            resolved = 1,
            outcome = (
                SELECT CASE
                    WHEN positions.direction = 'LONG' AND m.outcome = 'YES' THEN 'WIN'
                    WHEN positions.direction = 'LONG' AND m.outcome = 'NO' THEN 'LOSS'
                    WHEN positions.direction = 'SHORT' AND m.outcome = 'NO' THEN 'WIN'
                    WHEN positions.direction = 'SHORT' AND m.outcome = 'YES' THEN 'LOSS'
                    WHEN positions.direction = 'FLAT' THEN 'FLAT'
                END
                FROM markets m
                WHERE m.condition_id = positions.market_id
            ),
            pnl = (
                SELECT CASE
                    WHEN positions.direction = 'LONG' AND m.outcome = 'YES' THEN
                        positions.size * (1.0 - positions.avg_entry_price)
                    WHEN positions.direction = 'LONG' AND m.outcome = 'NO' THEN
                        positions.size * (0.0 - positions.avg_entry_price)
                    WHEN positions.direction = 'SHORT' AND m.outcome = 'NO' THEN
                        positions.size * positions.avg_entry_price
                    WHEN positions.direction = 'SHORT' AND m.outcome = 'YES' THEN
                        positions.size * (positions.avg_entry_price - 1.0)
                    WHEN positions.direction = 'FLAT' THEN 0
                END
                FROM markets m
                WHERE m.condition_id = positions.market_id
            )
        WHERE EXISTS (
            SELECT 1
            FROM markets m
            WHERE m.condition_id = positions.market_id AND m.outcome IS NOT NULL
        )
        AND positions.resolved = 0
        """
    )

    # Commit the transaction to persist changes
    db.conn.commit()

    # Return count of positions resolved
    return resolvable_count
