"""Pure lift metric functions for trader scoring.

All functions are stateless and operate on position data + market averages.
No database access -- follows the pure-function pattern from scoring.py and metrics.py.

Formula: composite = z(CLV) + z(ROI) + z(Sharpe), equal weights.
Validated by 348-experiment backtest -- no tuning needed.

Key design decisions:
- All intermediate math uses Decimal for financial precision.
- Float is used ONLY for statistics.mean/stdev calls, then immediately back to Decimal.
- Edge cases (empty input, single trader, zero stddev) return Decimal('0').
"""

import statistics
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class LiftMetrics:
    """Computed lift metrics for a single trader.

    Attributes:
        clv: Closing Line Value -- avg price advantage over crowd per position.
        roi: Return on Investment -- total_pnl / total_capital_deployed.
        sharpe: Sharpe ratio -- avg_pnl / stddev_pnl across positions.
        position_count: Number of valid positions used in computation.
    """

    clv: Decimal
    roi: Decimal
    sharpe: Decimal
    position_count: int


def compute_clv(positions: list, market_avgs: dict[str, Decimal]) -> Decimal:
    """Compute average Closing Line Value across all valid positions.

    CLV measures price advantage over the crowd (market average entry).
    - LONG: market_avg_entry - trader_avg_entry  (positive = bought cheaper)
    - SHORT: trader_avg_entry - market_avg_entry  (positive = sold dearer)

    Positions are skipped if:
    - avg_entry_price is None
    - market_id not in market_avgs

    Args:
        positions: List of Position-like objects with market_id, direction,
                   avg_entry_price attributes.
        market_avgs: Dict of {market_id: average_entry_price} for the population.

    Returns:
        Average CLV as Decimal. Returns Decimal('0') if no valid positions.
    """
    clv_values: list[Decimal] = []

    for pos in positions:
        if pos.avg_entry_price is None:
            continue
        market_avg = market_avgs.get(pos.market_id)
        if market_avg is None:
            continue

        if pos.direction == "LONG":
            clv = market_avg - pos.avg_entry_price
        elif pos.direction == "SHORT":
            clv = pos.avg_entry_price - market_avg
        else:
            continue  # FLAT positions skipped

        clv_values.append(clv)

    if not clv_values:
        return Decimal("0")

    return sum(clv_values, Decimal("0")) / Decimal(len(clv_values))


def compute_roi(positions: list) -> Decimal:
    """Compute Return on Investment across all valid positions.

    ROI = total_pnl / total_capital_deployed

    Capital deployed per position:
    - LONG: size * avg_entry_price  (you pay the price to buy shares)
    - SHORT: size * (1 - avg_entry_price)  (you pay the complement)

    Positions are skipped if pnl is None or avg_entry_price is None.
    Returns Decimal('0') if total capital deployed is zero.

    Args:
        positions: List of Position-like objects.

    Returns:
        ROI as Decimal. Returns Decimal('0') if no valid data.
    """
    total_pnl = Decimal("0")
    total_capital = Decimal("0")

    for pos in positions:
        if pos.pnl is None or pos.avg_entry_price is None:
            continue

        if pos.direction == "LONG":
            capital = pos.size * pos.avg_entry_price
        elif pos.direction == "SHORT":
            capital = pos.size * (Decimal("1") - pos.avg_entry_price)
        else:
            continue  # FLAT positions skipped

        total_pnl += pos.pnl
        total_capital += capital

    if total_capital == Decimal("0"):
        return Decimal("0")

    return total_pnl / total_capital


def compute_sharpe(positions: list) -> Decimal:
    """Compute Sharpe ratio as avg_pnl / stddev_pnl across positions.

    Only positions with non-None pnl are included.
    Returns Decimal('0') if:
    - Fewer than 2 valid positions (can't compute stddev)
    - stddev is zero (all positions have identical PnL)

    Args:
        positions: List of Position-like objects.

    Returns:
        Sharpe ratio as Decimal.
    """
    pnl_values = [
        float(pos.pnl) for pos in positions if pos.pnl is not None
    ]

    if len(pnl_values) < 2:
        return Decimal("0")

    avg = statistics.mean(pnl_values)
    try:
        std = statistics.stdev(pnl_values)
    except statistics.StatisticsError:
        return Decimal("0")

    if std == 0:
        return Decimal("0")

    return Decimal(str(avg / std))


def compute_z_scores(values: dict[str, Decimal]) -> dict[str, Decimal]:
    """Z-score normalize a population of trader metric values.

    Returns {trader_address: z_score} where z = (x - mean) / stdev.

    Edge cases:
    - n <= 1: returns {addr: Decimal('0')} for all (can't normalize)
    - stdev == 0: returns all zeros (all traders have identical values)

    Args:
        values: Dict of {trader_address: metric_value}.

    Returns:
        Dict of {trader_address: z_score}.
    """
    if not values:
        return {}

    if len(values) <= 1:
        return {addr: Decimal("0") for addr in values}

    float_vals = [float(v) for v in values.values()]
    mean = statistics.mean(float_vals)
    try:
        std = statistics.stdev(float_vals)
    except statistics.StatisticsError:
        return {addr: Decimal("0") for addr in values}

    if std == 0:
        return {addr: Decimal("0") for addr in values}

    return {
        addr: Decimal(str((float(val) - mean) / std))
        for addr, val in values.items()
    }


def compute_composite(
    clv_z: dict[str, Decimal],
    roi_z: dict[str, Decimal],
    sharpe_z: dict[str, Decimal],
) -> dict[str, Decimal]:
    """Compute composite score as equal-weight sum of z-scores.

    composite = z(CLV) + z(ROI) + z(Sharpe)

    Only traders present in ALL THREE dicts are included.
    This is correct behavior: traders without all three z-scores
    cannot be reliably ranked.

    Args:
        clv_z: Dict of {trader_address: clv_z_score}.
        roi_z: Dict of {trader_address: roi_z_score}.
        sharpe_z: Dict of {trader_address: sharpe_z_score}.

    Returns:
        Dict of {trader_address: composite_score}.
    """
    all_traders = set(clv_z) & set(roi_z) & set(sharpe_z)
    return {
        addr: clv_z[addr] + roi_z[addr] + sharpe_z[addr]
        for addr in all_traders
    }


def assign_quintiles(composite_scores: dict[str, Decimal]) -> dict[str, int]:
    """Assign quintile ranks (Q1-Q5) based on composite scores.

    Q5 = top 20% (highest composite scores, best traders).
    Q1 = bottom 20% (lowest composite scores).

    Quintile bands: sort ascending, assign by 20% bands.
    Formula: quintile = min(5, (rank_idx * 5) // n + 1)

    Edge cases:
    - Empty dict: returns empty dict.
    - Single trader: assigned Q3 (middle quintile).

    Args:
        composite_scores: Dict of {trader_address: composite_score}.

    Returns:
        Dict of {trader_address: quintile} where quintile in [1, 5].
    """
    if not composite_scores:
        return {}

    if len(composite_scores) == 1:
        addr = next(iter(composite_scores))
        return {addr: 3}

    sorted_traders = sorted(composite_scores.items(), key=lambda x: x[1])
    n = len(sorted_traders)

    quintiles: dict[str, int] = {}
    for rank_idx, (addr, _) in enumerate(sorted_traders):
        # rank_idx 0 = lowest score = Q1
        quintile = min(5, (rank_idx * 5) // n + 1)
        quintiles[addr] = quintile

    return quintiles
