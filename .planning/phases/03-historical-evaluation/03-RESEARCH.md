# Phase 3: Historical Evaluation - Research

**Researched:** 2026-02-06
**Domain:** Trading performance metrics calculation with time-series analysis
**Confidence:** MEDIUM

## Summary

This research investigates building a historical performance evaluation system for prediction market traders with multiple timeframes and trader profile classification. The standard approach uses pure Python functions for metrics calculation (avoiding heavyweight backtesting frameworks), SQLite time-based queries with proper indexing, and statistical analysis to differentiate consistent performers from streaky traders.

Key technical challenges include efficiently querying time-windowed data from SQLite, calculating accurate PnL including both realized (resolved markets) and unrealized (open positions) components, handling mark-to-market valuation for open positions, and building a validation framework that supports periodic re-tuning without overfitting.

The research reveals that standard trading performance libraries (empyrical, quantstats) expect continuous return series and are overkill for discrete trade evaluation. Instead, simple aggregation functions over filtered trade sets with Decimal precision match the existing codebase pattern better. For validation, temporal train-test splits (not k-fold) are critical for time-series data to avoid lookahead bias.

**Primary recommendation:** Use pure Python functions for metrics calculation (matching Phase 2's position tracker pattern), SQLite datetime range queries with composite indexes on (trader_address, timestamp, resolved), and temporal holdout validation with walk-forward testing capability for periodic weight re-tuning.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Timeframe windows:**
- Rolling from current time (not calendar periods or poll-relative)
- Windows: 7d, 30d, 90d, all-time
- Sparse windows (few resolved markets): calculate metrics but flag as low-confidence — downstream scoring weights accordingly

**Trader profiles:**
- Tag traders as "selective" vs "active" based on unique markets entered (not trade count)
- A trader placing many trades on 2 markets = selective; one trade each on 10 markets = active
- Both profiles can score high through different lenses: accuracy (selective) vs volume-weighted edge (active)

**Consistency detection:**
- Primary signal: cross-timeframe stability (compare win rate across 30d/90d/all-time — stable = consistent, divergent = streaky)
- Secondary signal: streak length analysis (alternating W/L at 70% > 8 wins then 8 losses)
- Different consistency bars per profile: selective traders need stability across fewer windows than active traders
- No special "declining" flag — Phase 4 recency weighting handles performance drops naturally

**Market difficulty:**
- Track entry prices and implied probabilities alongside performance metrics
- Do NOT adjust raw win rate or PnL for difficulty — PnL already captures edge naturally
- Data is available for future analysis but metrics stay clean and simple

**Resolution handling:**
- Voided/cancelled markets: exclude completely from all calculations (never happened)
- Resolved markets: include in PnL/win rate (resolution settles positions automatically, no explicit close needed)
- Unresolved markets: mark-to-market using current token price, tracked with "unrealized" flag, separate from realized metrics
- Resolution grace period: Claude's discretion based on Polymarket dispute mechanics

**Validation framework:**
- Goal: tune scoring weights (concentration, win rate, recency, sample size) using historical data
- Data split strategy: Claude's discretion
- Framework must be re-runnable — periodic re-tuning (monthly/quarterly) as market evolves and meta shifts
- Validation output format: Claude's discretion

### Claude's Discretion

- Data split methodology for validation (temporal holdout vs k-fold vs hybrid)
- Validation output format and metrics
- Resolution grace period handling
- Exact thresholds for selective vs active profile boundary
- Exact consistency bar differences between profiles
- Sparse window confidence flag threshold

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope

</user_constraints>

## Standard Stack

The established libraries/tools for this domain:

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib statistics | 3.11+ | Variance, stdev calculation | Built-in, zero dependencies, sufficient for basic stats |
| SQLAlchemy | 2.0.46+ (already in use) | Time-windowed queries with filters | Already used in Phase 1, ORM layer established |
| Decimal | stdlib | Financial precision | Already used in Phase 2 position tracker |
| datetime/timedelta | stdlib | Time window calculations | Built-in, standard for time-based filtering |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pandas | 2.3+ (optional) | Rolling window calculations, time-based grouping | If aggregation logic becomes complex; NOT needed for simple metrics |
| numpy | 2.2+ (optional) | Statistical calculations (if pandas used) | Dependency of pandas, vectorized operations |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Pure functions | empyrical/quantstats | empyrical expects continuous return series, not discrete trades; adds heavyweight dependency for simple aggregations |
| SQLite datetime filtering | Load all to pandas then filter | SQLite indexes are faster for time windows; pandas overhead unnecessary |
| Temporal holdout | K-fold cross-validation | K-fold invalid for time series (lookahead bias); temporal split respects causality |
| Manual stats | scipy.stats | scipy.stats overkill for mean/variance/count; stdlib sufficient for Phase 3 needs |

**Installation:**

No new dependencies required for core functionality. Optional pandas if aggregation becomes complex:

```bash
# Optional - only if aggregation logic justifies it
pip install pandas==2.3.0
```

## Architecture Patterns

### Recommended Module Structure

```
src/
├── evaluation/              # NEW - Performance evaluation layer
│   ├── __init__.py
│   ├── metrics.py           # Pure functions: calculate_pnl, calculate_win_rate, calculate_volume
│   ├── timeframes.py        # Pure functions: get_timeframe_bounds, filter_trades_by_window
│   ├── profiles.py          # Pure functions: classify_trader_profile, calculate_consistency
│   └── validation.py        # Validation framework: temporal_split, walk_forward_validate
├── db/
│   └── models.py            # EXTEND - Add PerformanceMetrics, TraderProfile models
└── pipeline/
    └── queries.py           # EXTEND - Add time-windowed trade queries
```

### Pattern 1: Pure Function Metrics (Matching Phase 2 Position Tracker)

**What:** Stateless functions that accept filtered trades/positions and return calculated metrics. No classes, no state.

**When to use:** For all metric calculations to maintain consistency with existing codebase (position_tracker.py is already pure functions).

**Example:**

```python
# Source: Existing pattern from src/discovery/position_tracker.py + trading metrics best practices
from decimal import Decimal
from datetime import datetime
from typing import Any

def calculate_performance_metrics(
    positions: list[Any],  # Duck-typed Position objects
    trades: list[Any],      # Duck-typed Trade objects
) -> dict[str, Decimal | int]:
    """
    Calculate performance metrics from resolved positions.

    Pure function - accepts duck-typed inputs (no SQLAlchemy imports).

    Args:
        positions: List of position-like objects with:
                  - resolved: bool
                  - outcome: str ("win", "loss", "flat", "void")
                  - pnl: Decimal
                  - size: Decimal (for volume calculation)
        trades: List of trade-like objects for volume calculation

    Returns:
        Dictionary with:
            - total_pnl: Decimal (sum of realized PnL)
            - win_rate: Decimal (wins / resolved_count * 100)
            - total_volume: Decimal (sum of trade sizes)
            - resolved_count: int (number of resolved positions)
            - win_count: int
            - loss_count: int
    """
    if not positions:
        return {
            "total_pnl": Decimal("0"),
            "win_rate": Decimal("0"),
            "total_volume": Decimal("0"),
            "resolved_count": 0,
            "win_count": 0,
            "loss_count": 0,
        }

    # Filter resolved positions (exclude void/flat)
    resolved = [p for p in positions if p.resolved and p.outcome in ("win", "loss")]

    if not resolved:
        return {
            "total_pnl": Decimal("0"),
            "win_rate": Decimal("0"),
            "total_volume": sum(Decimal(str(t.size)) for t in trades),
            "resolved_count": 0,
            "win_count": 0,
            "loss_count": 0,
        }

    # Calculate PnL
    total_pnl = sum(p.pnl for p in resolved)

    # Calculate win rate
    win_count = sum(1 for p in resolved if p.outcome == "win")
    loss_count = sum(1 for p in resolved if p.outcome == "loss")
    win_rate = (Decimal(win_count) / Decimal(len(resolved))) * Decimal("100")

    # Calculate volume from trades
    total_volume = sum(Decimal(str(t.size)) for t in trades)

    return {
        "total_pnl": total_pnl,
        "win_rate": win_rate,
        "total_volume": total_volume,
        "resolved_count": len(resolved),
        "win_count": win_count,
        "loss_count": loss_count,
    }
```

### Pattern 2: SQLite Time-Window Queries with Composite Indexes

**What:** Use datetime range filtering in SQL with composite indexes for efficient time-windowed queries.

**When to use:** For fetching trades/positions within specific timeframes (7d, 30d, 90d).

**Example:**

```python
# Source: SQLite datetime best practices + existing models.py pattern
from datetime import datetime, timedelta
from sqlalchemy import select, and_
from src.db.models import Trade, Position

def get_trades_in_window(
    session,
    trader_address: str,
    window_days: int | None,
    resolved_only: bool = False,
) -> list[Trade]:
    """
    Fetch trades within a time window for a trader.

    Uses composite index on (trader_address, timestamp) for performance.

    Args:
        session: SQLAlchemy session
        trader_address: Trader's wallet address
        window_days: Number of days to look back (None = all-time)
        resolved_only: If True, only include trades on resolved markets

    Returns:
        List of Trade objects within window
    """
    query = select(Trade).where(Trade.trader_address == trader_address)

    # Add time window filter
    if window_days is not None:
        cutoff = datetime.utcnow() - timedelta(days=window_days)
        query = query.where(Trade.timestamp >= cutoff)

    # Join to positions to filter by resolution status
    if resolved_only:
        query = (
            query.join(Position, and_(
                Position.trader_address == Trade.trader_address,
                Position.market_id == Trade.market_id,
                Position.resolved == True
            ))
        )

    # Order by timestamp for consistency
    query = query.order_by(Trade.timestamp.asc())

    return session.execute(query).scalars().all()

# Required index (already exists from Phase 1):
# Index('ix_trade_trader_timestamp', 'trader_address', 'timestamp')
```

### Pattern 3: Trader Profile Classification

**What:** Classify traders into "selective" (few markets, many trades each) vs "active" (many markets, fewer trades each) based on unique markets entered.

**When to use:** During trader evaluation to apply profile-specific consistency thresholds.

**Example:**

```python
# Source: User requirements + trading behavior analysis patterns
from decimal import Decimal
from typing import Literal

TraderProfileType = Literal["selective", "active"]

def classify_trader_profile(
    unique_markets_count: int,
    total_trades_count: int,
    threshold_markets: int = 10,  # Claude's discretion
) -> TraderProfileType:
    """
    Classify trader as selective vs active based on market breadth.

    Logic:
        - Selective: Few unique markets (<= threshold) with high concentration
        - Active: Many unique markets (> threshold) with broad participation

    Args:
        unique_markets_count: Number of unique markets entered
        total_trades_count: Total number of trades placed
        threshold_markets: Boundary between selective and active (default: 10)

    Returns:
        "selective" or "active"
    """
    if unique_markets_count <= threshold_markets:
        return "selective"
    else:
        return "active"

def calculate_consistency_score(
    win_rates: dict[str, Decimal],  # {timeframe: win_rate}
    trader_profile: TraderProfileType,
) -> dict[str, Decimal | bool]:
    """
    Calculate consistency score from cross-timeframe win rate stability.

    Consistency = low variance in win rates across timeframes.

    Args:
        win_rates: Dict mapping timeframe ("7d", "30d", "90d", "all") to win rate
        trader_profile: "selective" or "active" (affects threshold)

    Returns:
        Dict with:
            - variance: Decimal (variance of win rates)
            - is_consistent: bool (True if variance below threshold)
            - threshold: Decimal (threshold used based on profile)
    """
    import statistics

    # Extract win rates that exist (handle sparse windows)
    available_rates = [float(wr) for wr in win_rates.values() if wr is not None]

    if len(available_rates) < 2:
        # Not enough data to assess consistency
        return {
            "variance": Decimal("0"),
            "is_consistent": False,
            "threshold": Decimal("0"),
        }

    # Calculate variance
    variance = Decimal(str(statistics.variance(available_rates)))

    # Profile-specific thresholds (Claude's discretion - tune via validation)
    # Selective traders allowed higher variance (fewer samples)
    # Active traders need tighter consistency (more samples stabilize)
    threshold = Decimal("100") if trader_profile == "selective" else Decimal("50")

    is_consistent = variance <= threshold

    return {
        "variance": variance,
        "is_consistent": is_consistent,
        "threshold": threshold,
    }
```

### Pattern 4: Mark-to-Market Unrealized PnL

**What:** Calculate unrealized PnL for open positions using current market price from Polymarket API.

**When to use:** When displaying total performance including open positions (separate from realized metrics).

**Example:**

```python
# Source: Polymarket mark-to-market mechanics + position tracker pattern
from decimal import Decimal

def calculate_unrealized_pnl(
    position_size: Decimal,
    position_direction: str,  # "LONG" or "SHORT"
    avg_entry_price: Decimal,
    current_market_price: Decimal,
) -> Decimal:
    """
    Calculate unrealized PnL for an open position.

    Uses mark-to-market pricing: current_price vs entry_price.

    Args:
        position_size: Absolute position size (always positive)
        position_direction: "LONG" or "SHORT"
        avg_entry_price: Weighted average entry price
        current_market_price: Current market price from API (midpoint or last trade)

    Returns:
        Unrealized PnL (positive = profit, negative = loss)
    """
    if position_direction == "LONG":
        # Long: profit if current > entry
        unrealized_pnl = position_size * (current_market_price - avg_entry_price)
    elif position_direction == "SHORT":
        # Short: profit if entry > current
        unrealized_pnl = position_size * (avg_entry_price - current_market_price)
    else:
        unrealized_pnl = Decimal("0")

    return unrealized_pnl

# Note: Fetch current_market_price from Polymarket API:
# client.get_last_trade_price(token_id) or client.get_midpoint(token_id)
```

### Pattern 5: Temporal Holdout Validation (Not K-Fold)

**What:** Split data by time (train on earlier data, validate on later data) to avoid lookahead bias.

**When to use:** For validation framework to tune scoring weights without overfitting.

**Example:**

```python
# Source: Walk-forward validation patterns for time series
from datetime import datetime, timedelta
from typing import Callable, Any

def temporal_train_test_split(
    data: list[Any],  # List of timestamped objects
    test_window_days: int = 90,  # Last 90 days for test
    get_timestamp: Callable[[Any], datetime] = lambda x: x.timestamp,
) -> tuple[list[Any], list[Any]]:
    """
    Split timestamped data into train/test sets by time.

    Train set: all data up to (now - test_window_days)
    Test set: last test_window_days of data

    Args:
        data: List of objects with timestamp attribute
        test_window_days: Number of days for test set
        get_timestamp: Function to extract timestamp from object

    Returns:
        (train_data, test_data) tuple
    """
    if not data:
        return [], []

    # Find split point
    cutoff = datetime.utcnow() - timedelta(days=test_window_days)

    train_data = [d for d in data if get_timestamp(d) < cutoff]
    test_data = [d for d in data if get_timestamp(d) >= cutoff]

    return train_data, test_data

def walk_forward_validate(
    data: list[Any],
    n_splits: int = 5,
    test_window_days: int = 30,
) -> list[tuple[list[Any], list[Any]]]:
    """
    Create multiple train/test splits with rolling window.

    Each split uses progressively more data for training.

    Args:
        data: List of timestamped objects (sorted by time)
        n_splits: Number of train/test splits to create
        test_window_days: Size of each test window

    Returns:
        List of (train, test) tuples
    """
    splits = []

    # Sort by timestamp
    sorted_data = sorted(data, key=lambda x: x.timestamp)

    # Calculate split points
    for i in range(n_splits):
        # Progressive cutoff: each split includes more historical data
        cutoff = datetime.utcnow() - timedelta(days=(n_splits - i) * test_window_days)

        train = [d for d in sorted_data if d.timestamp < cutoff]
        test = [
            d for d in sorted_data
            if cutoff <= d.timestamp < cutoff + timedelta(days=test_window_days)
        ]

        if train and test:
            splits.append((train, test))

    return splits
```

### Anti-Patterns to Avoid

- **Using K-fold cross-validation on time series:** Creates lookahead bias (training on future data to predict past). Always use temporal splits.
- **Mixing realized and unrealized PnL:** Keep separate. Realized PnL is historical fact, unrealized PnL is mark-to-market estimate that fluctuates.
- **Adjusting win rate for market difficulty:** PnL already captures edge. Adjusting win rate adds complexity without value.
- **Fetching all trades then filtering in Python:** Use SQL WHERE clauses with indexed columns for time windows. 100x faster for large datasets.
- **Using empyrical/quantstats for discrete trades:** These libraries expect continuous return series. Discrete trades need simple aggregation functions.
- **Hardcoding timeframe windows:** Make configurable (7d, 30d, 90d, all-time) so validation can test different windows.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Statistical variance/stdev | Manual sum of squares | Python stdlib `statistics.variance()` | Handles edge cases (n=1, n=0), uses Bessel's correction |
| Time window calculations | Manual date arithmetic | datetime + timedelta | Handles DST, leap years, month boundaries correctly |
| Walk-forward validation | Custom nested loops | Pattern from backtesting literature | Easy to introduce off-by-one errors or lookahead bias |
| Unrealized PnL calculation | Custom formulas | Standard mark-to-market formula | Long/short direction logic is error-prone |
| SQL datetime filtering | Load to pandas then filter | SQLite WHERE with datetime | Indexed SQL is 10-100x faster for time ranges |

**Key insight:** Performance metrics are well-defined in trading literature. The challenge is adapting them to discrete trades (not continuous returns) and avoiding lookahead bias in validation. Use battle-tested formulas and temporal split patterns rather than inventing custom logic.

## Common Pitfalls

### Pitfall 1: Lookahead Bias in Validation

**What goes wrong:** Training on data that includes future information (e.g., k-fold cross-validation) produces unrealistically optimistic validation results that don't hold in production.

**Why it happens:** Standard ML validation methods (k-fold, stratified sampling) assume i.i.d. data. Time series violates this assumption.

**How to avoid:**
- Always use temporal splits: train on [t0, t1), validate on [t1, t2)
- Never shuffle time-series data
- Walk-forward validation for robustness (multiple temporal splits)

**Warning signs:** Validation performance much better than production; model works on test set but fails on new data.

### Pitfall 2: Polymarket Resolution Timing and Grace Period

**What goes wrong:** Markets can be disputed for 2 hours after proposed resolution. Including trades on recently-resolved markets may capture positions that don't reflect the final outcome yet.

**Why it happens:** UMA's Optimistic Oracle allows 2-hour challenge period. If disputed, resolution takes "a few days" for UMA DVM vote.

**How to avoid:**
- Add grace period: exclude markets resolved within last 2-4 hours from "resolved" metrics
- Flag positions as "pending_resolution" during grace period
- Re-calculate metrics after grace period expires

**Warning signs:** PnL calculations change after re-running hours later; positions resolve to different outcomes.

**Recommendation:** Use 4-hour grace period (2x the challenge period) to allow for dispute processing time.

### Pitfall 3: Sparse Timeframe Windows Leading to Statistical Noise

**What goes wrong:** Win rate in 7-day window based on 1 resolved market shows 100% or 0%, which is statistically meaningless but gets treated as signal.

**Why it happens:** Short windows or slow-moving markets produce small sample sizes. Variance is inversely proportional to sample size.

**How to avoid:**
- Flag windows with < N resolved markets as "low_confidence" (recommend N=5)
- Weight by sample size in downstream scoring (Phase 4)
- Display confidence flags in UI (Phase 7)

**Warning signs:** 7d win rate = 100%, 30d win rate = 45%, all-time = 52% (7d is noise, not signal).

### Pitfall 4: SQLite Datetime Timezone Confusion

**What goes wrong:** Mixing UTC and local time causes off-by-hours errors in time window calculations. Queries return incorrect trades.

**Why it happens:** SQLite stores TEXT datetime without timezone. Python datetime can be naive or aware. Polymarket API uses Unix timestamps (UTC).

**How to avoid:**
- Store all datetimes as UTC in database (use `datetime.utcnow()`)
- Convert API Unix timestamps to UTC datetime explicitly
- Use timezone-naive datetime objects consistently (all UTC)
- Document in comments: "All datetimes are UTC"

**Warning signs:** Time window queries missing expected trades; trades appear in wrong window; queries work differently in different timezones.

### Pitfall 5: Float Precision Errors in Performance Metrics

**What goes wrong:** Using float for PnL/win rate calculations accumulates rounding errors. PnL doesn't match expected values.

**Why it happens:** Binary floating-point cannot exactly represent decimal fractions. Errors compound over aggregations.

**How to avoid:**
- Use Decimal type for all financial calculations (already established in Phase 2)
- Convert float API responses to Decimal immediately: `Decimal(str(value))`
- Never mix float and Decimal (choose one consistently)

**Warning signs:** PnL total doesn't match sum of individual position PnLs; win rate percentages don't add up correctly.

### Pitfall 6: Consistency Detection Based on Insufficient Data

**What goes wrong:** Calculating variance across timeframes when only 1-2 windows have data produces meaningless consistency scores.

**Why it happens:** Variance calculation requires n >= 2 samples. With sparse data, consistency metrics are statistical noise.

**How to avoid:**
- Require minimum 2 timeframes with >= 5 resolved markets each for consistency calculation
- Return None/null for consistency score if insufficient data
- Flag traders as "insufficient_history" in metadata

**Warning signs:** Consistency scores of 0.0 or very high variance for traders with < 10 total markets; all new traders flagged as "inconsistent."

### Pitfall 7: Ignoring Position Direction in Unrealized PnL

**What goes wrong:** Calculating unrealized PnL as `size * (current - entry)` for both LONG and SHORT positions. SHORT positions show inverted PnL.

**Why it happens:** PnL formula differs by direction. LONG profits when price rises, SHORT profits when price falls.

**How to avoid:**
- Separate formulas: LONG = size * (current - entry), SHORT = size * (entry - current)
- Validate with test cases covering both directions
- Use existing `calculate_pnl` pattern from position_tracker.py as reference

**Warning signs:** SHORT positions show positive PnL when price rises (should be negative); unrealized PnL doesn't match expected values.

## Code Examples

Verified patterns from official sources:

### Python Statistics Variance Calculation

```python
# Source: Python stdlib documentation
import statistics
from decimal import Decimal

def calculate_win_rate_variance(win_rates: list[Decimal]) -> Decimal:
    """
    Calculate variance of win rates across timeframes.

    Uses Bessel's correction (n-1 denominator) for sample variance.
    """
    if len(win_rates) < 2:
        return Decimal("0")

    # Convert Decimal to float for statistics module
    float_rates = [float(wr) for wr in win_rates]

    # Calculate sample variance
    variance = statistics.variance(float_rates)

    return Decimal(str(variance))
```

### SQLite Datetime Range Query with Index

```python
# Source: SQLite best practices + SQLAlchemy 2.0 documentation
from datetime import datetime, timedelta
from sqlalchemy import select, and_
from src.db.models import Trade

def get_trades_last_n_days(session, trader_address: str, days: int):
    """
    Fetch trades within last N days for a trader.

    Uses composite index: Index('ix_trade_trader_timestamp', 'trader_address', 'timestamp')
    """
    cutoff = datetime.utcnow() - timedelta(days=days)

    query = (
        select(Trade)
        .where(and_(
            Trade.trader_address == trader_address,
            Trade.timestamp >= cutoff
        ))
        .order_by(Trade.timestamp.asc())
    )

    return session.execute(query).scalars().all()
```

### Polymarket Current Price Fetching

```python
# Source: py-clob-client documentation
from py_clob_client.client import ClobClient
from decimal import Decimal

def get_current_market_price(client: ClobClient, token_id: str) -> Decimal:
    """
    Fetch current market price for unrealized PnL calculation.

    Uses midpoint price (average of best bid and ask).
    """
    # Option 1: Midpoint (most stable)
    midpoint = client.get_midpoint(token_id)

    # Option 2: Last trade price (most recent)
    # last_price = client.get_last_trade_price(token_id)

    # Option 3: Best bid/ask (for more precision)
    # buy_price = client.get_price(token_id, side="BUY")
    # sell_price = client.get_price(token_id, side="SELL")
    # midpoint = (Decimal(str(buy_price)) + Decimal(str(sell_price))) / Decimal("2")

    return Decimal(str(midpoint))
```

### Temporal Train-Test Split

```python
# Source: Walk-forward validation literature
from datetime import datetime, timedelta

def create_temporal_split(
    positions: list,
    test_months: int = 3
) -> tuple[list, list]:
    """
    Split positions by time for validation.

    Train: all positions resolved before (now - test_months)
    Test: positions resolved in last test_months
    """
    cutoff = datetime.utcnow() - timedelta(days=test_months * 30)

    train = [p for p in positions if p.computed_at < cutoff]
    test = [p for p in positions if p.computed_at >= cutoff]

    return train, test
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| K-fold CV for time series | Temporal/walk-forward splits | ML best practices ~2018 | Eliminates lookahead bias in validation |
| Continuous return series (empyrical) | Discrete trade metrics | Adapting to prediction markets | Simpler metrics, no need to interpolate |
| Float for financial data | Decimal type | Python best practices (longstanding) | Eliminates precision errors |
| Load all → filter in pandas | SQL datetime range queries | SQLite 3.x optimization | 10-100x faster for time windows |
| Single train-test split | Walk-forward validation | Backtesting evolution ~2020 | More robust weight tuning |

**Deprecated/outdated:**
- **empyrical/quantstats for discrete trades:** Designed for continuous return series; overkill for simple win rate/PnL aggregation
- **K-fold cross-validation on time series:** Violates temporal causality; use temporal splits
- **Calendar-based windows (monthly, quarterly):** User specified rolling windows from current time (7d, 30d, 90d)

## Open Questions

Things that couldn't be fully resolved:

1. **Exact threshold for selective vs active trader classification**
   - What we know: Based on unique markets entered, not trade count; user wants to capture "sniper traders" (selective, high accuracy)
   - What's unclear: Specific threshold value (10 markets? 15? 20?)
   - Recommendation: Start with 10 markets as boundary, tune via validation framework. Track distribution of unique_markets in dataset to inform threshold.

2. **Optimal validation data split size**
   - What we know: Must be temporal (not k-fold); framework must support periodic re-tuning
   - What's unclear: What % of data for test set? How many walk-forward splits?
   - Recommendation: Use 3-month test window (matches 90d timeframe), 5-fold walk-forward for robustness. Re-validate quarterly as meta shifts.

3. **Confidence flag threshold for sparse windows**
   - What we know: Sparse windows (few resolved markets) should be flagged as low-confidence
   - What's unclear: Exact threshold (< 3 markets? < 5? < 10?)
   - Recommendation: Start with 5 resolved markets minimum for reliable statistics. Flag windows with < 5 as "low_confidence". Validate empirically.

4. **Consistency variance thresholds by trader profile**
   - What we know: Selective traders allowed more variance than active traders; different consistency bars
   - What's unclear: Specific variance values for "consistent" flag
   - Recommendation: Use validation framework to tune. Initial hypothesis: variance < 100 for selective, < 50 for active. Iterate based on correlation with out-of-sample performance.

5. **Resolution grace period duration**
   - What we know: UMA Optimistic Oracle has 2-hour challenge period; disputes take "a few days"
   - What's unclear: Optimal grace period to balance freshness vs accuracy
   - Recommendation: 4-hour grace period (2x challenge window) handles most non-disputed cases. Flag disputed markets separately (may take days).

## Sources

### Primary (HIGH confidence)

- [pandas.DataFrame.rolling documentation](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.rolling.html) - Time-based rolling window syntax
- [Python statistics module documentation](https://docs.python.org/3/library/statistics.html) - Variance and statistical functions
- [SQLite datetime best practices](https://copyprogramming.com/howto/insert-datetime-in-sqlite) - SQLite 3.51.0 datetime handling
- [py-clob-client GitHub](https://github.com/Polymarket/py-clob-client) - get_midpoint, get_last_trade_price methods
- [Polymarket resolution documentation](https://docs.polymarket.com/polymarket-learn/markets/how-are-markets-resolved) - UMA Optimistic Oracle 2-hour challenge period
- [Polymarket binary markets](https://rocknblock.io/blog/how-polymarket-works-the-tech-behind-prediction-markets) - YES/NO token settlement to $0 or $1

### Secondary (MEDIUM confidence)

- [Walk-Forward Optimization introduction](https://blog.quantinsti.com/walk-forward-optimization-introduction/) - Temporal validation patterns
- [Time Series Cross-Validation Best Practices](https://medium.com/@pacosun/respect-the-order-cross-validation-in-time-series-7d12beab79a1) - Why k-fold fails for time series
- [Backtesting Machine Learning Models for Time Series](https://machinelearningmastery.com/backtest-machine-learning-models-time-series-forecasting/) - Temporal train-test split methodology
- [Sharpe Ratio calculation in Python](https://blog.quantinsti.com/sharpe-ratio-applications-algorithmic-trading/) - Trading metrics formulas
- [empyrical GitHub](https://github.com/quantopian/empyrical) - Common financial metrics library
- [quantstats PyPI](https://pypi.org/project/quantstats/) - Portfolio analytics library
- [Mark-to-market unrealized PnL](https://www.kucoin.com/support/26695061760793) - Calculation formulas
- [SQLite time-range query optimization](https://sqlite.org/forum/info/ef0d0d63b9c1cd20) - Index usage for datetime filtering

### Tertiary (LOW confidence)

- General web search results on trader behavior classification
- Trading strategy blog posts (not academic sources)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - stdlib + existing dependencies (SQLAlchemy, Decimal) are well-established
- Architecture patterns: HIGH - Pure functions match Phase 2 pattern; temporal validation is industry standard
- Pitfalls: MEDIUM - Timezone, precision, and lookahead bias are documented but need testing
- Trader profile classification: LOW - No academic standard found; using logical heuristics from user requirements
- Threshold values (consistency, sparse windows): LOW - Require empirical validation; initial values are educated guesses

**Research date:** 2026-02-06
**Valid until:** 2026-03-06 (30 days - stable libraries, but validation results may inform threshold updates)

**Notes:**
- No new dependencies required (use stdlib + existing Phase 1-2 stack)
- Pure function pattern from Phase 2 position_tracker.py should be extended for consistency
- Temporal validation is critical - k-fold would be fatal flaw
- Threshold values (10 markets, 5 resolved minimum, variance < 50/100) are initial hypotheses to be tuned via validation framework
- Resolution grace period (4 hours) conservative choice; can reduce after observing dispute frequency
