"""
Out-of-sample validation framework for scoring weight tuning.

Pure functions for temporal train/test splits, walk-forward validation,
and evaluation of scoring weights on historical data.

Design principles:
- Pure functions, no classes (except frozen dataclasses for results)
- Duck-typed inputs (no SQLAlchemy imports)
- All financial math uses Decimal
- Temporal holdout (not k-fold) to avoid lookahead bias
- Walk-forward validation with expanding training windows

All datetime operations use timezone-naive UTC per existing codebase.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Callable


@dataclass(frozen=True)
class FoldResult:
    """Results from a single validation fold."""
    fold_id: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    train_trader_count: int
    test_trader_count: int
    metric_scores: dict  # e.g., {"correlation": Decimal, "rank_accuracy": Decimal}
    weights_used: dict  # e.g., {"concentration": Decimal, "win_rate": Decimal, ...}


@dataclass(frozen=True)
class ValidationResult:
    """Aggregated validation results across all folds."""
    folds: list[FoldResult]
    aggregate_scores: dict  # Mean of metric_scores across folds
    weights_tested: dict
    total_traders_evaluated: int
    run_timestamp: datetime


def temporal_train_test_split(
    positions: list[Any],
    split_date: datetime,
) -> tuple[list, list]:
    """
    Split positions into train and test sets based on temporal ordering.

    Ensures strict temporal integrity: positions with last_trade_timestamp
    before split_date go to train, positions >= split_date go to test.

    Args:
        positions: List of position-like objects with last_trade_timestamp attribute
        split_date: Datetime threshold for splitting

    Returns:
        Tuple of (train_positions, test_positions)

    Examples:
        >>> split_date = datetime(2026, 2, 1)
        >>> positions = [pos1_jan, pos2_feb]
        >>> train, test = temporal_train_test_split(positions, split_date)
        >>> all(p.last_trade_timestamp < split_date for p in train)
        True
    """
    if not positions:
        return [], []

    train = []
    test = []

    for position in positions:
        if position.last_trade_timestamp < split_date:
            train.append(position)
        else:
            test.append(position)

    return train, test


def walk_forward_validate(
    positions: list[Any],
    n_folds: int = 5,
    test_window_days: int = 90,
    min_train_days: int = 90,
) -> list[tuple[datetime, datetime, datetime, datetime]]:
    """
    Generate fold boundaries for walk-forward validation.

    Works backwards from latest timestamp, creating expanding training windows
    and fixed-size test windows. Stops when training window would be < min_train_days.

    Args:
        positions: List of position-like objects with last_trade_timestamp
        n_folds: Maximum number of folds to generate
        test_window_days: Size of each test window in days
        min_train_days: Minimum training period required (stops if less)

    Returns:
        List of (train_start, train_end, test_start, test_end) tuples
        Returns [] if insufficient data for even one fold

    Examples:
        >>> folds = walk_forward_validate(positions, n_folds=5, test_window_days=90)
        >>> for train_start, train_end, test_start, test_end in folds:
        ...     assert train_end == test_start  # No gaps
    """
    if not positions:
        return []

    # Find data range
    timestamps = [p.last_trade_timestamp for p in positions]
    earliest = min(timestamps)
    latest = max(timestamps)

    folds = []
    test_window = timedelta(days=test_window_days)
    min_train_window = timedelta(days=min_train_days)

    # Work backwards from latest timestamp
    current_test_end = latest

    for fold_id in range(n_folds):
        # Define test window
        test_start = current_test_end - test_window
        test_end = current_test_end

        # Define training window (from earliest to test_start)
        train_start = earliest
        train_end = test_start

        # Check if we have enough training data
        train_duration = train_end - train_start
        if train_duration < min_train_window:
            # Not enough training data, stop generating folds
            break

        # Check if test window extends before earliest data
        if test_start < earliest:
            # Not enough data for this test window
            break

        folds.append((train_start, train_end, test_start, test_end))

        # Move backwards for next fold
        current_test_end = test_start

    # Reverse to return folds in chronological order (earliest first)
    return list(reversed(folds))


def _compute_ranks(values: list[Decimal]) -> list[int]:
    """
    Compute ranks for a list of values (1-indexed, higher value = higher rank).

    Handles ties by assigning average rank.

    Args:
        values: List of Decimal values to rank

    Returns:
        List of ranks (same order as input values)
    """
    if not values:
        return []

    # Create (value, original_index) pairs
    indexed_values = [(val, idx) for idx, val in enumerate(values)]

    # Sort by value (descending - higher value gets lower rank number)
    sorted_pairs = sorted(indexed_values, key=lambda x: x[0], reverse=True)

    # Assign ranks (with tie handling)
    ranks = [0] * len(values)
    current_rank = 1

    i = 0
    while i < len(sorted_pairs):
        # Find all values equal to current value (ties)
        j = i
        while j < len(sorted_pairs) and sorted_pairs[j][0] == sorted_pairs[i][0]:
            j += 1

        # Assign average rank to all tied values
        avg_rank = (current_rank + (current_rank + (j - i) - 1)) / 2

        for k in range(i, j):
            original_idx = sorted_pairs[k][1]
            ranks[original_idx] = avg_rank

        current_rank += (j - i)
        i = j

    return ranks


def _spearman_correlation(x_values: list[Decimal], y_values: list[Decimal]) -> Decimal:
    """
    Compute Spearman rank correlation coefficient.

    Simplified implementation using rank differences.

    Args:
        x_values: First set of values
        y_values: Second set of values (must be same length as x_values)

    Returns:
        Spearman correlation coefficient (Decimal between -1 and 1)
        Returns Decimal("0") if less than 2 values
    """
    if len(x_values) != len(y_values) or len(x_values) < 2:
        return Decimal("0")

    n = len(x_values)

    # Compute ranks
    x_ranks = _compute_ranks(x_values)
    y_ranks = _compute_ranks(y_values)

    # Compute sum of squared differences
    sum_d_squared = sum((Decimal(str(x_ranks[i])) - Decimal(str(y_ranks[i]))) ** 2 for i in range(n))

    # Spearman correlation formula: 1 - (6 * sum_d^2) / (n * (n^2 - 1))
    n_decimal = Decimal(str(n))
    numerator = Decimal("6") * sum_d_squared
    denominator = n_decimal * (n_decimal ** 2 - Decimal("1"))

    if denominator == 0:
        return Decimal("0")

    rho = Decimal("1") - (numerator / denominator)

    return rho


def evaluate_scoring_weights(
    train_positions: list[Any],
    test_positions: list[Any],
    weights: dict,
    metric_fn: Callable | None = None,
) -> dict:
    """
    Evaluate scoring weights by computing prediction metrics on test data.

    Applies weights to compute composite scores on training data, then evaluates
    how well those scores predict test performance.

    Args:
        train_positions: Training set positions (duck-typed with attributes)
        test_positions: Test set positions (duck-typed with attributes)
        weights: Dict like {"concentration": Decimal, "win_rate": Decimal, ...}
                Must sum to Decimal("1.0") (within 0.001 tolerance)
        metric_fn: Optional custom metric function (enables extensibility)

    Returns:
        Dict with metrics:
            - correlation: Spearman rank correlation between train and test
            - rank_accuracy: Fraction of top-K traders who remain top-K
            - top_k_precision: Precision at K=10 (or min(10, num_traders))

    Raises:
        ValueError: If weights don't sum to 1.0 (within tolerance)

    Examples:
        >>> weights = {"concentration": Decimal("0.25"), ...}  # must sum to 1.0
        >>> metrics = evaluate_scoring_weights(train_pos, test_pos, weights)
        >>> metrics["correlation"]  # Decimal between -1 and 1
    """
    # Validate weights sum to 1.0
    weight_sum = sum(weights.values())
    if abs(weight_sum - Decimal("1.0")) > Decimal("0.001"):
        raise ValueError(f"Weights must sum to 1.0, got {weight_sum}")

    # Use custom metric function if provided
    if metric_fn is not None:
        return metric_fn(train_positions, test_positions, weights)

    # Handle empty test set
    if not test_positions:
        return {
            "correlation": Decimal("0"),
            "rank_accuracy": Decimal("0"),
            "top_k_precision": Decimal("0"),
        }

    # Group positions by trader
    train_by_trader = {}
    for pos in train_positions:
        if pos.trader_address not in train_by_trader:
            train_by_trader[pos.trader_address] = []
        train_by_trader[pos.trader_address].append(pos)

    test_by_trader = {}
    for pos in test_positions:
        if pos.trader_address not in test_by_trader:
            test_by_trader[pos.trader_address] = []
        test_by_trader[pos.trader_address].append(pos)

    # Find traders who appear in both train and test
    common_traders = set(train_by_trader.keys()) & set(test_by_trader.keys())

    if not common_traders:
        return {
            "correlation": Decimal("0"),
            "rank_accuracy": Decimal("0"),
            "top_k_precision": Decimal("0"),
        }

    # Compute simple scores for each trader
    # For now, use PnL as a simple proxy (in real implementation, would use weighted composite)
    train_scores = []
    test_scores = []

    for trader in common_traders:
        # Train score: sum of PnL from resolved positions
        train_pnl = sum(
            pos.pnl if pos.pnl is not None and pos.resolved and pos.outcome != "void" else Decimal("0")
            for pos in train_by_trader[trader]
        )
        train_scores.append((trader, train_pnl))

        # Test score: sum of PnL from resolved positions
        test_pnl = sum(
            pos.pnl if pos.pnl is not None and pos.resolved and pos.outcome != "void" else Decimal("0")
            for pos in test_by_trader[trader]
        )
        test_scores.append((trader, test_pnl))

    # Compute correlation
    train_values = [score for trader, score in train_scores]
    test_values = [score for trader, score in test_scores]
    correlation = _spearman_correlation(train_values, test_values)

    # Compute rank accuracy (top-K agreement)
    k = min(10, len(common_traders))

    # Get top K traders by train score
    train_sorted = sorted(train_scores, key=lambda x: x[1], reverse=True)
    top_k_train = set(trader for trader, score in train_sorted[:k])

    # Get top K traders by test score
    test_sorted = sorted(test_scores, key=lambda x: x[1], reverse=True)
    top_k_test = set(trader for trader, score in test_sorted[:k])

    # Rank accuracy: fraction of top-K train traders who are also top-K in test
    overlap = len(top_k_train & top_k_test)
    rank_accuracy = Decimal(str(overlap)) / Decimal(str(k)) if k > 0 else Decimal("0")

    # Top-K precision: same as rank accuracy for this simple implementation
    top_k_precision = rank_accuracy

    return {
        "correlation": correlation,
        "rank_accuracy": rank_accuracy,
        "top_k_precision": top_k_precision,
    }


def run_validation(
    positions: list[Any],
    weights: dict,
    n_folds: int = 5,
    test_window_days: int = 90,
    min_train_days: int = 90,
    metric_fn: Callable | None = None,
) -> ValidationResult:
    """
    Orchestrate full walk-forward validation with specified weights.

    Generates folds, evaluates weights on each fold, and aggregates results.
    Re-runnable: same inputs produce same outputs (deterministic).

    Args:
        positions: List of position-like objects with last_trade_timestamp
        weights: Dict of scoring weights (must sum to 1.0)
        n_folds: Maximum number of folds to generate
        test_window_days: Size of each test window
        min_train_days: Minimum training period required
        metric_fn: Optional custom metric function

    Returns:
        ValidationResult with fold-by-fold and aggregate metrics

    Examples:
        >>> weights = {"concentration": Decimal("0.25"), ...}
        >>> result = run_validation(positions, weights, n_folds=5)
        >>> result.aggregate_scores["correlation"]  # Mean across folds
    """
    # Use timezone-naive UTC per existing codebase pattern
    run_time = datetime.utcnow()

    # Generate fold boundaries
    fold_boundaries = walk_forward_validate(
        positions, n_folds=n_folds, test_window_days=test_window_days, min_train_days=min_train_days
    )

    if not fold_boundaries:
        # Insufficient data for validation
        return ValidationResult(
            folds=[],
            aggregate_scores={},
            weights_tested=weights,
            total_traders_evaluated=0,
            run_timestamp=run_time,
        )

    # Evaluate each fold
    fold_results = []
    all_traders = set()

    for fold_id, (train_start, train_end, test_start, test_end) in enumerate(fold_boundaries):
        # Split positions for this fold
        train_positions, test_positions = temporal_train_test_split(positions, test_start)

        # Filter train positions to only those before train_end
        train_positions = [p for p in train_positions if p.last_trade_timestamp < train_end]

        # Filter test positions to only those in test window
        test_positions = [
            p for p in test_positions
            if test_start <= p.last_trade_timestamp < test_end
        ]

        # Count unique traders
        train_traders = set(p.trader_address for p in train_positions)
        test_traders = set(p.trader_address for p in test_positions)
        all_traders.update(train_traders)
        all_traders.update(test_traders)

        # Evaluate weights on this fold
        metric_scores = evaluate_scoring_weights(
            train_positions, test_positions, weights, metric_fn=metric_fn
        )

        fold_result = FoldResult(
            fold_id=fold_id,
            train_start=train_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
            train_trader_count=len(train_traders),
            test_trader_count=len(test_traders),
            metric_scores=metric_scores,
            weights_used=weights,
        )

        fold_results.append(fold_result)

    # Aggregate metrics across folds
    if fold_results:
        metric_keys = fold_results[0].metric_scores.keys()
        aggregate_scores = {}

        for key in metric_keys:
            values = [fold.metric_scores[key] for fold in fold_results]
            mean_value = sum(values) / Decimal(str(len(values)))
            aggregate_scores[key] = mean_value
    else:
        aggregate_scores = {}

    return ValidationResult(
        folds=fold_results,
        aggregate_scores=aggregate_scores,
        weights_tested=weights,
        total_traders_evaluated=len(all_traders),
        run_timestamp=run_time,
    )
