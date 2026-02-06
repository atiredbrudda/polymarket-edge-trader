"""
Consistency detection for trader performance analysis.

Pure functions for detecting genuine experts vs lucky streaks via:
1. Cross-timeframe stability (primary signal)
2. Streak length analysis (secondary signal)

Design principles:
- Pure functions, no classes or state
- Duck-typed inputs (works with any position-like objects)
- All calculations use Decimal arithmetic
- No SQLAlchemy imports (keeps module pure and decoupled)

Consistency signals:
- stable: Win rates consistent across timeframes (< variance threshold)
- streaky: Win rates divergent across timeframes (>= variance threshold)
- insufficient_data: Fewer than 2 qualifying windows or all low-confidence
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
import statistics

from src.evaluation.metrics import calculate_win_rate
from src.evaluation.profiles import get_profile_consistency_bar


@dataclass(frozen=True)
class ConsistencyResult:
    """
    Immutable consistency analysis result.

    Attributes:
        is_consistent: bool - Overall consistency determination
        consistency_score: Decimal - 0-100, higher = more consistent
        primary_signal: str - "stable", "streaky", or "insufficient_data"
        secondary_signal: str | None - "alternating", "clustered", or None
        timeframe_win_rates: dict[str, Decimal | None] - Win rate per window
        win_rate_variance: Decimal | None - Variance across qualifying windows
        low_confidence_windows: list[str] - Windows with < sparse_threshold resolved
        profile_type: str - "selective" or "active"
    """
    is_consistent: bool
    consistency_score: Decimal
    primary_signal: str
    secondary_signal: str | None
    timeframe_win_rates: dict[str, Decimal | None]
    win_rate_variance: Decimal | None
    low_confidence_windows: list[str]
    profile_type: str


def calculate_consistency(
    positions_by_timeframe: dict[str, list[Any]],
    profile_type: str,
    sparse_threshold: int = 5,
) -> ConsistencyResult:
    """
    Calculate consistency via cross-timeframe stability analysis.

    Primary signal: Compares win rates across 30d/90d/all-time windows.
    Excludes 7d window from consistency calculation (too noisy).
    Windows with < sparse_threshold resolved markets are flagged as low-confidence.

    Args:
        positions_by_timeframe: Dict mapping timeframe keys to position lists
        profile_type: "selective" or "active" (determines variance threshold)
        sparse_threshold: Minimum resolved markets for confidence (default 5)

    Returns:
        ConsistencyResult with full analysis

    Examples:
        >>> # Stable trader: 65%, 68%, 70% win rates
        >>> result = calculate_consistency(positions_by_timeframe, "selective")
        >>> result.primary_signal
        'stable'

        >>> # Streaky trader: 90%, 45%, 60% win rates
        >>> result = calculate_consistency(positions_by_timeframe, "active")
        >>> result.primary_signal
        'streaky'
    """
    # Get consistency bar for profile type
    consistency_bar = get_profile_consistency_bar(profile_type)
    max_variance = consistency_bar["max_variance"]
    min_timeframes = consistency_bar["min_timeframes"]

    # Calculate win rate for each timeframe (excluding 7d completely)
    # 7d is too noisy for consistency analysis and not included in results
    consistency_windows = ["30d", "90d", "all"]  # Only these used for consistency

    timeframe_win_rates = {}
    low_confidence_windows = []
    qualifying_win_rates = []

    for window in consistency_windows:
        positions = positions_by_timeframe.get(window, [])

        # Calculate win rate
        win_rate_result = calculate_win_rate(positions)
        win_rate = win_rate_result["win_rate"]
        timeframe_win_rates[window] = win_rate

        # Count resolved non-void positions for confidence check
        resolved_count = win_rate_result["total"]

        # Check if window qualifies for consistency analysis
        if resolved_count < sparse_threshold:
            low_confidence_windows.append(window)
        elif win_rate is not None:
            # Add to qualifying list
            qualifying_win_rates.append(win_rate)

    # Determine consistency based on qualifying windows
    if len(qualifying_win_rates) < min_timeframes:
        # Insufficient data
        return ConsistencyResult(
            is_consistent=False,
            consistency_score=Decimal("0"),
            primary_signal="insufficient_data",
            secondary_signal=None,
            timeframe_win_rates=timeframe_win_rates,
            win_rate_variance=None,
            low_confidence_windows=low_confidence_windows,
            profile_type=profile_type,
        )

    # Calculate variance across qualifying win rates
    # Convert Decimal to float for statistics.variance, then back to Decimal
    win_rates_float = [float(wr) for wr in qualifying_win_rates]
    variance = Decimal(str(statistics.variance(win_rates_float)))

    # Determine primary signal based on variance vs threshold
    if variance < max_variance:
        primary_signal = "stable"
        is_consistent = True
    else:
        primary_signal = "streaky"
        is_consistent = False

    # Calculate consistency score: 100 - (variance * weight_factor)
    # Higher variance = lower score
    # Use weight factor of 1 for simplicity (can tune later)
    consistency_score = Decimal("100") - variance
    consistency_score = max(Decimal("0"), min(Decimal("100"), consistency_score))

    return ConsistencyResult(
        is_consistent=is_consistent,
        consistency_score=consistency_score,
        primary_signal=primary_signal,
        secondary_signal=None,  # Not used in this function
        timeframe_win_rates=timeframe_win_rates,
        win_rate_variance=variance,
        low_confidence_windows=low_confidence_windows,
        profile_type=profile_type,
    )


def analyze_streaks(outcomes: list[str]) -> dict[str, int | Decimal | str]:
    """
    Analyze streak patterns in trading outcomes (secondary consistency signal).

    Calculates max streaks, average streak length, and alternation rate.
    Higher alternation rate indicates more consistent performance.

    Args:
        outcomes: Chronologically ordered list of outcomes ("win", "loss", "void", "flat")

    Returns:
        Dictionary with:
            - max_win_streak: int
            - max_loss_streak: int
            - avg_streak_length: Decimal
            - alternation_rate: Decimal (transitions / total, 0-1)
            - signal: str ("alternating" if >= 0.4, "clustered" otherwise)

    Examples:
        >>> analyze_streaks(["win", "loss", "win", "loss"])
        {'max_win_streak': 1, 'max_loss_streak': 1, 'alternation_rate': Decimal('1.0'), 'signal': 'alternating'}

        >>> analyze_streaks(["win", "win", "win", "loss", "loss", "loss"])
        {'max_win_streak': 3, 'max_loss_streak': 3, 'alternation_rate': Decimal('0.2'), 'signal': 'clustered'}
    """
    # Filter out void and flat outcomes
    valid_outcomes = [o for o in outcomes if o not in ("void", "flat")]

    # Handle empty or single outcome
    if len(valid_outcomes) == 0:
        return {
            "max_win_streak": 0,
            "max_loss_streak": 0,
            "avg_streak_length": Decimal("0"),
            "alternation_rate": Decimal("0"),
            "signal": "alternating",  # No streak evidence
        }

    if len(valid_outcomes) == 1:
        is_win = valid_outcomes[0] == "win"
        return {
            "max_win_streak": 1 if is_win else 0,
            "max_loss_streak": 0 if is_win else 1,
            "avg_streak_length": Decimal("1"),
            "alternation_rate": Decimal("0"),
            "signal": "alternating",  # No alternation evidence
        }

    # Track streaks
    max_win_streak = 0
    max_loss_streak = 0
    current_streak_length = 1
    current_streak_type = valid_outcomes[0]
    streak_lengths = []
    transition_count = 0

    for i in range(1, len(valid_outcomes)):
        outcome = valid_outcomes[i]

        if outcome == current_streak_type:
            # Continue current streak
            current_streak_length += 1
        else:
            # Streak ended, record it
            streak_lengths.append(current_streak_length)

            # Update max streaks
            if current_streak_type == "win":
                max_win_streak = max(max_win_streak, current_streak_length)
            else:
                max_loss_streak = max(max_loss_streak, current_streak_length)

            # Transition detected
            transition_count += 1

            # Start new streak
            current_streak_length = 1
            current_streak_type = outcome

    # Record final streak
    streak_lengths.append(current_streak_length)
    if current_streak_type == "win":
        max_win_streak = max(max_win_streak, current_streak_length)
    else:
        max_loss_streak = max(max_loss_streak, current_streak_length)

    # Calculate average streak length
    avg_streak_length = Decimal(sum(streak_lengths)) / Decimal(len(streak_lengths))

    # Calculate alternation rate: transitions / (total outcomes - 1)
    # If we have N outcomes, there are N-1 potential transitions
    possible_transitions = len(valid_outcomes) - 1
    alternation_rate = Decimal(transition_count) / Decimal(possible_transitions) if possible_transitions > 0 else Decimal("0")

    # Determine signal: alternating if >= 0.4, clustered otherwise
    # Edge case: all wins or all losses (alternation_rate = 0) should be "alternating"
    # because there's no evidence of streaky clustering (only one outcome type)
    if alternation_rate == Decimal("0"):
        # All wins or all losses - no alternation evidence, default to alternating
        signal = "alternating"
    elif alternation_rate >= Decimal("0.4"):
        signal = "alternating"
    else:
        signal = "clustered"

    return {
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "avg_streak_length": avg_streak_length,
        "alternation_rate": alternation_rate,
        "signal": signal,
    }
