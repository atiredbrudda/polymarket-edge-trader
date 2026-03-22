# Phase 23: Contextual Analyze Command - Research

**Researched:** 2026-03-14
**Domain:** CLI command design, SQLAlchemy query patterns, entity-pivot work queue, pausable/resumable crawler state
**Confidence:** HIGH (all findings from direct codebase inspection)

## Summary

Phase 23 builds a `polymarket analyze` command with two modes. Batch mode (no flags) runs entity-level win rate analysis for traders discovered in the most recent `discover` run. Crawler mode (`--crawl`) exhausts all known entities from `market_entities` across all traders, with pausable/resumable state.

The codebase provides clear patterns for everything this phase needs. The `get_team_stats_for_trader()` function in `src/org_mapping/queries.py` already computes per-team win rates via a Position-MarketEntity join. Phase 23 extends this concept by pivoting the `market_entities` table into a work queue (entity_type × entity_name × game combinations) and attaches an `entity_alpha` ledger table to record results. The hardest design question is how to define "latest discover batch" — currently `discover_traders_from_market` returns new traders but nothing persists a batch timestamp. A lightweight approach is filtering `traders` by `first_seen` timestamp window (comparing to the most recent `first_seen` in the table).

**Primary recommendation:** Add a `discovered_at` column to `traders` (or use the existing `first_seen` as the discover-session marker), pivot `market_entities` into an entity work queue, reuse `get_team_stats_for_trader()` query logic as a basis for per-entity alpha computation, and store results in a new `entity_alpha` table. Crawler state is a single-row SQLite table (or JSON sidecar) tracking the last-processed entity cursor.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Click | existing | CLI command + flags | Already `@cli.command` pattern throughout |
| SQLAlchemy 2.0 | existing | ORM queries, work queue | `select()` style, `Mapped[]` models used everywhere |
| Rich | existing | `console.status()` spinner, `Table` | All existing commands use `Console` + `console.status(..., spinner="dots")` |
| loguru | existing | Structured logging | `logger.info/warning/error` in every command |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| sqlite3 / SQLAlchemy text() | existing | ALTER TABLE migrations | Pattern in `ingest.py` lines 2123-2142: inspect columns, conditionally ADD COLUMN |
| Python json | stdlib | Crawler cursor persistence | Simplest sidecar approach for pause/resume state |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| JSON sidecar for crawler cursor | New DB table `analyze_cursor` | DB table is cleaner but adds schema change; JSON file is zero-migration cost — fine for single-user tool |
| `first_seen` timestamp window for batch mode | New `discover_session_id` FK | FK requires schema change; `first_seen` window is sufficient if we query MAX(first_seen) minus a small tolerance |

**Installation:** No new packages needed. All dependencies are already in the project.

## Architecture Patterns

### Recommended Project Structure
```
src/
├── org_mapping/
│   ├── models.py         # Add EntityAlpha ORM model here
│   ├── queries.py        # Add entity alpha query functions here
│   └── crawler.py        # NEW: crawler state + work queue builder
tests/
└── org_mapping/
    ├── test_entity_alpha.py   # TDD unit tests (ANALYZE-01..ANALYZE-0N)
    └── test_analyze_cli.py    # Integration test for CLI command
```

### Pattern 1: DB Schema Migration (Existing Project Convention)
**What:** No Alembic. Migrations happen inline via `inspect().get_columns()` check + `ALTER TABLE ADD COLUMN` if column missing. Used in `ingest.py` lines 2119-2142.
**When to use:** Any time a new column is needed on an existing table, or a new table added via `Base.metadata.create_all()`.
**Example:**
```python
# Source: src/pipeline/ingest.py lines 2119-2142
inspector = inspect(engine)
existing_cols = [c["name"] for c in inspector.get_columns("traders")]
with engine.begin() as conn:
    if "discovered_at" not in existing_cols:
        conn.execute(text(
            "ALTER TABLE traders ADD COLUMN discovered_at TIMESTAMP"
        ))
```
For new tables: add ORM model to `src/db/models.py` (or module-specific models.py like `src/org_mapping/models.py`), then call `Base.metadata.create_all(engine)` — SQLAlchemy creates the table if it doesn't exist (idempotent).

### Pattern 2: Query Function in src/org_mapping/queries.py
**What:** Pure query function accepting a `Session` and returning a list of dicts. No side effects. Already established by `get_team_stats_for_trader()`.
**When to use:** All data retrieval logic for the analyze command.
**Example:**
```python
# Source: src/org_mapping/queries.py
def get_team_stats_for_trader(session: Session, trader_address: str) -> list[dict]:
    stmt = (
        select(Position, MarketEntity)
        .join(MarketEntity, Position.market_id == MarketEntity.condition_id)
        .where(
            Position.trader_address == trader_address,
            Position.resolved == True,
            Position.outcome.in_(["win", "loss"]),
            MarketEntity.market_type == "match",
        )
    )
    rows = session.execute(stmt).all()
    ...
```

### Pattern 3: CLI Command with Rich Spinner + Summary Table
**What:** `console.status(msg, spinner="dots")` wraps the processing block. After completion, `rich.table.Table` renders results. All existing commands use this.
**When to use:** The `analyze` command should follow this exact pattern.
**Example:**
```python
# Source: src/cli/commands.py lines 954-965
with console.status("[bold green]Processing traders...", spinner="dots") as status:
    for idx, addr in enumerate(all_addresses, start=1):
        status.update(f"[bold green]Processing {idx}/{len(all_addresses)}: {addr[:10]}...")
        ...
```

### Pattern 4: SELECT-then-UPDATE Upsert (Existing Convention)
**What:** No `INSERT OR REPLACE`. Query for existing row, update if found, insert if not. Used throughout `compute_and_upsert_team_stats()`.
**When to use:** For `entity_alpha` upsert in the analyze command.
**Example:**
```python
# Source: src/org_mapping/queries.py lines 108-134
existing = session.execute(
    select(TraderTeamStats).where(...)
).scalar_one_or_none()
if existing:
    existing.wins = s["wins"]
    ...
else:
    session.add(TraderTeamStats(...))
session.commit()
```

### Pattern 5: Crawler Work Queue from market_entities
**What:** Pivot `market_entities` to a set of unique (entity_type, entity_name, game) tuples. Build a queue of (trader_address, entity_name, game) pairs by joining traders to market_entities via positions.
**When to use:** Crawler mode (`--crawl`).

The work queue query skeleton:
```python
# Pseudo-query — all (trader, team, game) combinations with any resolved position
stmt = (
    select(
        Position.trader_address,
        MarketEntity.team_a,    # or team_b based on direction
        MarketEntity.game,
    )
    .join(MarketEntity, Position.market_id == MarketEntity.condition_id)
    .where(
        Position.resolved == True,
        Position.outcome.in_(["win", "loss"]),
        MarketEntity.market_type == "match",
    )
    .distinct()
)
```

### Pattern 6: Pausable Crawler State
**What:** JSON sidecar file at `.planning/analyze_cursor.json` (or DB table) tracks last-processed `(trader_address, entity_name, game)` offset. On resume: skip work items up to (but not including) the cursor.
**When to use:** `--crawl` mode only. Batch mode does not need a cursor since it processes a bounded set.

Simplest implementation: a dict `{"last_trader": "0x...", "last_entity": "NaVi", "last_game": "cs2", "processed": 1234}` written after each trader completes. On `--crawl`, if the cursor file exists, skip ahead.

### Anti-Patterns to Avoid
- **Float arithmetic for win rates:** Always use `Decimal`. `calculate_win_rate()` in `src/evaluation/metrics.py` already does this.
- **Blocking query without progress updates:** Crawler mode iterates potentially thousands of (trader, entity) pairs. Update the Rich spinner message each iteration.
- **Hand-rolling win rate calculation:** Use `calculate_win_rate()` from `src/evaluation/metrics.py` — it handles the zero-division, Decimal, and void-exclusion edge cases.
- **Querying `Trader` table for "latest batch" by address list:** The discover command does not persist a batch ID. Use `MAX(first_seen)` timestamp as the batch boundary: traders inserted within the last discover session share an approximate `first_seen` cluster. A practical approach is `WHERE first_seen >= (SELECT MAX(first_seen) FROM traders) - interval` or filter `backfill_complete=False AND first_seen = (SELECT MAX(first_seen) FROM traders)`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Win rate calculation | Custom wins/total formula | `calculate_win_rate()` in `src/evaluation/metrics.py` | Already handles void exclusion, Decimal precision, zero-division |
| Upsert logic | `INSERT OR REPLACE` or merge | SELECT-then-UPDATE pattern from `compute_and_upsert_team_stats()` | Existing convention; avoids autoincrement churn |
| Direction-to-team mapping | New mapping logic | Existing convention from Phase 22: LONG=team_a, SHORT=team_b (documented in `src/org_mapping/queries.py` module docstring) |
| Progress display | Custom print loop | `rich.console.status()` with `status.update()` | All existing commands use this pattern |
| DB migrations | Alembic | Inline `inspect + ALTER TABLE` pattern from `ingest.py:2119` | No Alembic in project; inline migrations are the convention |

**Key insight:** The Phase 22 query layer (`get_team_stats_for_trader`) already solves 80% of the per-entity alpha computation. Phase 23 needs to (a) generalize it to include tournament and game dimensions (not just team), (b) persist results to `entity_alpha`, and (c) build the crawler work queue on top of it.

## Common Pitfalls

### Pitfall 1: "Latest Discover Batch" is Ambiguous
**What goes wrong:** `discover_traders_from_market` returns new traders but does not tag them with a batch/session ID. If you try to reconstruct which traders came from the latest run, you have no reliable marker.
**Why it happens:** The `Trader` model has `first_seen` but no `discover_session_id` or `discovered_at` column.
**How to avoid:** Either (a) add a `discovered_at` column (inline migration, set on Trader creation) and query `WHERE discovered_at = (SELECT MAX(discovered_at) FROM traders)`, or (b) use `first_seen` as a proxy — traders created within the same second/minute cluster together. Option (a) is cleaner.
**Warning signs:** If batch mode produces an empty trader list when traders clearly exist in the DB, the timestamp window filter is too narrow.

### Pitfall 2: market_entities Does Not Cover All Traders
**What goes wrong:** A trader has positions in markets with no `market_entities` row (entity extraction not run, or market was not a match type). Entity alpha for that trader is empty, but trader still appears in the batch.
**Why it happens:** `market_entities` is populated by the `discover` command's `extract_entities()` call, which may fail silently (exception caught with `continue` at line 1131 of commands.py). Also, only markets with `market_type="match"` contribute to team stats.
**How to avoid:** Count and report "traders with no entity coverage" in the summary output. Do not error — skip silently with a log entry.
**Warning signs:** All analyze results are empty despite traders having resolved positions.

### Pitfall 3: Crawler Cursor Stale After Schema Change
**What goes wrong:** Cursor stores a (trader, entity, game) tuple but if `market_entities` data changes (re-extract), the cursor offset is wrong.
**Why it happens:** Cursor is positional, not version-stamped.
**How to avoid:** Store cursor as the actual (trader_address, entity_name, game) last-processed values, not a row count. Then on resume, skip rows `WHERE (trader, entity, game) <= cursor` rather than using a numeric offset.

### Pitfall 4: TraderTeamStats Base.metadata Issue
**What goes wrong:** `TraderTeamStats` is defined in `src/org_mapping/models.py` and imports `Base` from `src/db/models.py`. Tests that call `Base.metadata.create_all()` must import `TraderTeamStats` before the call, otherwise the table is not registered. The existing Phase 22 tests do this correctly.
**How to avoid:** In test fixtures, import `TraderTeamStats` (and the new `EntityAlpha` model) before `Base.metadata.create_all(engine)`.

### Pitfall 5: Entity Work Queue Explosion
**What goes wrong:** In crawler mode, the work queue can be very large — e.g., 10,000 traders × 20 entities each = 200,000 pairs. Loading the full queue into memory at once is not safe.
**Why it happens:** No pagination on the work queue query.
**How to avoid:** Use a generator or paginate by trader: iterate over trader addresses, process one trader's entities at a time, commit after each trader, then advance cursor. This also makes pause/resume natural.

## Code Examples

Verified patterns from direct codebase inspection:

### EntityAlpha ORM Model (New Table)
```python
# Follow src/org_mapping/models.py pattern
class EntityAlpha(Base):
    __tablename__ = "entity_alpha"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trader_address: Mapped[str] = mapped_column(String(42), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)  # "team", "tournament", "game"
    entity_name: Mapped[str] = mapped_column(String(200), nullable=False)
    game: Mapped[str | None] = mapped_column(String(200), nullable=True)
    wins: Mapped[int] = mapped_column(default=0, nullable=False)
    losses: Mapped[int] = mapped_column(default=0, nullable=False)
    total_resolved: Mapped[int] = mapped_column(default=0, nullable=False)
    win_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index(
            "ix_entity_alpha_trader_type_name_game",
            "trader_address", "entity_type", "entity_name", "game",
            unique=True,
        ),
        Index("ix_entity_alpha_entity_name", "entity_name"),
        Index("ix_entity_alpha_trader", "trader_address"),
    )
```

### CLI Command Registration
```python
# Source: src/cli/commands.py — @cli.command pattern
@cli.command("analyze")
@click.option("--crawl", is_flag=True, help="Exhaust all known entities across all traders")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def analyze(crawl, verbose):
    """Compute entity-level alpha for traders...."""
    console = Console()
    with console.status("[bold green]Analyzing entities...", spinner="dots") as status:
        ...
```

### Rich Status Update in Loop
```python
# Source: src/cli/commands.py lines 954-959
with console.status("[bold green]Processing traders...", spinner="dots") as status:
    for idx, addr in enumerate(all_addresses, start=1):
        status.update(
            f"[bold green]Processing {idx}/{len(all_addresses)}: {addr[:10]}..."
        )
```

### Detect and Acquire "Latest Batch" Traders
```python
# Query traders created in the most recent discover session
# Using first_seen as a proxy when no session_id column exists
from sqlalchemy import func
max_seen = session.execute(
    select(func.max(Trader.first_seen))
).scalar()
# Traders created within 60s of the most recent first_seen
recent_traders = session.execute(
    select(Trader).where(
        Trader.first_seen >= max_seen - timedelta(seconds=60)
    )
).scalars().all()
```
**Warning:** This heuristic works for interactive discover sessions but will group all traders if `discover` was never run. Add a guard: if `max_seen is None`, print a helpful message.

### Crawler Cursor Sidecar
```python
import json
from pathlib import Path

CURSOR_FILE = Path(".planning/analyze_cursor.json")

def load_cursor() -> dict | None:
    if CURSOR_FILE.exists():
        return json.loads(CURSOR_FILE.read_text())
    return None

def save_cursor(trader_address: str, entity_name: str, game: str | None, processed: int):
    CURSOR_FILE.write_text(json.dumps({
        "last_trader": trader_address,
        "last_entity": entity_name,
        "last_game": game,
        "processed": processed,
    }))

def clear_cursor():
    CURSOR_FILE.unlink(missing_ok=True)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Pre-computed `TraderTeamStats` (Phase 22) | Query-time computation in `get_team_stats_for_trader()` | Phase 22 | Phase 23 can reuse this as the computation engine; `entity_alpha` is the persisted ledger |
| Team-level only stats | Entity-level (team + tournament + game dimensions) | Phase 23 | Richer signal — a trader who has strong stats against "NaVi" in "IEM Katowice" is more actionable than generic eSports expertise |

## Open Questions

1. **What exactly constitutes "latest discover batch"?**
   - What we know: `Trader.first_seen` is set at creation time in `discover_traders_from_market()`; no batch ID column exists
   - What's unclear: Whether the user wants "traders discovered in the current session" vs "traders discovered since the last analyze run"
   - Recommendation: Use `first_seen` timestamp proximity (60s window from MAX) for now; add `discovered_at` column if the heuristic proves unreliable. Simpler alternative: a `--since` flag accepting a datetime or duration, defaulting to "last hour"

2. **Should entity_alpha cover tournament and game dimensions or only team?**
   - What we know: `market_entities` has `team_a`, `team_b`, `tournament`, `game` fields; Phase 22 only computed team-level stats
   - What's unclear: CONTEXT.md does not exist to lock this; ROADMAP says "win rate per dimension per trader, replaces pre-computed scoring"
   - Recommendation: Include all three dimensions (team, tournament, game) in `entity_alpha` via `entity_type` column. This is the natural extension of the LONG=team_a / SHORT=team_b pattern.

3. **Does --crawl replace or supplement TraderTeamStats?**
   - What we know: Phase 22 built `trader_team_stats` as pre-computed per-team stats; Phase 23 description says "replaces pre-computed scoring"
   - What's unclear: Whether `trader_team_stats` is deprecated by `entity_alpha` or kept as a different cut of the same data
   - Recommendation: `entity_alpha` is the new primary ledger; `trader_team_stats` remains for backward compatibility but is not used by the analyze command.

## Validation Architecture

`workflow.nyquist_validation` key is absent from `.planning/config.json`, so validation is enabled.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | none (pytest discovers by convention) |
| Quick run command | `python -m pytest tests/org_mapping/ -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements → Test Map

Phase 23 requirements are not yet in REQUIREMENTS.md. Based on the phase description, anticipated requirements and their test mapping:

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| ANALYZE-01 | `get_entity_alpha_for_trader()` returns per-entity wins/losses correctly | unit | `python -m pytest tests/org_mapping/test_entity_alpha.py::test_entity_alpha_basic -x` | Wave 0 |
| ANALYZE-02 | LONG=team_a, SHORT=team_b direction mapping honored | unit | `python -m pytest tests/org_mapping/test_entity_alpha.py::test_direction_mapping -x` | Wave 0 |
| ANALYZE-03 | Unresolved, void, prop markets excluded | unit | `python -m pytest tests/org_mapping/test_entity_alpha.py::test_excludes_unresolved -x` | Wave 0 |
| ANALYZE-04 | `upsert_entity_alpha()` is idempotent | unit | `python -m pytest tests/org_mapping/test_entity_alpha.py::test_upsert_idempotent -x` | Wave 0 |
| ANALYZE-05 | Batch mode processes latest-discover traders only | unit | `python -m pytest tests/org_mapping/test_entity_alpha.py::test_batch_mode_filters_by_first_seen -x` | Wave 0 |
| ANALYZE-06 | Crawler cursor save/load round-trips correctly | unit | `python -m pytest tests/org_mapping/test_entity_alpha.py::test_crawler_cursor -x` | Wave 0 |
| ANALYZE-07 | CLI `analyze` command (no flags) runs without error on seeded DB | integration | `python -m pytest tests/org_mapping/test_analyze_cli.py -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/org_mapping/ -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/org_mapping/test_entity_alpha.py` — covers ANALYZE-01..ANALYZE-06
- [ ] `tests/org_mapping/test_analyze_cli.py` — covers ANALYZE-07
- [ ] `tests/org_mapping/__init__.py` — already exists (org_mapping test package)

## Sources

### Primary (HIGH confidence)
- Direct read: `src/org_mapping/queries.py` — full implementation of `get_team_stats_for_trader()` and `compute_and_upsert_team_stats()`
- Direct read: `src/org_mapping/models.py` — `TraderTeamStats` schema, unique constraint pattern
- Direct read: `src/db/models.py` — `Trader`, `Position`, `MarketEntity`, all relevant table schemas
- Direct read: `src/pipeline/ingest.py` lines 689-803 — `discover_traders_from_market()` full implementation; lines 2119-2142 — inline migration pattern
- Direct read: `src/cli/commands.py` lines 2392-2465 — `team-stats` command as Phase 23's direct template; lines 954-959 — spinner+status.update pattern
- Direct read: `tests/org_mapping/test_queries.py` and `test_cli.py` — test fixture and setup patterns

### Secondary (MEDIUM confidence)
- Direct read: `.planning/ROADMAP.md` Phase 23 description and Phase 22 goal statement
- Direct read: `.planning/STATE.md` — "replaces pre-computed scoring" design intent

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries are existing dependencies, verified from imports in commands.py and models.py
- Architecture: HIGH — patterns copied directly from working Phase 22 code
- Pitfalls: HIGH — identified from reading actual discover_traders_from_market() and entity extraction code paths; one pitfall (cursor stale) is LOW, inferred from design
- DB migration pattern: HIGH — read directly from ingest.py lines 2119-2142

**Research date:** 2026-03-14
**Valid until:** 2026-04-14 (stable internal codebase, no external library dependency research needed)
