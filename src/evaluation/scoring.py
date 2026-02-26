"""
Composite expertise scoring engine for trader evaluation.

This module combines win rate, concentration, recency, sample size, and consistency
into a single 0-100 expertise score per trader per game. Scores are percentile-normalized
against the population so they remain meaningful as traders join/leave.

Design principles:
- Pure functions, no classes or state
- Duck-typed inputs (pre-computed data, not ORM objects)
- All calculations use Decimal arithmetic
- No SQLAlchemy imports (keeps module pure and decoupled)

Scoring formula:
    raw_score = (win_rate * 0.40 + concentration * 0.25 + recency * 0.20 + sample_size * 0.15)
    raw_score *= consistency_multiplier (1.0 baseline, 1.05 bonus for consistent traders)
    final_score = clamp(raw_score, 0, 100)

Percentile normalization:
    Converts raw scores to 0-100 percentile ranks relative to the population.
    Percentile = rank / (n-1) * 100, where rank 0 = worst, rank n-1 = best.
"""

from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, UTC
from typing import Any
import math

from src.evaluation.metrics import calculate_win_rate
from src.evaluation.concentration import classify_specialization


# Constants
DEFAULT_WEIGHTS = {
    "win_rate": Decimal("0.40"),
    "concentration": Decimal("0.25"),
    "recency": Decimal("0.20"),
    "sample_size": Decimal("0.15"),
}

MIN_RESOLVED_MARKETS = 5
RECENCY_HALF_LIFE_DAYS = 90


@dataclass(frozen=True)
class ExpertiseScoreResult:
    """
    Immutable composite expertise score result.

    Attributes:
        raw_score: Decimal - Weighted composite score (0-100)
        percentile_rank: Decimal | None - Population-relative rank (0-100), None if not yet computed
        win_rate_component: Decimal - Win rate scaled 0-100 (before weighting)
        concentration_component: Decimal - Concentration scaled 0-100 (before weighting)
        recency_component: Decimal - Recency scaled 0-100 (before weighting)
        sample_size_component: Decimal - Sample size confidence scaled 0-100 (before weighting)
        consistency_multiplier: Decimal - 1.0-1.1 range (bonus-only, never below 1.0)
        specialization_label: str - "specialist/specialist", "specialist/generalist", etc.
        game_slug: str - Game identifier
        trader_address: str - Trader Ethereum address
        resolved_market_count: int - Number of resolved markets used in scoring
    """

    raw_score: Decimal
    percentile_rank: Decimal | None
    win_rate_component: Decimal
    concentration_component: Decimal
    recency_component: Decimal
    sample_size_component: Decimal
    consistency_multiplier: Decimal
    specialization_label: str
    game_slug: str
    trader_address: str
    resolved_market_count: int


def calculate_recency_weight(
    last_resolved_timestamp: datetime, now: datetime, half_life_days: int = 90
) -> Decimal:
    """
    Calculate exponential recency weight with configurable half-life.

    Applies exponential decay: weight = 0.5 ^ (days_since / half_life_days)

    Args:
        last_resolved_timestamp: Timestamp of last resolved market
        now: Current timestamp
        half_life_days: Number of days for weight to decay to 0.5 (default 90)

    Returns:
        Recency weight as Decimal (0-1). Returns Decimal("1.0") for same day or future.

    Examples:
        >>> now = datetime(2024, 6, 1)
        >>> last = now - timedelta(days=90)
        >>> calculate_recency_weight(last, now)
        Decimal('0.5')  # Approximately
    """
    # Calculate days since last resolved (strip timezone info to ensure both are naive)
    now_naive = now.replace(tzinfo=None) if now.tzinfo is not None else now
    last_naive = last_resolved_timestamp.replace(tzinfo=None) if last_resolved_timestamp.tzinfo is not None else last_resolved_timestamp
    days_since = (now_naive - last_naive).total_seconds() / 86400

    # Same day or future: full weight (< 1 day)
    if days_since < 1:
        return Decimal("1.0")

    # Exponential decay: 0.5 ^ (days_since / half_life_days)
    # Use math.log for calculation, then convert to Decimal
    exponent = days_since / half_life_days
    weight = math.pow(0.5, exponent)

    return Decimal(str(weight))


def calculate_sample_size_confidence(
    resolved_market_count: int,
    min_threshold: int = 5,
    full_confidence_threshold: int = 30,
) -> Decimal:
    """
    Calculate sample size confidence using exponential growth curve.

    Confidence increases from 0 at min_threshold to 1.0 at full_confidence_threshold.
    Uses exponential curve: 1 - exp(-k * (n - min_threshold))

    Args:
        resolved_market_count: Number of resolved markets
        min_threshold: Minimum markets for non-zero confidence (default 5)
        full_confidence_threshold: Markets for full confidence (default 30)

    Returns:
        Confidence as Decimal (0-1). Returns 0 below min_threshold, 1.0 at/above full confidence.

    Examples:
        >>> calculate_sample_size_confidence(3)
        Decimal('0')

        >>> calculate_sample_size_confidence(30)
        Decimal('1.0')
    """
    # Below minimum: zero confidence
    if resolved_market_count < min_threshold:
        return Decimal("0")

    # At or above full confidence: maximum confidence
    if resolved_market_count >= full_confidence_threshold:
        return Decimal("1.0")

    # Between thresholds: exponential growth curve
    # Formula: 1 - exp(-k * (n - min_threshold + 1))
    # Adding 1 ensures that at min_threshold we get a positive value
    # Tune k so confidence ~0.95 at full_confidence_threshold

    n = resolved_market_count - min_threshold + 1  # +1 to ensure positive at min
    range_size = full_confidence_threshold - min_threshold

    # k = -ln(0.05) / range_size ≈ 3.0 / range_size
    # This gives confidence ~0.95 at full_confidence_threshold
    k = 3.0 / range_size

    confidence = 1 - math.exp(-k * n)

    return Decimal(str(confidence))


def calculate_expertise_score(
    positions: list[Any],
    trader_address: str,
    game_slug: str,
    esports_concentration: Decimal,
    game_concentration: Decimal,
    consistency_score: Decimal,
    consistency_signal: str,
    weights: dict[str, Decimal] | None = None,
    now: datetime | None = None,
) -> ExpertiseScoreResult | None:
    """
    Calculate composite expertise score from all components.

    Combines win rate (~40%), concentration (~25%), recency (~20%), and sample size (~15%)
    into a weighted composite. Applies consistency multiplier (bonus-only) after weighting.

    Args:
        positions: List of position-like objects for this trader/game
        trader_address: Trader Ethereum address
        game_slug: Game identifier
        esports_concentration: Pre-computed eSports concentration (0-1)
        game_concentration: Pre-computed game concentration (0-1)
        consistency_score: Pre-computed consistency score (0-100)
        consistency_signal: Consistency signal ("stable", "streaky", "insufficient_data")
        weights: Optional custom weights (default: DEFAULT_WEIGHTS)
        now: Optional current timestamp (default: datetime.utcnow())

    Returns:
        ExpertiseScoreResult or None if below minimum sample size (< 5 resolved markets)

    Examples:
        >>> positions = [MockPosition(resolved=True, outcome="win") for _ in range(10)]
        >>> result = calculate_expertise_score(
        ...     positions, "0x123", "esports.cs2",
        ...     Decimal("0.8"), Decimal("0.7"), Decimal("85"), "stable"
        ... )
        >>> result.raw_score
        Decimal('82.5')  # Example
    """
    # Use provided weights or default
    if weights is None:
        weights = DEFAULT_WEIGHTS

    # Use provided now or current UTC time
    if now is None:
        now = datetime.now(UTC)

    # Filter resolved positions (exclude void)
    resolved_positions = [
        p for p in positions if p.resolved and p.outcome != "void"
    ]

    # Check minimum sample size
    if len(resolved_positions) < MIN_RESOLVED_MARKETS:
        return None

    # Component 1: Win rate
    win_rate_result = calculate_win_rate(resolved_positions)
    win_rate = win_rate_result["win_rate"]

    # If win_rate is None (no wins or losses), treat as 0
    if win_rate is None:
        win_rate_component = Decimal("0")
    else:
        win_rate_component = win_rate  # Already 0-100 scale

    # Component 2: Concentration
    # Game concentration is already 0-1, scale to 0-100
    concentration_component = game_concentration * Decimal("100")

    # Component 3: Recency
    # Find most recent resolved timestamp
    last_resolved_timestamp = max(
        p.last_trade_timestamp for p in resolved_positions
    )
    recency_weight = calculate_recency_weight(last_resolved_timestamp, now, RECENCY_HALF_LIFE_DAYS)
    recency_component = recency_weight * Decimal("100")

    # Component 4: Sample size confidence
    sample_size_confidence = calculate_sample_size_confidence(
        len(resolved_positions), MIN_RESOLVED_MARKETS, full_confidence_threshold=30
    )
    sample_size_component = sample_size_confidence * Decimal("100")

    # Calculate weighted composite
    raw_score = (
        win_rate_component * weights["win_rate"]
        + concentration_component * weights["concentration"]
        + recency_component * weights["recency"]
        + sample_size_component * weights["sample_size"]
    )

    # Apply consistency multiplier (bonus-only, never below 1.0)
    # Bonus: consistency_score >= 80 AND consistency_signal == "stable" -> 1.05x
    # All other cases: 1.0x (baseline, no penalty)
    if consistency_score >= Decimal("80") and consistency_signal == "stable":
        consistency_multiplier = Decimal("1.05")
    else:
        consistency_multiplier = Decimal("1.0")

    raw_score *= consistency_multiplier

    # Clamp to [0, 100]
    raw_score = max(Decimal("0"), min(Decimal("100"), raw_score))

    # Get specialization label
    specialization_profile = classify_specialization(
        esports_concentration, game_concentration, game_slug
    )
    specialization_label = f"{specialization_profile.esports_level}/{specialization_profile.game_level}"

    # Return result with percentile_rank = None (computed in batch later)
    return ExpertiseScoreResult(
        raw_score=raw_score,
        percentile_rank=None,
        win_rate_component=win_rate_component,
        concentration_component=concentration_component,
        recency_component=recency_component,
        sample_size_component=sample_size_component,
        consistency_multiplier=consistency_multiplier,
        specialization_label=specialization_label,
        game_slug=game_slug,
        trader_address=trader_address,
        resolved_market_count=len(resolved_positions),
    )


def normalize_scores_to_percentiles(raw_scores: dict[str, Decimal]) -> dict[str, Decimal]:
    """
    Normalize raw scores to percentile ranks (0-100) relative to the population.

    Percentile = rank / (n-1) * 100, where rank 0 = worst, rank n-1 = best.
    Handles ties by assigning same percentile to traders with same raw score.

    Args:
        raw_scores: Dict mapping trader_address to raw_score

    Returns:
        Dict mapping trader_address to percentile_rank (0-100)

    Examples:
        >>> scores = {"0x1": Decimal("50"), "0x2": Decimal("80"), "0x3": Decimal("90")}
        >>> normalize_scores_to_percentiles(scores)
        {'0x1': Decimal('0'), '0x2': Decimal('50'), '0x3': Decimal('100')}

        >>> scores = {"0x1": Decimal("70"), "0x2": Decimal("70")}
        >>> normalize_scores_to_percentiles(scores)
        {'0x1': Decimal('50'), '0x2': Decimal('50')}  # Tied
    """
    # Handle empty input
    if not raw_scores:
        return {}

    # Single trader: percentile = 100
    if len(raw_scores) == 1:
        trader = list(raw_scores.keys())[0]
        return {trader: Decimal("100")}

    # Sort traders by raw score (ascending)
    sorted_traders = sorted(raw_scores.items(), key=lambda x: x[1])

    # Build percentile mapping
    percentiles = {}
    n = len(sorted_traders)

    # Group by score to handle ties
    score_to_traders = {}
    for trader, score in sorted_traders:
        if score not in score_to_traders:
            score_to_traders[score] = []
        score_to_traders[score].append(trader)

    # Assign percentiles
    rank = 0
    for score in sorted(score_to_traders.keys()):
        traders_with_score = score_to_traders[score]

        # Calculate percentile for this rank
        # Percentile = rank / (n-1) * 100
        percentile = (Decimal(rank) / Decimal(n - 1)) * Decimal("100")

        # Assign same percentile to all tied traders
        for trader in traders_with_score:
            percentiles[trader] = percentile

        # Increment rank by number of tied traders
        rank += len(traders_with_score)

    return percentiles
