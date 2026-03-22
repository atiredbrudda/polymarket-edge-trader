# Phase 22: Org-Team Mapping - Research

**Researched:** 2026-03-14
**Domain:** SQLAlchemy data modeling, query layer design, entity-to-trader linkage
**Confidence:** HIGH

## Summary

Phase 22 builds the mapping layer that connects trader trade history to the team/org entities produced by Phase 21. The output of Phase 21 is a `market_entities` table where each row holds `condition_id, team_a, team_b, tournament, game, market_type` for a market. The output of earlier phases includes a `positions` table where each row holds `trader_address, market_id, direction, outcome`. Joining these two tables yields the primitive: "trader X bet on team Y in market Z, and the position resolved as win/loss."

Phase 22's job is to build query functions and a summary model on top of that join — so that Phase 23 can ask "what is trader X's win rate when betting on Natus Vincere?" without doing ad hoc multi-table reasoning at query time. The most natural form for this is a `trader_team_stats` table (or a pure query function) that aggregates win/loss counts per trader per canonical team name.

The key structural insight from reading the codebase: `market_entities.condition_id` joins to `positions.market_id` (which also stores condition_ids), and `positions.outcome` already encodes win/loss/void/flat. No new API calls are needed — this is purely a data reshaping phase over existing tables.

**Primary recommendation:** Build a `TraderTeamStats` ORM model and a `compute_trader_team_stats(session, trader_address)` function that joins positions to market_entities, groups by canonical team name (and game, tournament), and stores win/loss counts. The planner can split this into two plans: model + query logic in plan 01, and a `polymarket team-stats` CLI command in plan 02.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy | 2.0 (already in project) | ORM model + query layer | Project standard for all DB access |
| pytest | already in project | Unit tests | Project standard |

### No New Dependencies
Phase 22 requires zero new library installs. All work is pure SQLAlchemy query authoring and model definition over existing tables.

**Installation:**
```bash
# No new packages needed
```

## Architecture Patterns

### Recommended Project Structure
```
src/
├── extraction/          # Phase 21 (existing) — llm_extractor, normalizer
├── org_mapping/         # NEW Phase 22 package
│   ├── __init__.py
│   ├── queries.py       # compute_trader_team_stats(), get_teams_for_trader()
│   └── models.py        # TraderTeamStats ORM model (optional — see discussion below)
tests/
└── org_mapping/
    ├── __init__.py
    └── test_queries.py
```

### Pattern 1: Join-then-aggregate over positions + market_entities

**What:** `positions` has `(trader_address, market_id, outcome, direction)`. `market_entities` has `(condition_id, team_a, team_b, game, tournament)`. Join on `positions.market_id == market_entities.condition_id`, then pivot team_a/team_b into a "team the trader bet on" field, then group-count wins and losses.

**When to use:** Any time Phase 23 needs contextual win rate per team. This is the central join.

**The pivoting problem — critical design decision:**

A match market has `team_a` and `team_b`. A trade has `direction = LONG` or `SHORT`. In Polymarket binary markets, `LONG` = betting YES and `SHORT` = betting NO. For a market "Will NaVi beat FaZe?", a LONG position means betting on NaVi, a SHORT position means betting on FaZe. The entity extraction records `team_a` as the likely "favorite" or first-named team, but the LLM may order them arbitrarily.

**Resolution:** The safest approach for Phase 22 is to record stats for **both** `team_a` and `team_b` from every resolved match-type position — i.e., treat a position as evidence that the trader "bet on" either team, with the direction indicating which side. Do not attempt to infer "which team the trader was rooting for" at stat-build time; instead record the raw direction per team and let Phase 23's query layer interpret it. However, the simpler model for Phase 23's use case (win-rate per team) is: for match markets, attribute a win to the team the trader bet on (LONG = team_a, SHORT = team_b).

**Example:**
```python
# Source: project SQLAlchemy 2.0 patterns (models.py)
from sqlalchemy import select, func
from src.db.models import Position, MarketEntity

def get_team_win_rates(session: Session, trader_address: str) -> list[dict]:
    """
    Returns list of {team, game, wins, losses, win_rate} for a trader.
    Only includes resolved match-type positions.
    """
    stmt = (
        select(
            MarketEntity.team_a,
            MarketEntity.team_b,
            MarketEntity.game,
            Position.direction,
            Position.outcome,
        )
        .join(Position, Position.market_id == MarketEntity.condition_id)
        .where(
            Position.trader_address == trader_address,
            Position.resolved == True,
            MarketEntity.market_type == "match",
            Position.outcome.in_(["win", "loss"]),
        )
    )
    rows = session.execute(stmt).all()
    # pivot: LONG direction -> trader bet on team_a; SHORT -> trader bet on team_b
    # then group by canonical team name and count wins/losses
    ...
```

### Pattern 2: TraderTeamStats ORM Model (pre-computed summary)

**What:** A `trader_team_stats` table that stores pre-computed win/loss totals per (trader, team, game). Phase 23 queries this table at display time instead of re-joining on every `analyze` call.

**When to use:** If Phase 23 needs to sort traders by "NaVi specialists" or show a leaderboard filtered by team. Pre-computation makes this O(1) lookup instead of a full table scan.

**Schema:**
```python
class TraderTeamStats(Base):
    __tablename__ = "trader_team_stats"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trader_address: Mapped[str] = mapped_column(String(42), nullable=False)
    team_name: Mapped[str] = mapped_column(String(200), nullable=False)
    game: Mapped[str | None] = mapped_column(String(200), nullable=True)
    wins: Mapped[int] = mapped_column(default=0, nullable=False)
    losses: Mapped[int] = mapped_column(default=0, nullable=False)
    total_resolved: Mapped[int] = mapped_column(default=0, nullable=False)
    win_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_team_stats_trader_team", "trader_address", "team_name", unique=True),
        Index("ix_team_stats_team", "team_name"),
    )
```

**Note:** The `unique=True` on (trader_address, team_name) means re-computation upserts in place — same pattern as ExpertiseScore rows in existing code.

### Pattern 3: Pure query functions (no pre-computed table)

**What:** `get_team_stats_for_trader(session, trader_address)` returns a list of team stat dataclasses computed at query time from positions + market_entities join. No intermediate table.

**When to use:** If Phase 23 only ever queries per-trader (not cross-trader by team), the join is fast enough and the extra table is unnecessary complexity.

**Recommendation:** Implement both — pure query function first (easier to test), then a `TraderTeamStats` ORM model that caches results. Plan 01 = query function + model. Plan 02 = `compute-team-stats` CLI command that populates the table.

### Recommended Project Structure (revised)
```
src/
├── extraction/           # Phase 21 (existing)
├── org_mapping/          # NEW Phase 22 package
│   ├── __init__.py
│   ├── queries.py        # get_team_stats_for_trader(), get_teams_for_trader()
│   └── models.py         # TraderTeamStats ORM model
tests/
└── org_mapping/
    ├── __init__.py
    └── test_queries.py   # unit tests with in-memory SQLite
```

### Anti-Patterns to Avoid

- **Storing un-normalized team names:** If the normalizer returned "NaVi" for one market and "Natus Vincere" for another, grouping by team_name breaks. The normalizer already handles this — only store the canonical form. Do NOT call `extract_entities` again in Phase 22.
- **Trying to infer trade side from price:** Prices near 0.9 do not tell you which team the trader backed; `Position.direction` (LONG/SHORT) is the correct field.
- **Foreign keys to market_entities:** Following the Phase 21 precedent, use plain string join on `condition_id` — no FK constraints.
- **Computing stats at every query:** For Phase 23, a "show me all NaVi specialists" query across thousands of traders would be slow without pre-computed rows. Build the `TraderTeamStats` table.
- **Including unresolved positions:** Win rates computed over unresolved positions are meaningless. Always filter `Position.resolved == True` and `Position.outcome IN ('win', 'loss')`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Upsert logic | Custom merge loop | SQLAlchemy `session.merge()` or explicit SELECT-then-UPDATE | Already established pattern in project (see discover command upsert for MarketEntity) |
| Alias normalization | Re-implement alias lookup | `normalizer.py` from Phase 21 is already loaded at module level | Would duplicate `_TEAM_ALIASES` map |
| Win rate calculation | Custom Decimal math | `calculate_win_rate` from `src.evaluation.metrics` already exists | Reuse established pure function |

**Key insight:** The entire Phase 22 is a reshape of existing data. Every building block exists — don't introduce complexity.

## Common Pitfalls

### Pitfall 1: market_type=None rows polluting team stats
**What goes wrong:** `market_entities` rows where `market_type=None` or `market_type="prop"` don't have a clear team_a-vs-team_b match structure. Counting LONG direction as "team_a win" on a prop market (e.g., "Will NaVi win map 1 pistol round?") conflates team support with prop outcome.
**Why it happens:** LLM extraction sets `market_type="prop"` for these but the stats query doesn't filter.
**How to avoid:** Filter `MarketEntity.market_type == "match"` in all team stat queries.
**Warning signs:** Team win rates appear much lower than expected; positions with only one team populated are included.

### Pitfall 2: Double-counting when team appears as both team_a and team_b
**What goes wrong:** A trader bets on NaVi across many markets. In some markets NaVi is `team_a`, in others it's `team_b`. If stats are keyed by team_a alone, half the NaVi history is lost.
**Why it happens:** LLM doesn't guarantee consistent ordering.
**How to avoid:** The stat computation function must check both `team_a` and `team_b` fields to identify which team the position was on, using `Position.direction` to disambiguate. A `LONG` position = bet on `team_a`; a `SHORT` position = bet on `team_b`. This convention must be established in Phase 22 and documented clearly for Phase 23.
**Warning signs:** NaVi stats show only 50% of expected resolved positions.

### Pitfall 3: Void/flat outcomes inflating trade count
**What goes wrong:** `Position.outcome` can be `"void"` or `"flat"` in addition to `"win"` and `"loss"`. Including these in `total_resolved` inflates counts without contributing to win rate.
**Why it happens:** The positions model from Phase 3/18 stores all outcomes.
**How to avoid:** Only count positions where `outcome IN ('win', 'loss')` for win rate calculations. Optionally store `void_count` separately for transparency.
**Warning signs:** Win rate denominator doesn't match wins + losses.

### Pitfall 4: Stale TraderTeamStats after new positions resolve
**What goes wrong:** `compute-team-stats` is run once, then new positions get resolved, and Phase 23 reads stale data.
**Why it happens:** The stats table is not automatically refreshed.
**How to avoid:** The CLI command for Phase 22 must be designed as a full recompute (delete + reinsert or upsert), not incremental. Phase 23's analyze command should note when stats were last computed (`computed_at`).
**Warning signs:** `computed_at` timestamps are days old while new positions exist.

## Code Examples

Verified patterns from existing project code:

### Upsert pattern (from commands.py discover)
```python
# Source: src/cli/commands.py lines 1102-1126
existing = session.get(MarketEntity, None)  # or query by condition_id
if existing:
    existing.team_a = normalized.team_a
    existing.extracted_at = datetime.utcnow()
else:
    entity_row = MarketEntity(condition_id=market.condition_id, ...)
    session.add(entity_row)
session.commit()
```

### Join pattern: positions to market_entities
```python
# Source: project SQLAlchemy 2.0 style (models.py, queries.py)
from sqlalchemy import select
from src.db.models import Position, MarketEntity

stmt = (
    select(Position, MarketEntity)
    .join(MarketEntity, Position.market_id == MarketEntity.condition_id)
    .where(
        Position.trader_address == trader_address,
        Position.resolved == True,
        MarketEntity.market_type == "match",
        Position.outcome.in_(["win", "loss"]),
    )
)
rows = session.execute(stmt).all()
```

### Aggregation pattern (existing style from scoring_pipeline.py)
```python
# Source: src/pipeline/scoring_pipeline.py + src/evaluation/metrics.py
from src.evaluation.metrics import calculate_win_rate
wins = sum(1 for r in rows if r.Position.outcome == "win")
losses = sum(1 for r in rows if r.Position.outcome == "loss")
win_rate = calculate_win_rate(wins, wins + losses)  # returns Decimal
```

### Win rate function (already exists)
```python
# Source: src/evaluation/metrics.py — reuse, do not re-implement
from src.evaluation.metrics import calculate_win_rate
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No entity-level trader stats | TraderTeamStats pre-computed table | Phase 22 (now) | Enables Phase 23 per-team filtering |
| Win rate only over full game taxonomy | Win rate per canonical team name | Phase 22 (now) | Shows "trader is NaVi specialist" not just "CS2 specialist" |

## Open Questions

1. **Should `game` be included in the `TraderTeamStats` unique key?**
   - What we know: Team Liquid appears in CS2, Dota 2, and LoL in esports.yaml. Without game in the key, their stats would be merged.
   - What's unclear: Whether the same canonical team name is intentionally shared or a taxonomy gap.
   - Recommendation: Include `game` in the unique index: `(trader_address, team_name, game)`. Treat Team Liquid CS2 and Team Liquid Dota 2 as separate specializations.

2. **Should tournament-level stats also be computed in Phase 22?**
   - What we know: `market_entities` also stores `tournament`. Phase 23 "Contextual Analyze Command" mentions "win rate per dimension."
   - What's unclear: Whether Phase 23 needs tournament stats or only team stats.
   - Recommendation: Phase 22 builds team stats only. Add `TraderTournamentStats` in Phase 23 if needed, or add it to Phase 22 plan 02 as an optional extension.

3. **What is the join volume?**
   - What we know: ~3,633 trades recovered in Phase 20, JBecker has many more. `market_entities` is populated per discover run — only markets discovered via the discover command have entities.
   - What's unclear: How many markets in `market_entities` vs total markets with positions.
   - Recommendation: Add a diagnostic step in plan 02 that reports join coverage (how many positions have a matching market_entity row).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (existing, no config file detected) |
| Config file | none — run from project root |
| Quick run command | `python -m pytest tests/org_mapping/ -x -q` |
| Full suite command | `python -m pytest tests/ -x -q --ignore=tests/datasources` |

### Phase Requirements -> Test Map

Phase 22 requirements are not yet formally defined in REQUIREMENTS.md (listed as TBD in ROADMAP.md). Based on analysis of what Phase 23 needs:

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MAP-01 | `get_team_stats_for_trader()` returns correct wins/losses from in-memory positions+entities | unit | `python -m pytest tests/org_mapping/test_queries.py::test_team_stats_basic -x` | Wave 0 |
| MAP-02 | LONG direction correctly mapped to team_a, SHORT to team_b | unit | `python -m pytest tests/org_mapping/test_queries.py::test_direction_mapping -x` | Wave 0 |
| MAP-03 | Unresolved/void/flat positions excluded from win rate | unit | `python -m pytest tests/org_mapping/test_queries.py::test_excludes_unresolved -x` | Wave 0 |
| MAP-04 | prop-type markets excluded from team stats | unit | `python -m pytest tests/org_mapping/test_queries.py::test_excludes_prop_markets -x` | Wave 0 |
| MAP-05 | `TraderTeamStats` upsert is idempotent | unit | `python -m pytest tests/org_mapping/test_queries.py::test_upsert_idempotent -x` | Wave 0 |
| MAP-06 | Team names stored using canonical form (not LLM alias) | unit | `python -m pytest tests/org_mapping/test_queries.py::test_canonical_team_names -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/org_mapping/ -x -q`
- **Per wave merge:** `python -m pytest tests/org_mapping/ tests/extraction/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/org_mapping/__init__.py` — package marker
- [ ] `tests/org_mapping/test_queries.py` — covers MAP-01 through MAP-06
- [ ] `src/org_mapping/__init__.py` — package marker
- [ ] `src/org_mapping/queries.py` — query functions
- [ ] `src/org_mapping/models.py` — TraderTeamStats ORM model

## Sources

### Primary (HIGH confidence)
- Direct reading of `src/db/models.py` — confirmed Position, MarketEntity, TraderCategorySummary schemas
- Direct reading of `src/extraction/llm_extractor.py` and `src/extraction/normalizer.py` — confirmed canonical name output
- Direct reading of `src/cli/commands.py` — confirmed existing upsert pattern and discover wiring
- Direct reading of `src/evaluation/scoring.py` and `src/evaluation/metrics.py` — confirmed reusable `calculate_win_rate`
- Direct reading of `data/taxonomy/esports.yaml` — confirmed cross-game team name sharing (Team Liquid, Cloud9, etc.)
- Direct reading of `.planning/phases/21-*/SUMMARY.md` — confirmed Phase 21 deliverables

### Secondary (MEDIUM confidence)
- SQLAlchemy 2.0 join syntax inferred from patterns already used throughout `src/pipeline/queries.py` — consistent with SQLAlchemy 2.0 documentation style

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new libraries, all patterns from existing codebase
- Architecture: HIGH — join path is unambiguous; TraderTeamStats schema is a direct analog of existing summary tables
- Pitfalls: HIGH — all identified pitfalls derived from reading actual data shapes in existing models and extraction code
- Phase scope: HIGH — the "Org-Team Mapping" name and downstream needs are clear from ROADMAP.md note and Phase 23 description

**Research date:** 2026-03-14
**Valid until:** 2026-04-14 (stable domain — no external APIs, pure internal query logic)
