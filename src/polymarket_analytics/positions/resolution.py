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
    direction: str,
    outcome: str,
    size: Decimal,
    avg_entry_price: Decimal,
    avg_exit_price: Decimal = None,
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
        avg_exit_price: Average exit price (optional, used for FLAT positions)

    Returns:
        PnL as Decimal (positive = profit, negative = loss)
    """
    if direction == "FLAT":
        if avg_exit_price is not None:
            return size * (avg_exit_price - avg_entry_price)
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

    # 2. Assert markets have outcomes (resolve-outcomes must be run first)
    outcomes_count = db.execute(
        "SELECT COUNT(*) FROM markets WHERE outcome IS NOT NULL"
    ).fetchone()[0]
    flat_resolvable = db.execute(
        "SELECT COUNT(*) FROM positions"
        " WHERE direction = 'FLAT' AND avg_exit_price IS NOT NULL AND resolved = 0"
    ).fetchone()[0]
    if outcomes_count == 0 and flat_resolvable == 0:
        raise click.ClickException(
            "No market outcomes found. "
            "Run resolve-outcomes command first, then re-run resolve-positions."
        )

    # VOID pass: close positions on markets that are resolved but have no outcome
    # (cancelled/postponed games — neither Gamma nor CLOB will ever supply an outcome).
    # pnl=0 (stake returned), excluded from scoring via m.outcome IS NOT NULL guard.
    void_result = db.execute(
        """
        UPDATE positions
        SET resolved = 1, outcome = 'VOID', pnl = 0
        WHERE resolved = 0
          AND EXISTS (
              SELECT 1 FROM markets m
              WHERE m.condition_id = positions.market_id
                AND (m.resolved = 1 OR m.active = 0)
                AND m.outcome IS NULL
          )
        """
    )
    void_count = void_result.rowcount

    # FLAT pass: resolve positions that were fully exited (avg_exit_price set)
    flat_result = db.execute(
        """
        UPDATE positions
        SET
            resolved = 1,
            outcome = CASE
                WHEN size * (avg_exit_price - avg_entry_price) > 0 THEN 'WIN'
                WHEN size * (avg_exit_price - avg_entry_price) < 0 THEN 'LOSS'
                ELSE 'FLAT'
            END,
            pnl = size * (avg_exit_price - avg_entry_price)
        WHERE direction = 'FLAT'
          AND avg_exit_price IS NOT NULL
          AND resolved = 0
        """
    )

    # Outcome pass: resolve positions where the market has a YES/NO outcome
    outcome_result = db.execute(
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

    total_resolved = void_count + flat_result.rowcount + outcome_result.rowcount
    if total_resolved == 0:
        raise click.ClickException(
            "No positions have resolvable markets. "
            "Remaining unresolved positions may need market outcomes — "
            "run resolve-outcomes to update market outcomes first."
        )
    return total_resolved
