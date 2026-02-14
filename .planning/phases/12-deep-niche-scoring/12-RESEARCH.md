# Phase 12: Deep Niche Scoring - Research

**Researched:** 2026-02-14
**Domain:** Multi-level expertise scoring and taxonomy-based aggregation
**Confidence:** HIGH

## Summary

Phase 12 extends the existing expertise scoring system from game-level (depth 1) to tournament-level (depth 2) and team-level (depth 3) scoring. The goal is to surface "hidden specialists" — traders with niche expertise at deep taxonomy levels (e.g., "IEM Katowice specialist" or "NaVi trader") who may have average game-level scores but excel in specific sub-domains.

The existing codebase already has all necessary foundations:
- **4-level taxonomy hierarchy**: TaxonomyNode with depth 0=root, 1=game, 2=tournament, 3=team (src/db/models.py)
- **Position-to-taxonomy linkage**: MarketClassification links positions to taxonomy nodes
- **Pure scoring functions**: calculate_expertise_score() is already depth-agnostic
- **Concentration framework**: Ready to extend from 2-tier (eSports/game) to 4-tier (eSports/game/tournament/team)
- **Leaderboard queries**: get_game_leaderboard() pattern can be replicated for tournament/team

**Primary recommendation:** Extend scoring and querying by taxonomy depth using the existing pure-function architecture. Add new database indexes and query functions for tournament/team scoring. Implement "hidden specialist" detection via multi-depth score comparison.

## Standard Stack

### Core (Already in Use)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy 2.0 | 2.x | ORM and query building | Project standard, already used for TaxonomyNode queries |
| Decimal | stdlib | Financial precision | Project standard for all scoring calculations |
| Pydantic | 2.x | Data validation | Project standard for taxonomy models |

### Supporting (Already in Use)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Click | 8.x | CLI command framework | Extend existing leaderboard command with --depth filter |
| Rich | 13.x | Terminal formatting | Display multi-depth leaderboards and trader breakdowns |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Pure SQL queries | SQLAlchemy ORM | ORM provides type safety and composability already established |
| Custom aggregation logic | Pandas groupby | Project avoids pandas dependency; Decimal+SQLAlchemy is cleaner |

**Installation:**
No new dependencies required. All necessary libraries already in requirements.txt.

## Architecture Patterns

### Recommended Module Structure
```
src/
├── evaluation/
│   ├── scoring.py                 # calculate_expertise_score() (REUSE AS-IS)
│   ├── concentration.py           # EXTEND: add tournament/team concentration
│   └── validation.py              # (existing, no changes)
├── pipeline/
│   ├── scoring_pipeline.py        # EXTEND: add compute_tournament_scores(), compute_team_scores()
│   └── queries.py                 # EXTEND: add get_positions_for_tournament(), get_positions_for_team()
├── cli/
│   ├── commands.py                # EXTEND: add --depth flag to leaderboard command
│   └── formatters.py              # EXTEND: add format_expert_breakdown_table()
└── db/
    └── models.py                  # (existing TaxonomyNode, ExpertiseScore sufficient)
```

### Pattern 1: Taxonomy-Depth-Agnostic Scoring
**What:** Reuse calculate_expertise_score() for all depths by passing filtered positions
**When to use:** Computing scores at game, tournament, or team level
**Example:**
```python
# From src/evaluation/scoring.py (ALREADY EXISTS, NO CHANGES NEEDED)
def calculate_expertise_score(
    positions: list[Any],
    trader_address: str,
    game_slug: str,  # Can be game_slug, tournament_slug, or team_slug
    esports_concentration: Decimal,
    game_concentration: Decimal,  # Rename semantically to "domain_concentration"
    consistency_score: Decimal,
    consistency_signal: str,
    weights: dict[str, Decimal] | None = None,
    now: datetime | None = None,
) -> ExpertiseScoreResult | None:
    # Pure function - works at ANY taxonomy depth
    # Just filter positions before passing
```

### Pattern 2: Slug-Based Position Filtering
**What:** Use TaxonomyNode.slug with LIKE queries to filter positions by depth
**When to use:** Getting positions for tournament or team scoring
**Example:**
```python
# From src/pipeline/queries.py (EXTEND THIS PATTERN)
def get_positions_for_tournament(
    session: Session, tournament_slug: str, trader_address: str | None = None
) -> list[Position]:
    """Query positions in markets under a tournament slug.

    Example tournament_slug: "esports.cs2.iem-katowice"
    """
    query = (
        select(Position)
        .join(MarketClassification, Position.market_id == MarketClassification.market_id)
        .join(TaxonomyNode, MarketClassification.taxonomy_node_id == TaxonomyNode.id)
        .where(TaxonomyNode.slug.like(f"{tournament_slug}%"))  # Matches tournament + teams
    )
    # ... (same pattern as get_positions_for_game)
```

### Pattern 3: Multi-Tier Concentration Calculation
**What:** Extend concentration from 2-tier (eSports/game) to 4-tier (eSports/game/tournament/team)
**When to use:** Computing concentration component for tournament/team scores
**Example:**
```python
# From src/evaluation/concentration.py (EXTEND)
def calculate_tournament_concentration(
    tournament_volume: Decimal, game_volume: Decimal
) -> Decimal:
    """Fraction of game volume in specific tournament (0-1)."""
    if game_volume == Decimal("0"):
        return Decimal("0")
    return tournament_volume / game_volume

def calculate_team_concentration(
    team_volume: Decimal, tournament_volume: Decimal
) -> Decimal:
    """Fraction of tournament volume in specific team (0-1)."""
    if tournament_volume == Decimal("0"):
        return Decimal("0")
    return team_volume / tournament_volume
```

### Pattern 4: Hidden Specialist Detection
**What:** Compare scores across depths to find traders with high deep scores but average shallow scores
**When to use:** Discovering niche experts for CLI display
**Example:**
```python
def identify_hidden_specialists(
    session: Session, game_slug: str, min_depth_score: Decimal = Decimal("75")
) -> list[dict]:
    """Find traders with high tournament/team scores despite average game scores.

    Returns:
        List of dicts with trader_address, game_score, tournament_slug, tournament_score
    """
    # Pseudocode:
    # 1. Get all traders with game score < 60 (average)
    # 2. Get their tournament/team scores
    # 3. Filter to tournament/team score >= 75 (high)
    # 4. Return the delta cases
```

### Anti-Patterns to Avoid
- **Duplicating scoring logic**: DON'T create separate tournament_scoring.py — reuse calculate_expertise_score()
- **Hardcoded depth assumptions**: DON'T assume depth=1 anywhere — parameterize by slug
- **Client-side slug parsing**: DON'T split slugs in Python — use SQL LIKE queries with indexes
- **Denormalization**: DON'T duplicate tournament/team data in ExpertiseScore — use slug as foreign key

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Taxonomy slug generation | Custom slugify() | Use existing TaxonomyNode.slug pattern | Already established: "esports.cs2.iem-katowice" |
| Score aggregation | Custom tree traversal | SQLAlchemy LIKE queries with indexes | Database is faster, leverages existing indexes |
| Multi-depth leaderboards | Nested data structures | Separate queries per depth | Simpler, clearer, testable |
| Concentration tiers | Complex nested calculations | Pure functions per tier | Existing pattern in concentration.py |

**Key insight:** The existing architecture is depth-agnostic by design. Position filtering + pure scoring functions means extending to new depths is mostly query engineering, not scoring algorithm changes.

## Common Pitfalls

### Pitfall 1: Breaking Pure Scoring Functions
**What goes wrong:** Adding depth-specific logic to calculate_expertise_score() breaks composability
**Why it happens:** Temptation to add "if depth == 2" conditionals
**How to avoid:** Keep scoring pure; vary inputs (filtered positions, slug, concentration) not logic
**Warning signs:** Conditionals based on depth, slug parsing inside scoring.py

### Pitfall 2: Index Coverage Gaps
**What goes wrong:** Tournament/team queries become slow without proper indexes
**Why it happens:** Existing indexes are optimized for game-level queries
**How to avoid:** Add composite index on (TaxonomyNode.slug, TaxonomyNode.depth) for LIKE queries
**Warning signs:** EXPLAIN QUERY shows table scans on TaxonomyNode

### Pitfall 3: Concentration Denominator Mismatches
**What goes wrong:** Tournament concentration uses wrong denominator (total volume instead of game volume)
**Why it happens:** Copy-paste from game concentration without adjusting parent scope
**How to avoid:** Always calculate concentration as child_volume / parent_volume
**Warning signs:** Concentrations > 1.0, failing tests

### Pitfall 4: Slug Ambiguity for Cross-Tournament Teams
**What goes wrong:** Team "NaVi" appears in multiple tournaments, unclear which slug to use
**Why it happens:** Team names repeat across tournaments in taxonomy
**How to avoid:** Always use full slug path (e.g., "esports.cs2.iem-katowice.navi"), not just team name
**Warning signs:** Duplicate team scores, confusion in leaderboard display

### Pitfall 5: ExpertiseScore Schema Assumptions
**What goes wrong:** Reusing game_slug column for tournament slugs breaks foreign key semantics
**Why it happens:** Trying to avoid schema changes
**How to avoid:** Rename game_slug to taxonomy_slug (migration) or add taxonomy_depth column
**Warning signs:** Queries filtering on game_slug returning tournament/team scores

## Code Examples

Verified patterns from existing codebase:

### Query Positions by Taxonomy Slug (EXISTING PATTERN)
```python
# From src/pipeline/queries.py:460-494
def get_positions_for_game(
    session: Session, game_slug: str, trader_address: str | None = None
) -> list[Position]:
    """Query positions in markets classified under a specific game slug.

    Uses slug LIKE pattern to capture game and sub-nodes (tournaments, teams).
    """
    query = (
        select(Position)
        .join(MarketClassification, Position.market_id == MarketClassification.market_id)
        .join(TaxonomyNode, MarketClassification.taxonomy_node_id == TaxonomyNode.id)
        .where(TaxonomyNode.slug.like(f"{game_slug}%"))
    )

    if trader_address is not None:
        query = query.where(Position.trader_address == trader_address)

    result = session.execute(query)
    return list(result.scalars().all())

# REUSE THIS PATTERN for get_positions_for_tournament() and get_positions_for_team()
```

### Calculate Concentration (EXTEND THIS)
```python
# From src/evaluation/concentration.py:69-92
def calculate_game_concentration(
    game_volume: Decimal, esports_volume: Decimal
) -> Decimal:
    """Calculate game-level concentration (fraction of eSports volume in specific game)."""
    if esports_volume == Decimal("0"):
        return Decimal("0")
    return game_volume / esports_volume

# ADD SIMILAR FUNCTIONS:
# calculate_tournament_concentration(tournament_volume, game_volume)
# calculate_team_concentration(team_volume, tournament_volume)
```

### Leaderboard Query Pattern (EXISTING PATTERN)
```python
# From src/pipeline/queries.py:338-387
def get_game_leaderboard(
    session: Session, game_slug: str, top_n: int = 20, min_score: Decimal | None = None
) -> list[ExpertiseScore]:
    """Query latest expertise scores for a game leaderboard."""
    # Subquery to find max(computed_at) per trader per game
    subquery = (
        select(
            ExpertiseScore.trader_address,
            func.max(ExpertiseScore.computed_at).label("max_computed_at"),
        )
        .where(ExpertiseScore.game_slug == game_slug)
        .group_by(ExpertiseScore.trader_address)
        .subquery()
    )

    # Main query: join to get latest scores
    query = (
        select(ExpertiseScore)
        .join(
            subquery,
            (ExpertiseScore.trader_address == subquery.c.trader_address)
            & (ExpertiseScore.computed_at == subquery.c.max_computed_at),
        )
        .where(ExpertiseScore.game_slug == game_slug)
    )
    # ... order by percentile_rank DESC, limit top_n

# REPLICATE for get_tournament_leaderboard() and get_team_leaderboard()
```

### Pure Scoring Function (NO CHANGES NEEDED)
```python
# From src/evaluation/scoring.py:166-291
def calculate_expertise_score(
    positions: list[Any],
    trader_address: str,
    game_slug: str,  # Semantically rename to "taxonomy_slug" or "domain_slug"
    esports_concentration: Decimal,
    game_concentration: Decimal,  # Semantically rename to "domain_concentration"
    consistency_score: Decimal,
    consistency_signal: str,
    weights: dict[str, Decimal] | None = None,
    now: datetime | None = None,
) -> ExpertiseScoreResult | None:
    """Calculate composite expertise score from all components.

    DEPTH-AGNOSTIC: Works for game, tournament, or team by varying:
    - positions: Filtered to specific taxonomy scope
    - game_slug: Full taxonomy slug (e.g., "esports.cs2.iem-katowice")
    - concentrations: Calculated at appropriate tier
    """
    # Pure function - NO CHANGES NEEDED for multi-depth support
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Game-only scoring | Multi-depth taxonomy scoring | Phase 12 (2026-02-14) | Discovers niche specialists |
| Hardcoded game_slug | Parameterized taxonomy_slug | Phase 12 (2026-02-14) | Depth-agnostic queries |
| 2-tier concentration | 4-tier concentration | Phase 12 (2026-02-14) | Finer specialization detection |

**Deprecated/outdated:**
- N/A - This is a greenfield extension, not a replacement

## Open Questions

1. **ExpertiseScore schema: Rename game_slug or add taxonomy_depth?**
   - What we know: Current column is `game_slug: Mapped[str]` (line 273 in models.py)
   - What's unclear: Whether to rename to `taxonomy_slug` (breaking change) or add `taxonomy_depth` column
   - Recommendation: Add `taxonomy_depth: Mapped[int]` column and keep `game_slug` renamed to `taxonomy_slug` in single migration. Update all queries to filter on both slug and depth.

2. **Should tournament/team scores inherit game-level consistency?**
   - What we know: Consistency is calculated at "all positions" level, not per-game
   - What's unclear: Whether tournament/team scoring should use same consistency or recalculate
   - Recommendation: Use same consistency (it's trader-wide, not domain-specific). Don't recalculate per-depth.

3. **How to handle teams appearing in multiple tournaments?**
   - What we know: "NaVi" appears in both IEM Katowice and BLAST Premier (esports.yaml)
   - What's unclear: Should team scoring aggregate across tournaments or keep separate?
   - Recommendation: Keep separate per full slug path. "esports.cs2.iem-katowice.navi" vs "esports.cs2.blast-premier.navi" are distinct scoring contexts.

4. **Minimum sample size thresholds for tournament/team scoring?**
   - What we know: Game-level uses MIN_RESOLVED_MARKETS = 5 (scoring.py:42)
   - What's unclear: Should tournament/team use same threshold or lower (fewer markets available)?
   - Recommendation: Use same threshold (5) to maintain statistical validity. Document that deep niches may have fewer qualifying traders.

## Sources

### Primary (HIGH confidence)
- `/Users/macbookair/Documents/project/test/rerun7/GSD_Polymarket/src/db/models.py` - TaxonomyNode schema (lines 126-148), ExpertiseScore schema (lines 262-289)
- `/Users/macbookair/Documents/project/test/rerun7/GSD_Polymarket/src/evaluation/scoring.py` - Pure scoring functions (lines 166-291)
- `/Users/macbookair/Documents/project/test/rerun7/GSD_Polymarket/src/evaluation/concentration.py` - 2-tier concentration pattern (lines 43-92)
- `/Users/macbookair/Documents/project/test/rerun7/GSD_Polymarket/src/pipeline/queries.py` - Slug-based position queries (lines 460-494), leaderboard queries (lines 338-387)
- `/Users/macbookair/Documents/project/test/rerun7/GSD_Polymarket/src/taxonomy/classifier.py` - Node path generation (lines 59-86)
- `/Users/macbookair/Documents/project/test/rerun7/GSD_Polymarket/data/taxonomy/esports.yaml` - 4-level taxonomy structure

### Secondary (MEDIUM confidence)
- Project MEMORY.md - Phase 4 concentration gap fix confirms volume-based concentration is production-validated

### Tertiary (LOW confidence)
- N/A

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries already in requirements.txt, well-tested in v1.0
- Architecture: HIGH - Pure-function pattern is established, depth extension is natural
- Pitfalls: HIGH - Based on existing codebase patterns and SQLAlchemy best practices

**Research date:** 2026-02-14
**Valid until:** 2026-03-14 (30 days - stable stack, architectural extension)
