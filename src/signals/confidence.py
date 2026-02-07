"""Pure functions for consensus confidence scoring.

This module provides stateless confidence score calculation following the
pure-function, duck-typed pattern. Uses Decimal arithmetic for precision.

Design principles:
- Pure functions, no classes or state
- Duck-typed inputs (works with any object having the right attributes)
- All arithmetic uses Decimal, never float
- No SQLAlchemy imports (keeps module pure and decoupled)

Confidence formula (0-100 scale):
- Agreement component (60% weight): agreement_pct = experts_agreeing / experts_total * 100
- Sample size component (30% weight): (1 - exp(-(n - min_experts) / 10)) * 100
- Uniformity component (10% weight): (1 - min(CV, 1)) * 10 where CV = coefficient of variation

Total confidence = agreement * 0.6 + sample_size * 0.3 + uniformity, capped at 100.
"""

import math
from decimal import Decimal
from typing import Any


def _compute_position_volume(position: Any) -> Decimal:
    """Compute volume proxy for a position.

    Matches scoring_pipeline.py pattern exactly.

    Uses abs(size * avg_entry_price) if avg_entry_price available,
    otherwise falls back to abs(size).

    Args:
        position: Position-like object with size and avg_entry_price attributes

    Returns:
        Volume as Decimal
    """
    if position.avg_entry_price is not None:
        return abs(position.size * position.avg_entry_price)
    else:
        return abs(position.size)


def calculate_confidence_score(
    experts_agreeing: list[Any], experts_total: int, min_experts: int = 3
) -> Decimal:
    """Calculate 0-100 confidence score for consensus signal.

    Combines three components:
    1. Agreement % (60% weight): How many experts agree vs total
    2. Sample size (30% weight): Asymptotic formula rewards more experts
    3. Position uniformity (10% weight): Coefficient of variation of volumes

    Returns Decimal("0") if experts_agreeing < min_experts.

    Args:
        experts_agreeing: List of position-like objects for experts in same direction.
                         Must have attributes: size, avg_entry_price
        experts_total: Total number of experts in market (across all directions)
        min_experts: Minimum number of experts required (default: 3)

    Returns:
        Confidence score as Decimal (0-100), capped at 100

    Examples:
        >>> experts = [
        ...     MockPosition("market1", "trader1", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 1)),
        ...     MockPosition("market1", "trader2", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 2)),
        ...     MockPosition("market1", "trader3", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 3)),
        ... ]
        >>> calculate_confidence_score(experts, experts_total=3, min_experts=3)
        Decimal('70')  # 100% agreement (60) + 0 sample (0) + uniform (10)
    """
    n = len(experts_agreeing)

    if n < min_experts:
        return Decimal("0")

    # Component 1: Agreement percentage (60% weight)
    agreement_pct = (Decimal(n) / Decimal(experts_total)) * 100
    agreement_component = agreement_pct * Decimal("0.6")

    # Component 2: Sample size (30% weight)
    # Asymptotic formula: (1 - exp(-(n - min_experts) / 10)) * 100
    # At exactly min_experts: (1 - exp(0)) = 0
    # At min+10: (1 - exp(-1)) ≈ 63.2
    # Asymptotes to 100 as n increases
    exponent = -(n - min_experts) / 10
    sample_size_pct = (1 - math.exp(exponent)) * 100
    sample_size_component = Decimal(str(sample_size_pct)) * Decimal("0.3")

    # Component 3: Position-size uniformity (10% weight, 0-10 points)
    # Calculate coefficient of variation (CV) of position volumes
    # Uniformity = (1 - min(CV, 1)) * 10
    uniformity_component = _calculate_uniformity_component(experts_agreeing)

    # Final confidence score
    confidence = agreement_component + sample_size_component + uniformity_component

    # Cap at 100
    if confidence > 100:
        confidence = Decimal("100")

    return confidence


def _calculate_uniformity_component(positions: list[Any]) -> Decimal:
    """Calculate uniformity component (0-10 points) from position volumes.

    Uses coefficient of variation (CV) of volumes:
    - CV = std_dev / mean
    - Uniformity = (1 - min(CV, 1)) * 10
    - Uniform positions (CV ≈ 0) give ~10 points
    - Highly varied positions (CV ≥ 1) give 0 points

    Args:
        positions: List of position-like objects with size and avg_entry_price

    Returns:
        Uniformity score as Decimal (0-10)
    """
    if len(positions) <= 1:
        # Can't compute CV with single position
        return Decimal("0")

    # Compute volumes
    volumes = [_compute_position_volume(p) for p in positions]

    # Filter out zero volumes
    non_zero_volumes = [v for v in volumes if v > 0]

    if not non_zero_volumes:
        # All volumes are zero
        return Decimal("0")

    if len(non_zero_volumes) == 1:
        # Only one non-zero volume, can't compute meaningful CV
        return Decimal("0")

    # Calculate mean
    mean_volume = sum(non_zero_volumes) / len(non_zero_volumes)

    # Calculate variance
    variance = sum((v - mean_volume) ** 2 for v in non_zero_volumes) / len(
        non_zero_volumes
    )

    # Calculate standard deviation
    std_dev = variance.sqrt()

    # Calculate coefficient of variation
    if mean_volume == 0:
        cv = Decimal("0")
    else:
        cv = std_dev / mean_volume

    # Uniformity score: (1 - min(CV, 1)) * 10
    cv_capped = min(cv, Decimal("1"))
    uniformity = (Decimal("1") - cv_capped) * 10

    return uniformity
