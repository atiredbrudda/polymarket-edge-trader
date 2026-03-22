# Phase 25: Lift-Based Scoring v2 - Research

**Researched:** 2026-03-22
**Domain:** Scoring engine replacement (z-score composite), CLI rewire, DB schema migration
**Confidence:** HIGH

## Summary

Phase 25 replaces the entire old scoring engine (40% win_rate + 25% concentration + 20% recency + 15% sample_size) with a backtest-validated formula: **z(CLV) + z(ROI) + z(Sharpe)** with equal weights. The backtest briefing (ANALYZE_BRIEFING.md) provides exhaustive evidence that this formula outperforms all 84 tested alternatives across 5 markets. Win rate is explicitly excluded -- it predicts nothing about future profitability.

The implementation requires: (1) new pure-function lift metrics module computing CLV, ROI, and Sharpe per trader per category, (2) a new LiftScore ORM model replacing ExpertiseScore, (3) rewiring the scoring pipeline from the old weighted composite to z-score normalization, (4) rewiring the `score` and `leaderboard` CLI commands, (5) enriching consensus signals with price context (expert avg entry), and (6) rewriting the `analyze` command as the primary Q5 identification surface.

**Primary recommendation:** Build as two plans -- P0 (scoring engine replacement + analyze rewrite) and P1 (signal price-context enrichment + slippage tracking). Fade detection is deferred per CONTEXT.md.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Composite score = z(CLV) + z(ROI) + z(Sharpe), equal weights, no tuning
- CLV (Closing Line Value): LONG = market_avg_entry - trader_avg_entry; SHORT = trader_avg_entry - market_avg_entry. Positive = better price than crowd.
- ROI: total_pnl / total_capital_deployed
- Sharpe: avg_pnl_per_position / stddev_pnl_per_position
- Z-score normalize each metric across the trader population, then sum
- Top 20% = Q5 traders. Quintile assignment (Q1-Q5).
- 30-day training window. Recency > quantity.
- Per-market config: esports min_positions=30 actionable=true; epl min_positions=10 actionable=true; politics min_positions=30 actionable=true; la-liga min_positions=20 actionable=false; ligue-1 min_positions=10 actionable=false; nba not scorable.
- Old scoring.py formula REPLACED, not kept alongside. ExpertiseScore table replaced by LiftScore table. No dual system.
- All functions take a category parameter (category-agnostic design).
- Win rate, weight tuning, extra features, specialist/niche detection are all explicitly excluded from the formula.
- Capital deployed: LONG = size * avg_entry_price; SHORT = size * (1 - avg_entry_price).
- Real-time signal: 0-2 Q5 same side = 1% bankroll; 3+ Q5 same side = 2-3% bankroll; if market price moved past Q5 entry = skip.
- Slippage tracking: log your_entry_price, q5_entry_price, market_avg_price, slippage.

### Claude's Discretion
- Module file organization (lift_metrics.py, lift_scoring.py, lift_queries.py naming)
- DB migration strategy (new table vs alter existing)
- Index design for LiftScore table
- CLI output formatting for analyze command
- How to compute market_avg_entry efficiently (single SQL aggregate per scoring run)
- Whether to keep ExpertiseScore table data or drop it

### Deferred Ideas (OUT OF SCOPE)
- Ingesting EPL/politics/other market data (separate phase)
- Live CLOB price fetching for real-time edge calculation (needs API integration)
- Automated trade execution based on Q5 signals
- Fade detection for reliably bad traders as contrarian signals
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| LIFT-01 | Lift metric computation + replace win_rate_component with CLV/ROI/Sharpe z-score composite | New lift_metrics.py pure functions, LiftScore ORM model, scoring pipeline rewire |
| LIFT-02 | Price-context enrichment on consensus signals: expert avg entry + market price | New columns on SignalSnapshot or enrichment in detection.py |
| LIFT-03 | Analyze command as primary Q5 identification + signal surface | CLI rewrite of `analyze` and `score` commands, Q5 leaderboard output |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy | 2.0+ | ORM for LiftScore table, queries | Already used throughout project |
| Python statistics | stdlib | z-score computation (mean, stdev) | No external dependency needed |
| Decimal | stdlib | Financial precision for all metrics | Project convention -- never float |
| Click | 8.x | CLI commands | Already used for all commands |
| Rich | latest | CLI output formatting | Already used for console output |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| dataclasses | stdlib | Immutable result objects | All score/metric results |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| statistics.stdev | numpy | Overkill -- stdlib stdev is sufficient for z-score on trader populations |
| New LiftScore table | ALTER ExpertiseScore | Clean break preferred -- old schema has wrong columns entirely |

## Architecture Patterns

### Recommended Module Organization
```
src/
  evaluation/
    lift_metrics.py      # Pure functions: compute_clv(), compute_roi(), compute_sharpe(), compute_z_scores()
    scoring.py           # OLD -- no longer imported by pipeline (kept for reference only)
  pipeline/
    scoring_pipeline.py  # Rewired: compute_category_scores() replaces compute_game_scores()
    queries.py           # New: get_positions_for_category(), get_market_avg_entries()
  db/
    models.py            # New: LiftScore model. ExpertiseScore kept but unused.
  cli/
    commands.py          # Rewired: score, leaderboard, analyze commands
  config/
    market_config.py     # NEW: per-market min_positions + actionable flag
```

### Pattern 1: Pure Lift Metrics (No DB, No State)
**What:** All CLV/ROI/Sharpe calculations are pure functions accepting position data + market averages as inputs.
**When to use:** Always -- follows existing project convention from metrics.py, scoring.py.
**Example:**
```python
from decimal import Decimal
from dataclasses import dataclass

@dataclass(frozen=True)
class LiftMetrics:
    clv: Decimal          # Closing Line Value
    roi: Decimal          # Return on Investment
    sharpe: Decimal       # Sharpe ratio
    position_count: int   # Number of positions used

def compute_clv(positions: list, market_avgs: dict[str, Decimal]) -> Decimal:
    """CLV per position, averaged across all positions.
    LONG: market_avg_entry - trader_avg_entry
    SHORT: trader_avg_entry - market_avg_entry
    """
    ...

def compute_roi(positions: list) -> Decimal:
    """total_pnl / total_capital_deployed.
    Capital: LONG = size * avg_entry_price, SHORT = size * (1 - avg_entry_price)
    """
    ...

def compute_sharpe(positions: list) -> Decimal:
    """avg_pnl_per_position / stddev_pnl_per_position.
    Returns Decimal('0') if stddev is 0 (all positions same PnL).
    """
    ...
```

### Pattern 2: Z-Score Normalization Across Population
**What:** Compute z-scores for CLV, ROI, Sharpe across all traders in a category, then sum for composite score.
**When to use:** After computing raw metrics for all traders in a scoring run.
**Example:**
```python
import statistics
from decimal import Decimal

def compute_z_scores(values: dict[str, Decimal]) -> dict[str, Decimal]:
    """Z-score normalize a dict of {trader_address: metric_value}.
    Returns {trader_address: z_score}. Handles n=1 (z=0).
    """
    if len(values) <= 1:
        return {addr: Decimal('0') for addr in values}

    float_vals = [float(v) for v in values.values()]
    mean = statistics.mean(float_vals)
    stdev = statistics.stdev(float_vals)

    if stdev == 0:
        return {addr: Decimal('0') for addr in values}

    return {
        addr: Decimal(str((float(val) - mean) / stdev))
        for addr, val in values.items()
    }

def compute_composite(
    clv_zscores: dict[str, Decimal],
    roi_zscores: dict[str, Decimal],
    sharpe_zscores: dict[str, Decimal],
) -> dict[str, Decimal]:
    """Equal-weight sum: z(CLV) + z(ROI) + z(Sharpe)."""
    all_traders = set(clv_zscores) & set(roi_zscores) & set(sharpe_zscores)
    return {
        addr: clv_zscores[addr] + roi_zscores[addr] + sharpe_zscores[addr]
        for addr in all_traders
    }
```

### Pattern 3: Category-Parametric Scoring Pipeline
**What:** All scoring functions take `category` as a parameter instead of hardcoding eSports/game_slug.
**When to use:** Every scoring and query function.
**Example:**
```python
def compute_category_scores(
    session: Session,
    category: str,  # "esports", "epl", "politics", etc.
    window_days: int = 30,
    now: datetime | None = None,
) -> list[LiftLeaderboardEntry]:
    """Score all traders in a category using 30-day rolling window."""
    config = get_market_config(category)
    if config is None:
        return []  # NBA, unknown categories

    # 1. Get positions in last 30 days for this category
    # 2. Filter traders with >= config.min_positions resolved positions
    # 3. Compute market_avg_entries once
    # 4. Compute CLV, ROI, Sharpe per trader
    # 5. Z-score normalize across population
    # 6. Sum for composite, assign quintiles
    # 7. Persist LiftScore snapshots
    # 8. Return leaderboard
    ...
```

### Pattern 4: Per-Market Configuration
**What:** Static config dict mapping category names to min_positions + actionable flag.
**When to use:** Scoring pipeline entry point to validate categories and set thresholds.
**Example:**
```python
from dataclasses import dataclass

@dataclass(frozen=True)
class MarketConfig:
    min_positions: int
    actionable: bool

MARKET_CONFIGS: dict[str, MarketConfig] = {
    "esports": MarketConfig(min_positions=30, actionable=True),
    "epl": MarketConfig(min_positions=10, actionable=True),
    "politics": MarketConfig(min_positions=30, actionable=True),
    "la-liga": MarketConfig(min_positions=20, actionable=False),
    "ligue-1": MarketConfig(min_positions=10, actionable=False),
}
# NBA intentionally absent -- not scorable

def get_market_config(category: str) -> MarketConfig | None:
    return MARKET_CONFIGS.get(category)
```

### Anti-Patterns to Avoid
- **Keeping dual scoring systems:** Old ExpertiseScore pipeline must not remain active. One scoring path only.
- **Using float for financial math:** All CLV/ROI/Sharpe intermediate values must use Decimal. Convert to float only for statistics.stdev, then back to Decimal immediately.
- **Weight tuning:** 348 experiments proved equal weights work. No configurable weight parameters.
- **Win rate in formula:** Explicitly tested and proven useless. Do not include even as optional.
- **Specialist/niche detection:** Backtest proved skill transfers within categories. No sub-market specialization tracking.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Z-score normalization | Custom mean/stdev loop | `statistics.mean()` + `statistics.stdev()` | Edge cases (n=1, all-same-values) handled correctly |
| Market average entry price | Per-position Python loop | Single SQL aggregate `SELECT market_id, AVG(avg_entry_price) GROUP BY market_id` | O(1) query vs O(n) position loads |
| Rolling window filtering | Custom date math | SQLAlchemy `where(Position.last_trade_timestamp >= cutoff)` | Index-friendly, correct timezone handling |
| Quintile assignment | Manual percentile math | Sort by composite score, assign Q1-Q5 by 20% bands | Simple `math.ceil(rank / total * 5)` |

**Key insight:** The scoring formula is pure arithmetic -- the complexity is in the pipeline plumbing (getting the right positions, filtering by 30-day window, computing market averages efficiently), not in the math itself.

## Common Pitfalls

### Pitfall 1: Division by Zero in Sharpe Ratio
**What goes wrong:** stddev=0 when all positions have identical PnL (or only one position).
**Why it happens:** Single-position traders, or traders with all-win/all-loss at same size.
**How to avoid:** Return Decimal('0') for Sharpe when stdev=0. These traders will have z(Sharpe)=0 and be ranked on CLV+ROI only.
**Warning signs:** NaN or Infinity values appearing in composite scores.

### Pitfall 2: Capital Deployed = 0 for SHORT Positions
**What goes wrong:** ROI = pnl / capital_deployed blows up if capital = size * (1 - avg_entry_price) and avg_entry_price = 1.0.
**Why it happens:** Edge case where trader enters SHORT at price 1.0 (complement = 0).
**How to avoid:** Guard against zero capital deployed -- skip position or use epsilon.
**Warning signs:** Infinite ROI values.

### Pitfall 3: Empty Population Z-Scores
**What goes wrong:** Z-score normalization fails when only 1 trader meets min_positions threshold.
**Why it happens:** New category with sparse data.
**How to avoid:** With n=1, assign z-score=0 for all metrics. Composite=0, Q3 by default.
**Warning signs:** Categories showing exactly one trader with extreme composite scores.

### Pitfall 4: Market Average Includes the Trader Being Scored
**What goes wrong:** CLV is biased because the "crowd price" includes the trader's own entry.
**Why it happens:** Computing `AVG(avg_entry_price)` over all positions in a market.
**How to avoid:** This is ACCEPTABLE per the backtest. The briefing defines market_avg_entry as `AVG(avg_entry_price) FROM positions WHERE direction IN ('LONG','SHORT') GROUP BY market_id`. Including the trader in the average is fine -- with many traders per market, the impact is negligible, and the backtest validated this exact approach.
**Warning signs:** None -- this is by design.

### Pitfall 5: Old ExpertiseScore Data Confusing Queries
**What goes wrong:** `leaderboard` command or signal detection reads from old ExpertiseScore table instead of new LiftScore.
**Why it happens:** Incomplete rewiring -- some query paths still reference ExpertiseScore.
**How to avoid:** Search all imports of ExpertiseScore and either remove or redirect. Keep the model class for migration compatibility but do not write new rows.
**Warning signs:** Leaderboard showing old-format scores after running new `score` command.

### Pitfall 6: 30-Day Window Boundary
**What goes wrong:** Trader has positions straddling the 30-day boundary -- some included, some excluded.
**Why it happens:** Using `last_trade_timestamp` as the filter -- a position entered 35 days ago but with last trade 28 days ago would be included.
**How to avoid:** This is the correct behavior. Filter on `last_trade_timestamp >= now - 30 days`. Positions are included if the trader was still active in them within the window.
**Warning signs:** None -- this matches the backtest's definition of "active in last 30 days."

## Code Examples

### LiftScore ORM Model
```python
class LiftScore(Base):
    """Lift-based trader score per category.

    Replaces ExpertiseScore. Stores z(CLV) + z(ROI) + z(Sharpe) composite
    and individual components for debugging/display.
    """
    __tablename__ = "lift_scores"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trader_address: Mapped[str] = mapped_column(String(42), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)  # "esports", "epl", etc.
    composite_score: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    clv_raw: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    clv_zscore: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    roi_raw: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    roi_zscore: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    sharpe_raw: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    sharpe_zscore: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    quintile: Mapped[int] = mapped_column(nullable=False)  # 1-5, Q5 = top 20%
    position_count: Mapped[int] = mapped_column(nullable=False)
    total_pnl: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    capital_deployed: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    window_start: Mapped[datetime] = mapped_column(nullable=False)
    window_end: Mapped[datetime] = mapped_column(nullable=False)
    computed_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_lift_trader_category", "trader_address", "category"),
        Index("ix_lift_category_composite", "category", "composite_score"),
        Index("ix_lift_category_quintile", "category", "quintile"),
        Index("ix_lift_computed_at", "computed_at"),
    )
```

### Market Average Entry Query
```python
def get_market_avg_entries(
    session: Session,
    category: str,
    window_start: datetime,
) -> dict[str, Decimal]:
    """Compute market_avg_entry for all markets in a category within window.

    Returns {market_id: avg_entry_price} for use in CLV computation.
    Single SQL aggregate -- O(1) query regardless of trader count.
    """
    query = (
        select(
            Position.market_id,
            func.avg(Position.avg_entry_price).label("avg_entry"),
        )
        .join(Market, Position.market_id == Market.condition_id)
        .where(Market.category == category)
        .where(Position.direction.in_(["LONG", "SHORT"]))
        .where(Position.last_trade_timestamp >= window_start)
        .where(Position.avg_entry_price.isnot(None))
        .group_by(Position.market_id)
    )

    results = session.execute(query).all()
    return {row.market_id: Decimal(str(row.avg_entry)) for row in results}
```

### Quintile Assignment
```python
def assign_quintiles(
    composite_scores: dict[str, Decimal],
) -> dict[str, int]:
    """Assign Q1-Q5 based on composite score ranking.
    Q5 = top 20% (best). Q1 = bottom 20%.
    """
    if not composite_scores:
        return {}

    sorted_traders = sorted(composite_scores.items(), key=lambda x: x[1])
    n = len(sorted_traders)

    quintiles = {}
    for rank_idx, (addr, _) in enumerate(sorted_traders):
        # rank_idx 0 = lowest score = Q1
        quintile = min(5, (rank_idx * 5) // n + 1)
        quintiles[addr] = quintile

    return quintiles
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 40% WR + 25% concentration + 20% recency + 15% sample_size | z(CLV) + z(ROI) + z(Sharpe) equal weight | Phase 25 (now) | Predictive power jumps from ~0 to Spearman 0.54-0.67 |
| ExpertiseScore table (game_slug, taxonomy_depth) | LiftScore table (category, quintile) | Phase 25 (now) | Category-agnostic, no taxonomy dependency |
| 90-day recency half-life decay | 30-day hard window | Phase 25 (now) | Recency > quantity, validated by backtest |
| MIN_RESOLVED_MARKETS=5 | Per-category min_positions (10-30) | Phase 25 (now) | Category-specific thresholds validated by 348 experiments |
| Concentration + consistency multiplier | Neither used | Phase 25 (now) | Both degrade performance when added to CLV+ROI+Sharpe |

**Deprecated/outdated:**
- `scoring.py`: Entire module replaced. Keep file for reference but remove all imports from pipeline.
- `concentration.py`: No longer used in formula. Functions may be kept for diagnostic display but not in scoring path.
- `consistency.py`: No longer used in formula. Same treatment.
- `ExpertiseScore` model: No new rows written. Table kept for migration compatibility.

## Key Implementation Details

### Category Mapping
The existing codebase uses `Market.category` (e.g., "eSports", "Sports", "Politics") and `MarketEntity.game` for sub-categorization. The new scoring needs to map between the CONTEXT.md categories ("esports", "epl", "politics") and the database values. Options:

1. **Use Market.category directly** for broad categories (eSports, Politics).
2. **For sub-sport categories** (EPL, La Liga, etc.), use `MarketEntity.tournament` or a tournament-to-league mapping.
3. **Recommendation:** Use `Market.category` for the top-level filter ("eSports" vs "Politics"), then for Sports subcategories, join MarketEntity to filter by tournament/league. This is Claude's discretion per CONTEXT.md.

### Positions Table Has All Required Data
The `positions` table already has: `avg_entry_price`, `pnl`, `size`, `direction`, `resolved`, `outcome`, `last_trade_timestamp`, `market_id`, `trader_address`. No new columns needed on positions.

### Existing Analyze Command
Phase 23's `analyze` command computes entity-level alpha (win rate per team/tournament/game). Phase 25 replaces this with lift-based scoring. The existing `EntityAlpha` table and `analyze` command logic will be replaced, not extended.

## Open Questions

1. **Category-to-config mapping for non-eSports**
   - What we know: Only eSports has position data today. EPL/politics configs are defined but no data exists.
   - What's unclear: How Market.category values map to config keys (e.g., "eSports" in DB vs "esports" in config).
   - Recommendation: Case-insensitive match or explicit mapping dict. Build the plumbing now; it will work when data arrives.

2. **ExpertiseScore table: drop data or keep?**
   - What we know: No new rows will be written. Old data is from the WR-based formula.
   - What's unclear: Whether any diagnostic/audit use case exists.
   - Recommendation: Keep table and data (no migration to drop). Simply stop writing to it and stop reading from it in the pipeline. This is safest and simplest.

3. **Signal detection rewire scope**
   - What we know: `detection.py` currently filters experts by `raw_score > 70`. Phase 25 needs to filter by `quintile == 5` from LiftScore.
   - What's unclear: Whether signal detection is fully in scope or just the price-context enrichment.
   - Recommendation: Signal detection expert filtering must be rewired to use LiftScore Q5, but the core consensus logic stays the same. Price-context enrichment (LIFT-02) adds expert avg entry to signal output.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (no config file -- uses defaults) |
| Config file | None -- pytest auto-discovers tests/ directory |
| Quick run command | `python -m pytest tests/test_lift_metrics.py tests/test_lift_scoring_pipeline.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| LIFT-01a | compute_clv returns correct CLV for LONG/SHORT positions | unit | `python -m pytest tests/test_lift_metrics.py::test_compute_clv -x` | Wave 0 |
| LIFT-01b | compute_roi handles zero capital deployed | unit | `python -m pytest tests/test_lift_metrics.py::test_compute_roi -x` | Wave 0 |
| LIFT-01c | compute_sharpe handles stddev=0 | unit | `python -m pytest tests/test_lift_metrics.py::test_compute_sharpe -x` | Wave 0 |
| LIFT-01d | z-score normalization with n=1, ties, normal population | unit | `python -m pytest tests/test_lift_metrics.py::test_z_scores -x` | Wave 0 |
| LIFT-01e | composite score = z(CLV) + z(ROI) + z(Sharpe) | unit | `python -m pytest tests/test_lift_metrics.py::test_composite -x` | Wave 0 |
| LIFT-01f | quintile assignment Q1-Q5 | unit | `python -m pytest tests/test_lift_metrics.py::test_quintiles -x` | Wave 0 |
| LIFT-01g | LiftScore persisted to DB correctly | integration | `python -m pytest tests/test_lift_scoring_pipeline.py::test_persist -x` | Wave 0 |
| LIFT-01h | 30-day window filters positions correctly | integration | `python -m pytest tests/test_lift_scoring_pipeline.py::test_window -x` | Wave 0 |
| LIFT-01i | Per-category min_positions threshold enforced | integration | `python -m pytest tests/test_lift_scoring_pipeline.py::test_min_positions -x` | Wave 0 |
| LIFT-02a | Signal snapshot includes expert_avg_entry | integration | `python -m pytest tests/test_signal_enrichment.py::test_price_context -x` | Wave 0 |
| LIFT-03a | score command uses new pipeline, writes LiftScore | integration | `python -m pytest tests/test_cli_lift.py::test_score_command -x` | Wave 0 |
| LIFT-03b | leaderboard shows Q5 traders with CLV/ROI/Sharpe | integration | `python -m pytest tests/test_cli_lift.py::test_leaderboard -x` | Wave 0 |
| LIFT-03c | analyze --signals shows Q5 consensus with price context | integration | `python -m pytest tests/test_cli_lift.py::test_analyze_signals -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_lift_metrics.py tests/test_lift_scoring_pipeline.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_lift_metrics.py` -- covers LIFT-01a through LIFT-01f (pure function tests)
- [ ] `tests/test_lift_scoring_pipeline.py` -- covers LIFT-01g through LIFT-01i (pipeline integration)
- [ ] `tests/test_signal_enrichment.py` -- covers LIFT-02a (signal price context)
- [ ] `tests/test_cli_lift.py` -- covers LIFT-03a through LIFT-03c (CLI integration)

## Sources

### Primary (HIGH confidence)
- ANALYZE_BRIEFING.md (Backtest/ANALYZE_BRIEFING.md) -- authoritative source for formula, per-market configs, what NOT to build
- 25-CONTEXT.md -- locked user decisions
- Existing codebase: scoring.py, metrics.py, models.py, scoring_pipeline.py, queries.py, commands.py -- current implementation to replace

### Secondary (MEDIUM confidence)
- Python statistics module documentation -- mean(), stdev() behavior with edge cases

### Tertiary (LOW confidence)
- None -- all critical decisions are locked by backtest evidence

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- pure Python + SQLAlchemy, same as all prior phases
- Architecture: HIGH -- follows established project patterns (pure functions, duck-typed, Decimal arithmetic)
- Pitfalls: HIGH -- most edge cases identified from formula analysis + codebase review
- Formula correctness: HIGH -- exhaustively validated by 348-experiment backtest

**Research date:** 2026-03-22
**Valid until:** 2026-04-22 (stable -- formula is locked, no external dependencies changing)
