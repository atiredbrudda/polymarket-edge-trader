# Phase 4: Scoring Engine - Research

**Researched:** 2026-02-06
**Domain:** Expertise scoring systems, specialization metrics, composite ranking
**Confidence:** HIGH

## Summary

Phase 4 implements a percentile-based expertise scoring system (0-100) for traders in eSports niches. The scoring combines four components: win rate (dominant ~40%), category concentration, sample size confidence, and recency weighting. Scores are relative/percentile-normalized against the population, not absolute formula outputs. The system distinguishes specialists (focused on specific games) from generalists while scoring both fairly. All scoring uses the validation framework from Phase 3 to tune weights via walk-forward testing.

The standard approach for expertise scoring systems combines domain-specific performance metrics (win rate, PnL) with behavioral indicators (concentration, consistency) and temporal weighting (recency decay). Research shows that domain expertise matters more than algorithmic complexity — the niche hypothesis (focused traders have superior domain knowledge) should drive the scoring design.

**Primary recommendation:** Build a weighted composite score using Decimal arithmetic throughout, store both raw scores and percentile ranks in PerformanceSnapshot, and leverage the existing validation framework to auto-tune weights via historical backtests rather than hardcoding initial values.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Score Formula Weights:**
- Win rate dominant weighting (~40%), remaining split across concentration, recency, sample size
- Moderate recency decay (half-life ~3 months) — balances rewarding history with penalizing inactivity
- Consistency score from Phase 3 factors INTO the expertise score as a multiplier/bonus — consistent traders get boosted, streaky ones penalized
- Initial weight values: Claude's discretion (hardcoded defaults or auto-tuned via validation framework, whichever makes more sense for v1)

**Specialist vs Generalist:**
- Specialization threshold: Claude's discretion based on what the data supports
- Generalists receive a different label only — scores are fair per game, not penalized
- Per-game independent scoring — a trader CAN be specialist in multiple games simultaneously (e.g., CS:GO and Valorant)
- Two-tier specialization tracking: both eSports-level (how focused within eSports overall) AND game-level (how focused within a specific game)

**Leaderboard Design:**
- Both views: default top-N per game AND filterable by minimum score threshold
- Recency decay naturally handles inactive traders — no separate removal mechanism needed
- Each entry includes: score + rank, win rate + PnL, activity level (trade count, unique markets, last active), specialization label
- Data/computation only at this phase — CLI rendering is Phase 7's responsibility

**Score Interpretation:**
- Raw numbers only (0-100) — no named tiers (Expert/Proficient/etc.)
- Scores are relative/percentile-based — normalized against the population, not absolute formula output
- New traders with exactly 5 resolved markets (minimum) scored normally — sample size component naturally gives appropriate weight
- Score history tracked over time — store snapshots to enable trend analysis and "rising star" detection downstream

### Claude's Discretion

1. Initial weight values: Hardcoded defaults OR auto-tuned via validation framework (choose whichever approach makes more sense for v1)
2. Specialization threshold: Determine based on what the data supports (e.g., 70% concentration, or top 20% of distribution)
3. Implementation details for two-tier specialization tracking (eSports-level and game-level)
4. Score snapshot storage strategy (frequency, retention policy)

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.

</user_constraints>

## Standard Stack

Phase 4 uses the existing project stack with no new dependencies.

### Core Libraries (Already in Use)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.11+ | Language | Project standard (Homebrew managed) |
| Decimal | stdlib | Numeric precision | All financial calculations use Decimal (Phase 1 decision) |
| SQLAlchemy | 2.0 | ORM | Project ORM layer, PerformanceSnapshot already exists |
| pytest | Latest | Testing | Project test framework (234 tests passing) |
| dataclasses | stdlib | Immutable results | Established pattern (ConsistencyResult, TraderProfile, etc.) |

### Scoring-Specific Components (No External Libraries)

| Component | Implementation | Purpose |
|-----------|----------------|---------|
| Percentile normalization | Pure Python + Decimal | Rank scores 0-100 relative to population |
| Exponential decay | Math formula | Recency weighting with ~3 month half-life |
| Composite weighting | Weighted sum | Combine 4+ components into single score |
| Sample size adjustment | Confidence multiplier | Penalize small sample sizes per statistical principles |

**Installation:** None required — all components use stdlib or existing dependencies.

## Architecture Patterns

### Recommended Module Structure

```
src/evaluation/
├── metrics.py              # Existing: PnL, win rate, volume (Phase 3)
├── consistency.py          # Existing: Cross-timeframe stability (Phase 3)
├── profiles.py             # Existing: Selective vs active classification (Phase 3)
├── timeframes.py           # Existing: Time window filtering (Phase 3)
├── validation.py           # Existing: Walk-forward weight tuning (Phase 3)
├── scoring.py              # NEW: Composite expertise score calculation
└── concentration.py        # NEW: Category/game concentration metrics

src/db/models.py
├── PerformanceSnapshot     # Existing: Add expertise_score, percentile_rank fields
├── ExpertiseScore          # NEW: Score snapshots for history tracking
└── LeaderboardEntry        # NEW: Cached leaderboard data per game

tests/
├── test_scoring.py         # NEW: Expertise score calculation tests
├── test_concentration.py   # NEW: Concentration metrics tests
└── test_leaderboard.py     # NEW: Leaderboard generation tests
```

### Pattern 1: Pure Function Scoring (Established Pattern)

**What:** Stateless, duck-typed functions following the pattern from metrics.py and consistency.py

**When to use:** All score component calculations (concentration, recency, sample size adjustment)

**Example:**
```python
# src/evaluation/scoring.py
from decimal import Decimal
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class ExpertiseScoreResult:
    """Immutable expertise score result."""
    raw_score: Decimal              # Weighted composite (0-100)
    percentile_rank: Decimal        # Population-relative rank (0-100)
    win_rate_component: Decimal     # Component scores for transparency
    concentration_component: Decimal
    recency_component: Decimal
    sample_size_component: Decimal
    consistency_multiplier: Decimal  # From Phase 3
    specialization_label: str       # "specialist" or "generalist"
    game_slug: str                  # e.g., "esports.cs2"
    trader_address: str

def calculate_expertise_score(
    positions: list[Any],
    trader_address: str,
    game_slug: str,
    all_trader_positions: dict[str, list[Any]],  # For percentile normalization
    weights: dict[str, Decimal],
    now: datetime | None = None,
) -> ExpertiseScoreResult:
    """
    Calculate composite expertise score for a trader in a specific game.

    Args:
        positions: Trader's positions in this game (duck-typed)
        trader_address: Trader wallet address
        game_slug: Game taxonomy slug (e.g., "esports.cs2")
        all_trader_positions: All traders' positions for percentile calculation
        weights: Component weights {"win_rate": Decimal, "concentration": Decimal, ...}
        now: Current time for recency calculation (defaults to utcnow)

    Returns:
        ExpertiseScoreResult with raw score, percentile rank, and components
    """
    # Implementation follows...
```

**Why this pattern:**
- Consistent with existing codebase (metrics.py, consistency.py established this)
- Easy to test (pure functions, no side effects)
- Composable (validation framework can call with different weights)
- Duck-typed inputs work with ORM models or test mocks

### Pattern 2: Percentile Normalization Against Population

**What:** Convert raw scores to percentile ranks (0-100) relative to all traders in the game

**When to use:** After computing raw composite scores, before storing to database

**Example:**
```python
def normalize_scores_to_percentiles(
    raw_scores: dict[str, Decimal]  # trader_address -> raw_score
) -> dict[str, Decimal]:
    """
    Convert raw scores to percentile ranks (0-100).

    Percentile indicates % of traders this trader outperforms.
    Example: 95th percentile = better than 95% of traders.

    Args:
        raw_scores: Dict mapping trader addresses to raw composite scores

    Returns:
        Dict mapping trader addresses to percentile ranks (0-100)
    """
    if not raw_scores:
        return {}

    # Sort traders by raw score (ascending)
    sorted_traders = sorted(raw_scores.items(), key=lambda x: x[1])

    # Compute percentile for each trader
    n = len(sorted_traders)
    percentiles = {}

    for rank, (trader, score) in enumerate(sorted_traders):
        # Percentile = (rank / (n-1)) * 100
        # rank=0 (worst) -> 0th percentile
        # rank=n-1 (best) -> 100th percentile
        if n == 1:
            percentile = Decimal("100")
        else:
            percentile = (Decimal(rank) / Decimal(n - 1)) * Decimal("100")
        percentiles[trader] = percentile

    return percentiles
```

**Why this approach:**
- Scores remain meaningful as population changes (relative, not absolute)
- Matches user requirement: "percentile-based, normalized against the population"
- Standard practice in competitive ranking systems (CAT exam, JEE Main use percentile scoring)

### Pattern 3: Exponential Recency Decay

**What:** Time-weighted scoring where recent performance counts more than old activity

**When to use:** When calculating recency component of expertise score

**Example:**
```python
def calculate_recency_weight(
    last_trade_timestamp: datetime,
    now: datetime,
    half_life_days: int = 90,  # ~3 months per user decision
) -> Decimal:
    """
    Calculate recency weight using exponential decay.

    Formula: weight = 0.5 ^ (days_since / half_life_days)

    Examples:
        - Last trade today: weight = 1.0
        - Last trade 90 days ago: weight = 0.5
        - Last trade 180 days ago: weight = 0.25
        - Last trade 270 days ago: weight = 0.125

    Args:
        last_trade_timestamp: Timestamp of trader's most recent trade
        now: Current time for recency calculation
        half_life_days: Days until weight drops to 0.5 (default: 90)

    Returns:
        Decimal weight (0-1), higher = more recent activity
    """
    days_since = (now - last_trade_timestamp).days

    if days_since < 0:
        # Future timestamp (shouldn't happen, but handle gracefully)
        return Decimal("1.0")

    if days_since == 0:
        # Same day
        return Decimal("1.0")

    # Exponential decay: weight = 0.5 ^ (t / half_life)
    # Use logarithms for Decimal precision
    # weight = exp(ln(0.5) * t / half_life)
    import math
    exponent = -math.log(2) * days_since / half_life_days
    weight_float = math.exp(exponent)

    return Decimal(str(weight_float))
```

**Why exponential decay:**
- Industry standard for time-weighted attribution (marketing, sports analytics)
- Natural decay curve balances rewarding history with penalizing inactivity
- Half-life parameter (90 days) is intuitive and tunable

### Pattern 4: Sample Size Confidence Adjustment

**What:** Reduce scores for traders with small sample sizes to reflect statistical uncertainty

**When to use:** When computing sample_size_component of expertise score

**Example:**
```python
def calculate_sample_size_confidence(
    resolved_market_count: int,
    min_threshold: int = 5,
    full_confidence_threshold: int = 30,
) -> Decimal:
    """
    Calculate confidence multiplier based on sample size.

    Uses sigmoid-like curve:
    - Below min_threshold (5): Not scored (enforced upstream)
    - At min_threshold (5): ~30% confidence
    - At 15 markets: ~65% confidence
    - At full_confidence_threshold (30): ~95% confidence
    - Above 30: Asymptotically approaches 100%

    Formula: confidence = 1 - exp(-k * (n - min_threshold))
    Where k is tuned so confidence reaches ~95% at full_confidence_threshold

    Args:
        resolved_market_count: Number of resolved markets trader participated in
        min_threshold: Minimum for scoring (default: 5 per user decision)
        full_confidence_threshold: Markets needed for ~95% confidence (default: 30)

    Returns:
        Decimal confidence (0-1), higher = more statistical confidence
    """
    if resolved_market_count < min_threshold:
        # Below minimum, shouldn't be scored
        return Decimal("0")

    if resolved_market_count >= full_confidence_threshold:
        # Full confidence
        return Decimal("1.0")

    # Exponential growth: 1 - exp(-k * (n - min_threshold))
    # Solve for k such that confidence = 0.95 at full_confidence_threshold
    # 0.95 = 1 - exp(-k * (30 - 5))
    # exp(-k * 25) = 0.05
    # -k * 25 = ln(0.05)
    # k = -ln(0.05) / 25 ≈ 0.1198

    import math
    k = -math.log(0.05) / (full_confidence_threshold - min_threshold)

    n_adjusted = resolved_market_count - min_threshold
    confidence_float = 1 - math.exp(-k * n_adjusted)

    return Decimal(str(confidence_float))
```

**Why this approach:**
- Statistically sound: More data = higher confidence
- Matches user requirement: "minimum sample size (5+ resolved markets) before scoring"
- Gradual curve prevents sharp cliff at thresholds
- Tunable parameters (min=5, full=30) based on what data supports

### Pattern 5: Two-Tier Specialization Detection

**What:** Track specialization at both eSports-level (across all games) and game-level (within specific game)

**When to use:** When classifying traders as specialists vs generalists

**Example:**
```python
@dataclass(frozen=True)
class SpecializationProfile:
    """Two-tier specialization classification."""
    esports_level: str         # "specialist" or "generalist" (within eSports overall)
    game_level: str            # "specialist" or "generalist" (within this game)
    esports_concentration: Decimal  # % of total volume in eSports
    game_concentration: Decimal     # % of eSports volume in this game
    primary_game: str | None   # Game slug with highest concentration (if specialist)

def classify_specialization(
    esports_positions: list[Any],      # All eSports positions
    game_positions: list[Any],          # Positions in specific game
    all_category_positions: list[Any],  # Positions across ALL categories
    game_slug: str,
    esports_threshold: Decimal = Decimal("0.7"),  # 70% in eSports = specialist
    game_threshold: Decimal = Decimal("0.7"),     # 70% in one game = specialist
) -> SpecializationProfile:
    """
    Classify trader specialization at two levels.

    eSports-level: % of total trading volume in eSports category
    Game-level: % of eSports volume in this specific game

    Args:
        esports_positions: All positions in eSports category
        game_positions: Positions in specific game
        all_category_positions: All positions across all Polymarket categories
        game_slug: Game taxonomy slug
        esports_threshold: Concentration needed for eSports specialist (default: 0.7)
        game_threshold: Concentration needed for game specialist (default: 0.7)

    Returns:
        SpecializationProfile with two-tier classification
    """
    # Calculate total volumes (use existing calculate_total_volume from metrics.py)
    from src.evaluation.metrics import calculate_total_volume

    # Extract trades from positions (duck-typed, assume positions have .trades attribute)
    all_trades = []
    for p in all_category_positions:
        all_trades.extend(p.trades if hasattr(p, 'trades') else [])

    esports_trades = []
    for p in esports_positions:
        esports_trades.extend(p.trades if hasattr(p, 'trades') else [])

    game_trades = []
    for p in game_positions:
        game_trades.extend(p.trades if hasattr(p, 'trades') else [])

    total_volume = calculate_total_volume(all_trades)
    esports_volume = calculate_total_volume(esports_trades)
    game_volume = calculate_total_volume(game_trades)

    # eSports-level concentration
    if total_volume == Decimal("0"):
        esports_concentration = Decimal("0")
    else:
        esports_concentration = esports_volume / total_volume

    # Game-level concentration
    if esports_volume == Decimal("0"):
        game_concentration = Decimal("0")
    else:
        game_concentration = game_volume / esports_volume

    # Classify eSports-level
    esports_level = "specialist" if esports_concentration >= esports_threshold else "generalist"

    # Classify game-level
    game_level = "specialist" if game_concentration >= game_threshold else "generalist"

    return SpecializationProfile(
        esports_level=esports_level,
        game_level=game_level,
        esports_concentration=esports_concentration,
        game_concentration=game_concentration,
        primary_game=game_slug if game_level == "specialist" else None,
    )
```

**Why two-tier tracking:**
- Matches user requirement: "both eSports-level AND game-level" specialization
- Enables nuanced detection: A trader can be eSports specialist (focused on eSports) but game generalist (plays multiple games)
- Concentration-based approach is objective and quantifiable

### Anti-Patterns to Avoid

**1. Float Arithmetic for Scores:** All scoring must use Decimal (project standard, financial precision)

**2. Absolute Score Thresholds:** Don't hardcode "90 = Expert" tiers. User explicitly requested percentile-based, relative scoring.

**3. Ignoring Consistency from Phase 3:** Consistency score MUST factor into expertise score as multiplier/bonus per user decision.

**4. Single-Pass Scoring:** Must compute raw scores for ALL traders in a game FIRST, THEN percentile-normalize. Can't compute percentile for one trader in isolation.

**5. Direct ORM Dependencies in Scoring Logic:** Scoring functions should be pure and duck-typed (like metrics.py). Database operations go in separate pipeline/orchestration layer.

## Don't Hand-Roll

Problems that look simple but have existing solutions or established patterns in this codebase:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Spearman correlation for weight validation | Custom rank correlation | `validation.py::_spearman_correlation` | Already implemented for validation framework (Phase 3) |
| Timeframe filtering | Custom date range logic | `timeframes.py::filter_positions_by_window` | Existing tested implementation |
| Win rate calculation | New win rate logic | `metrics.py::calculate_win_rate` | Pure function, tested in Phase 3 |
| Position aggregation by trader | Manual grouping loops | `pipeline/queries.py::get_positions_by_timeframe` | ORM queries with indexes |
| Sample size thresholds | Arbitrary numbers | Statistical confidence formulas | Use established statistical principles (see Pattern 4) |
| Percentile calculation | Custom ranking | Standard percentile formula | Well-defined mathematical operation (see Pattern 2) |

**Key insight:** This project has strong foundations from Phases 1-3. Scoring should compose existing primitives (metrics, consistency, timeframes) rather than rebuilding them.

## Common Pitfalls

### Pitfall 1: Percentile vs Percentage Confusion

**What goes wrong:** Treating percentile rank as a percentage score (e.g., "90th percentile" as "90% correct")

**Why it happens:** Both use 0-100 scale, easy to conflate

**How to avoid:**
- Store both raw_score and percentile_rank in separate fields
- Document clearly: percentile = "better than X% of traders", not "X% performance"
- Use clear naming: `percentile_rank` not `score_percentage`

**Warning signs:** Documentation or variable names conflating the two concepts

### Pitfall 2: Population Drift Without Re-normalization

**What goes wrong:** Computing percentiles once at score creation, never updating as population changes

**Why it happens:** Percentiles depend on the full population — adding/removing traders changes everyone's rank

**How to avoid:**
- Re-compute percentiles on each scoring run (acceptable since it's Phase 7 CLI display, not real-time)
- OR: Store generation timestamp with percentile and flag stale percentiles
- Document: "Percentiles are snapshot-in-time relative to scoring run population"

**Warning signs:** Percentile ranks sum to more/less than expected across population

### Pitfall 3: Ignoring Minimum Sample Size Before Scoring

**What goes wrong:** Scoring traders with 1-2 resolved markets, giving them extreme percentile ranks

**Why it happens:** Small samples create high variance (lucky beginner with 2/2 wins ranks above expert with 65/100)

**How to avoid:**
- Filter out traders with < 5 resolved markets BEFORE computing scores (user decision: "minimum sample size")
- Return null/None for expertise score if below threshold
- Document clearly in function signatures and validation

**Warning signs:** Leaderboards dominated by traders with 2-3 markets

### Pitfall 4: Recency Decay on Unresolved Positions

**What goes wrong:** Using last_trade_timestamp for recency when position is still open (unresolved)

**Why it happens:** Timestamps reflect last activity, not when performance was determined

**How to avoid:**
- For recency weighting, only consider RESOLVED positions' timestamps
- Unresolved positions shouldn't affect historical recency (performance unknown)
- Use last_resolved_timestamp or filter to resolved=True before finding max timestamp

**Warning signs:** Active traders in unresolved markets getting recency boost before outcomes known

### Pitfall 5: Consistency Multiplier Applied Before Percentile Normalization

**What goes wrong:** Applying consistency multiplier to raw score, THEN percentile-normalizing (breaks population comparison)

**Why it happens:** Natural to think "boost score, then rank"

**How to avoid:**
- Apply consistency as component in raw score formula
- Percentile normalization happens AFTER all components weighted
- Order: Components → Raw Score → Percentile Rank → Store both

**Warning signs:** Percentile ranks don't match expected distribution (not uniform across population)

### Pitfall 6: Not Tracking Score History

**What goes wrong:** Overwriting previous scores, losing ability to detect "rising stars" or trajectory

**Why it happens:** Simple to update one row instead of inserting historical snapshots

**How to avoid:**
- User explicitly requested: "Score history tracked over time"
- Create ExpertiseScore model (separate from PerformanceSnapshot) for snapshots
- Store: trader_address, game_slug, score, percentile_rank, computed_at timestamp
- Enable Phase 5 to query score changes over time

**Warning signs:** Cannot answer "which traders improved most in last 30 days?"

## Code Examples

### Example 1: Composite Score Calculation

```python
# src/evaluation/scoring.py

def calculate_expertise_score(
    positions: list[Any],
    trader_address: str,
    game_slug: str,
    all_trader_positions: dict[str, list[Any]],
    weights: dict[str, Decimal],
    now: datetime | None = None,
) -> ExpertiseScoreResult:
    """
    Calculate composite expertise score combining 4+ components.

    Components:
    1. Win rate (dominant ~40% weight)
    2. Category concentration (game-level focus)
    3. Recency (exponential decay, 90-day half-life)
    4. Sample size confidence (statistical adjustment)
    5. Consistency multiplier (from Phase 3)

    Args:
        positions: Trader's positions in this game
        trader_address: Trader wallet address
        game_slug: Game taxonomy slug
        all_trader_positions: All traders in game for percentile calculation
        weights: Component weights (must sum to 1.0)
        now: Current time for recency (defaults to utcnow)

    Returns:
        ExpertiseScoreResult with raw score, percentile, and components
    """
    from src.evaluation.metrics import calculate_win_rate
    from src.evaluation.consistency import calculate_consistency
    from src.evaluation.timeframes import get_all_timeframe_snapshots

    if now is None:
        now = datetime.utcnow()

    # Filter to resolved positions only
    resolved_positions = [p for p in positions if p.resolved and p.outcome != "void"]

    # Enforce minimum sample size (5+ resolved markets)
    if len(resolved_positions) < 5:
        # Below threshold, don't score
        return None  # Or return ExpertiseScoreResult with score=0, percentile=None

    # Component 1: Win rate
    win_rate_result = calculate_win_rate(resolved_positions)
    win_rate = win_rate_result["win_rate"] or Decimal("0")  # Handle None
    # Normalize to 0-100 scale (already percentage)
    win_rate_component = win_rate * weights["win_rate"]

    # Component 2: Concentration (game-level)
    # Computed via concentration.py helper
    concentration = calculate_game_concentration(trader_address, game_slug, session)
    concentration_component = concentration * Decimal("100") * weights["concentration"]

    # Component 3: Recency
    last_resolved_timestamp = max(p.last_trade_timestamp for p in resolved_positions)
    recency_weight = calculate_recency_weight(last_resolved_timestamp, now, half_life_days=90)
    recency_component = recency_weight * Decimal("100") * weights["recency"]

    # Component 4: Sample size confidence
    sample_size_confidence = calculate_sample_size_confidence(
        resolved_market_count=len(resolved_positions),
        min_threshold=5,
        full_confidence_threshold=30,
    )
    sample_size_component = sample_size_confidence * Decimal("100") * weights["sample_size"]

    # Compute raw composite score (weighted sum)
    raw_score = (
        win_rate_component +
        concentration_component +
        recency_component +
        sample_size_component
    )

    # Component 5: Consistency multiplier (from Phase 3)
    # Get timeframe snapshots for consistency calculation
    positions_by_timeframe = get_all_timeframe_snapshots(positions, now=now)
    profile_type = "active"  # Get from trader profile (Phase 3)
    consistency_result = calculate_consistency(positions_by_timeframe, profile_type)

    # Consistency score (0-100) -> multiplier (0.9 to 1.1)
    # Consistent traders get boost, streaky traders get penalty
    # Example: 80+ consistency -> 1.05x, <40 consistency -> 0.95x
    if consistency_result.consistency_score >= Decimal("80"):
        consistency_multiplier = Decimal("1.05")
    elif consistency_result.consistency_score < Decimal("40"):
        consistency_multiplier = Decimal("0.95")
    else:
        consistency_multiplier = Decimal("1.0")

    raw_score = raw_score * consistency_multiplier

    # Clamp raw score to 0-100
    raw_score = max(Decimal("0"), min(Decimal("100"), raw_score))

    # Percentile normalization (computed separately, see Example 2)
    percentile_rank = None  # Computed in batch after all raw scores

    # Specialization classification
    specialization = classify_specialization(
        esports_positions=get_esports_positions(trader_address, session),
        game_positions=positions,
        all_category_positions=get_all_positions(trader_address, session),
        game_slug=game_slug,
    )
    specialization_label = f"{specialization.esports_level}/{specialization.game_level}"

    return ExpertiseScoreResult(
        raw_score=raw_score,
        percentile_rank=percentile_rank,  # Set in batch normalization
        win_rate_component=win_rate_component,
        concentration_component=concentration_component,
        recency_component=recency_component,
        sample_size_component=sample_size_component,
        consistency_multiplier=consistency_multiplier,
        specialization_label=specialization_label,
        game_slug=game_slug,
        trader_address=trader_address,
    )
```

### Example 2: Batch Percentile Normalization

```python
# src/evaluation/scoring.py

def compute_game_leaderboard(
    game_slug: str,
    session: Session,
    weights: dict[str, Decimal],
    now: datetime | None = None,
) -> list[ExpertiseScoreResult]:
    """
    Compute expertise scores for all traders in a game, with percentile ranks.

    Process:
    1. Get all traders with positions in this game
    2. Calculate raw scores for each trader
    3. Percentile-normalize across population
    4. Return ranked list

    Args:
        game_slug: Game taxonomy slug
        session: Database session
        weights: Scoring component weights
        now: Current time for recency

    Returns:
        List of ExpertiseScoreResult, sorted by percentile_rank descending
    """
    # Get all traders in this game
    traders = get_traders_for_game(game_slug, session)

    # Calculate raw scores for each trader
    raw_scores = {}
    score_results = {}

    for trader_address in traders:
        positions = get_trader_game_positions(trader_address, game_slug, session)

        score_result = calculate_expertise_score(
            positions=positions,
            trader_address=trader_address,
            game_slug=game_slug,
            all_trader_positions={},  # Not needed for raw score
            weights=weights,
            now=now,
        )

        if score_result is not None:  # Passed minimum sample size
            raw_scores[trader_address] = score_result.raw_score
            score_results[trader_address] = score_result

    # Percentile normalization
    percentiles = normalize_scores_to_percentiles(raw_scores)

    # Update score results with percentile ranks
    final_results = []
    for trader_address, score_result in score_results.items():
        # Create updated result with percentile
        updated_result = ExpertiseScoreResult(
            raw_score=score_result.raw_score,
            percentile_rank=percentiles[trader_address],
            win_rate_component=score_result.win_rate_component,
            concentration_component=score_result.concentration_component,
            recency_component=score_result.recency_component,
            sample_size_component=score_result.sample_size_component,
            consistency_multiplier=score_result.consistency_multiplier,
            specialization_label=score_result.specialization_label,
            game_slug=score_result.game_slug,
            trader_address=score_result.trader_address,
        )
        final_results.append(updated_result)

    # Sort by percentile rank (descending)
    final_results.sort(key=lambda x: x.percentile_rank, reverse=True)

    return final_results
```

### Example 3: Weight Tuning via Validation Framework

```python
# scripts/tune_scoring_weights.py

from decimal import Decimal
from src.evaluation.validation import run_validation
from src.pipeline.queries import get_all_positions

def tune_weights():
    """
    Use walk-forward validation to find optimal scoring weights.

    Tests multiple weight configurations, measures prediction accuracy
    via Spearman correlation between train and test scores.
    """
    # Get all positions for validation
    session = get_session()
    positions = get_all_positions(session)

    # Define weight configurations to test
    weight_configs = [
        # Win rate dominant
        {"win_rate": Decimal("0.4"), "concentration": Decimal("0.2"),
         "recency": Decimal("0.2"), "sample_size": Decimal("0.2")},

        # Win rate even more dominant
        {"win_rate": Decimal("0.5"), "concentration": Decimal("0.2"),
         "recency": Decimal("0.15"), "sample_size": Decimal("0.15")},

        # Concentration emphasized
        {"win_rate": Decimal("0.35"), "concentration": Decimal("0.3"),
         "recency": Decimal("0.2"), "sample_size": Decimal("0.15")},
    ]

    best_correlation = Decimal("-1")
    best_weights = None

    for weights in weight_configs:
        # Run validation with these weights
        result = run_validation(
            positions=positions,
            weights=weights,
            n_folds=5,
            test_window_days=90,
            min_train_days=90,
            metric_fn=None,  # Use default (PnL-based for now)
        )

        # Check aggregate correlation
        correlation = result.aggregate_scores.get("correlation", Decimal("0"))

        print(f"Weights: {weights}")
        print(f"  Correlation: {correlation}")
        print(f"  Rank accuracy: {result.aggregate_scores.get('rank_accuracy')}")
        print()

        if correlation > best_correlation:
            best_correlation = correlation
            best_weights = weights

    print(f"Best weights: {best_weights}")
    print(f"Best correlation: {best_correlation}")

    return best_weights
```

## State of the Art

### Current Approach (2026)

| Domain | Current Best Practice | Source |
|--------|----------------------|--------|
| Expertise Scoring | Composite scores with domain-specific metrics + behavioral indicators | ML framework research ([Management Science](https://pubsonline.informs.org/doi/10.1287/mnsc.2021.03357)) |
| Recency Weighting | Exponential decay with configurable half-life (0.5^(t/half_life)) | Time-decay attribution ([PlainSignal](https://plainsignal.com/glossary/time-decay-attribution)) |
| Percentile Normalization | Population-relative ranking (percentile = rank/(n-1) * 100) | CAT/JEE exam systems ([CollegeDekho](https://www.collegedekho.com/articles/cat-normalization-process/)) |
| Sample Size Confidence | Exponential growth curve (1 - exp(-k*(n-min))) | Statistical confidence principles ([Fiveable](https://fiveable.me/key-terms/ap-stats/minimum-sample-size)) |
| Trading Performance | Sharpe ratio, max drawdown, profit factor, win-loss ratios | Algorithmic trading metrics ([QuantifiedStrategies](https://www.quantifiedstrategies.com/trading-performance/)) |

### Evolution Over Time

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual tier assignment (Expert/Intermediate/Novice) | Percentile-based continuous scoring | 2020s with ML adoption | More granular, objective, population-relative |
| Equal weighting of all components | Validated weight tuning via backtests | 2020s with validation frameworks | Empirically optimized, not arbitrary |
| Static scores (compute once) | Time-series score tracking | Modern analytics era | Enables trajectory/momentum detection |
| Absolute thresholds (>90 = expert) | Population-relative percentiles | Competitive exam systems (CAT, JEE) | Fair as population grows/changes |

**Deprecated/outdated:**
- Named tiers (Expert/Proficient/Beginner): User explicitly rejected this — use raw 0-100 scores and percentiles only
- Simple linear combination without validation: Modern approach uses walk-forward validation to tune weights empirically

## Weight Recommendations

Based on user decisions and research:

### Initial Default Weights (v1 Hardcoded)

If choosing hardcoded defaults instead of auto-tuning for v1:

```python
DEFAULT_WEIGHTS = {
    "win_rate": Decimal("0.40"),        # Dominant component (user decision)
    "concentration": Decimal("0.25"),   # Rewards specialists (niche hypothesis)
    "recency": Decimal("0.20"),         # Moderate weight (keeps leaderboard current)
    "sample_size": Decimal("0.15"),     # Statistical confidence adjustment
}
```

**Rationale:**
- Win rate dominant at 40% (user decision: "~40%")
- Concentration high at 25% (user: "niche hypothesis is core")
- Recency moderate at 20% (user: "moderate recency decay")
- Sample size smaller at 15% (adjustment factor, not performance metric)

### Auto-Tuning Approach (Recommended)

**Better for v1:** Use validation framework to find optimal weights empirically.

**Process:**
1. Define weight search space (keep win_rate >= 0.35, vary others)
2. Grid search or random search over weight configurations
3. Evaluate each via walk-forward validation (5 folds, 90-day test windows)
4. Select weights with highest Spearman correlation (train/test score agreement)
5. Store tuned weights in config file or database

**Advantages:**
- Data-driven, not arbitrary
- Validation framework already built (Phase 3)
- Can re-tune as more data accumulates
- Avoids premature optimization

**Recommendation:** Start with auto-tuning. The infrastructure exists (validation.py), and empirical optimization is superior to guessing.

## Open Questions

### 1. Game Patch Tracking for Recency Adjustment

**What we know:** User mentioned "Game patch tracking integration" as a Phase 4 concern in STATE.md

**What's unclear:** How to incorporate patch releases into scoring (reset recency? discount pre-patch performance?)

**Recommendation:**
- Phase 4 v1: Ignore patch tracking (recency decay alone handles this — old performance naturally decays)
- Phase 4 v2 (future): Add optional patch-aware recency weighting (heavier decay across patch boundaries)
- Need reliable source for patch release dates (game-specific APIs or manual YAML updates)

### 2. Handling Traders Active in Multiple Games

**What we know:** User decision: "Per-game independent scoring — trader CAN be specialist in multiple games"

**What's unclear:** Should cross-game performance influence individual game scores? (e.g., CS:GO expert starting Valorant)

**Recommendation:**
- Phase 4: Keep games completely independent (score CS:GO performance based only on CS:GO positions)
- Phase 5 (Signal Detection): Could add "proven in similar game" as signal enhancer
- Justification: Clean separation of concerns, easier to explain/validate

### 3. Percentile Staleness Threshold

**What we know:** Percentiles shift as population changes

**What's unclear:** How often to re-compute percentiles? When to flag as stale?

**Recommendation:**
- Phase 4: Re-compute on every scoring run (acceptable for Phase 7 CLI display, not real-time)
- Store `percentile_computed_at` timestamp alongside percentile_rank
- Phase 7: Add flag if percentile is >7 days old (warns user it may be outdated)

## Sources

### Primary (HIGH confidence)

- [Management Science: ML Framework for Assessing Expert Decisions](https://pubsonline.informs.org/doi/10.1287/mnsc.2021.03357) - Expert assessment methodology
- [PlainSignal: Time-Decay Attribution](https://plainsignal.com/glossary/time-decay-attribution) - Recency weighting formulas
- [CollegeDekho: CAT Normalization Process](https://www.collegedekho.com/articles/cat-normalization-process/) - Percentile normalization approach
- [Fiveable: Minimum Sample Size](https://fiveable.me/key-terms/ap-stats/minimum-sample-size) - Statistical confidence principles
- [QuantifiedStrategies: Trading Performance Metrics](https://www.quantifiedstrategies.com/trading-performance/) - Win rate, Sharpe ratio, max drawdown

### Secondary (MEDIUM confidence)

- [Customers.ai: Recency-Weighted Scoring](https://customers.ai/recency-weighted-scoring) - Recency weighting applications
- [Hardball Times: Math of Weighting Past Results](https://tht.fangraphs.com/the-math-of-weighting-past-results/) - Time-weighting in sports analytics
- [Towards Data Science: Domain Expertise in ML](https://towardsdatascience.com/domain-expert-is-an-essential-block-of-a-robust-ml-system-a29fd1576832/) - Importance of domain knowledge in scoring

### Codebase (HIGH confidence)

- `src/evaluation/metrics.py` - Pure function pattern for PnL, win rate, volume
- `src/evaluation/consistency.py` - ConsistencyResult dataclass, cross-timeframe stability
- `src/evaluation/validation.py` - Walk-forward validation, Spearman correlation
- `src/evaluation/timeframes.py` - Time window filtering (7d/30d/90d/all)
- `src/db/models.py` - PerformanceSnapshot model (add expertise_score fields here)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All stdlib/existing dependencies, no new libraries
- Architecture: HIGH - Follows established pure-function, duck-typed patterns from Phase 3
- Scoring formulas: MEDIUM-HIGH - Research validates approach, user decisions provide constraints
- Weight tuning: HIGH - Validation framework exists and is tested
- Percentile normalization: HIGH - Well-defined mathematical operation, industry-standard

**Research date:** 2026-02-06
**Valid until:** ~60 days (stable domain — scoring methodology doesn't change rapidly)

**Next steps for planner:**
1. Use patterns from this research to structure PLAN.md files
2. Prioritize auto-tuned weights over hardcoded defaults (validation framework ready)
3. Follow pure-function, duck-typed pattern (consistency with metrics.py/consistency.py)
4. Store both raw_score and percentile_rank in PerformanceSnapshot
5. Create separate ExpertiseScore model for score history tracking
