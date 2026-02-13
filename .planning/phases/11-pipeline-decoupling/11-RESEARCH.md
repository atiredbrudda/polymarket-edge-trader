# Phase 11: Pipeline Decoupling - Research

**Researched:** 2026-02-13
**Domain:** Pipeline state management, CLI decoupling, incremental processing
**Confidence:** HIGH

## Summary

Phase 11 decouples trader discovery from history backfill, allowing independent execution and state tracking. The current `IngestionPipeline.run_full_sweep()` combines both operations atomically - this phase splits them into separate commands with persistent state tracking via the existing `Trader.backfill_complete` boolean flag.

The architecture is straightforward: add database queries to filter traders by backfill state, add two new CLI commands that call existing pipeline methods independently, and add a status command to view progress. The pipeline methods (`discover_traders_from_market`, `ingest_trader_history_hybrid`) already exist and support independent execution.

**Primary recommendation:** Extend existing pipeline with state-filtered queries and add three new Click commands (discover, backfill, status). No new database columns needed - the `backfill_complete` flag already provides the state tracking required.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy | 2.0+ | ORM and state tracking | Already in use, provides boolean flags and query filtering |
| Click | 8.x | CLI framework | Already in use for all commands, supports command groups |
| pytest | Latest | Testing framework | Already in use, 362 tests existing |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| loguru | Latest | Logging | Already configured for CLI session logging |
| Rich | Latest | CLI formatting | Already in use for console output |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Boolean flag | Enum state field | Over-engineered for two states (discovered vs. backfilled) |
| CLI commands | Pipeline script arguments | Less discoverable, worse UX |
| Separate queries | Application-level filtering | Slower, doesn't leverage DB indexes |

**Installation:**
No new dependencies required - all libraries already in requirements.txt.

## Architecture Patterns

### Recommended Project Structure
```
src/
├── pipeline/
│   ├── ingest.py              # Existing - already has separated methods
│   └── queries.py             # Extend with backfill-state queries
├── cli/
│   └── commands.py            # Add 3 new commands: discover, backfill, status
└── db/
    └── models.py              # Existing - Trader.backfill_complete already present
```

### Pattern 1: State-Based Query Filtering
**What:** Use SQLAlchemy boolean filters to select traders by processing state
**When to use:** Separating discovery from backfill, resumable operations
**Example:**
```python
# Source: SQLAlchemy 2.1 State Management Documentation
# https://docs.sqlalchemy.org/en/21/orm/session_state_management.html

from sqlalchemy import select

def get_traders_needing_backfill(session) -> list[Trader]:
    """Get traders discovered but not yet backfilled."""
    stmt = select(Trader).where(Trader.backfill_complete == False)
    return session.execute(stmt).scalars().all()

def get_backfilled_traders(session) -> list[Trader]:
    """Get traders with completed backfill."""
    stmt = select(Trader).where(Trader.backfill_complete == True)
    return session.execute(stmt).scalars().all()
```

### Pattern 2: Decoupled CLI Commands with Shared Pipeline
**What:** Separate Click commands call same pipeline methods independently
**When to use:** Breaking monolithic operations into user-controllable steps
**Example:**
```python
# Source: Click Advanced Patterns Documentation
# https://click.palletsprojects.com/en/stable/advanced/

@cli.command()
def discover():
    """Discover traders without triggering backfill."""
    pipeline = IngestionPipeline(...)
    for market in get_active_markets():
        pipeline.discover_traders_from_market(market.condition_id)

@cli.command()
@click.argument("address", required=False)
def backfill(address):
    """Backfill history for discovered traders."""
    pipeline = IngestionPipeline(...)
    if address:
        # Single trader
        pipeline.ingest_trader_history_hybrid(address)
    else:
        # All pending
        traders = get_traders_needing_backfill(session)
        for trader in traders:
            pipeline.ingest_trader_history_hybrid(trader.address)
```

### Pattern 3: CLI Status Reporting with Rich Tables
**What:** Query database state and display formatted summary
**When to use:** User visibility into pipeline progress
**Example:**
```python
# Source: Existing implementation in src/cli/formatters.py

@cli.command()
def status():
    """View discovery and backfill status."""
    pending = get_traders_needing_backfill(session)
    complete = get_backfilled_traders(session)

    table = Table(title="Pipeline Status")
    table.add_row("Discovered (not backfilled)", str(len(pending)))
    table.add_row("Backfilled", str(len(complete)))
    console.print(table)
```

### Anti-Patterns to Avoid
- **Duplicating pipeline logic in CLI:** Commands should call pipeline methods, not reimplement discovery/backfill logic
- **Application-level state filtering:** Always filter in SQL (`.where()`) not Python loops
- **Stateless operations:** Don't re-discover already-backfilled traders - check `backfill_complete` first

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| State machine | Custom enum transitions | Boolean flag + queries | Two states don't need state machine complexity |
| CLI progress tracking | Custom state file | Database queries + Rich | Already have DB, Rich provides formatting |
| Resumable processing | Custom checkpoint system | Query by backfill_complete | Database already tracks state atomically |
| Command composition | Custom orchestrator | Click command groups | Click designed for this, supports --help automatically |

**Key insight:** The existing architecture already supports decoupling - we just need queries and commands that expose the separated methods.

## Common Pitfalls

### Pitfall 1: Race Conditions in Backfill Flag Updates
**What goes wrong:** Multiple processes mark same trader as backfilled simultaneously
**Why it happens:** No transaction isolation between check and update
**How to avoid:** Use single UPDATE statement that checks and sets atomically, or run backfill single-threaded
**Warning signs:** Duplicate processing, inconsistent state in logs

### Pitfall 2: Forgetting to Set backfill_complete=False on Discovery
**What goes wrong:** Newly discovered traders don't appear in "pending backfill" query
**Why it happens:** Default value not set in Trader creation
**How to avoid:** Verify `Trader(backfill_complete=False)` in `discover_traders_from_market()`
**Warning signs:** Status command shows 0 pending but traders exist in table

### Pitfall 3: Not Handling Partial Backfill Failures
**What goes wrong:** Trader marked complete even if history ingestion fails mid-process
**Why it happens:** Flag set before operation completes
**How to avoid:** Set `backfill_complete=True` ONLY at end of `ingest_trader_history_hybrid()` after commit
**Warning signs:** Traders marked complete with 0 trades in database

### Pitfall 4: Missing Indexes on backfill_complete
**What goes wrong:** Status queries become slow with 10,000+ traders
**Why it happens:** Full table scan without index
**How to avoid:** Add `Index("ix_trader_backfill_status", "backfill_complete")` to Trader model
**Warning signs:** CLI status command takes >1 second

## Code Examples

Verified patterns from existing codebase:

### Existing Pipeline Method (Already Independent)
```python
# Source: src/pipeline/ingest.py lines 378-472
def discover_traders_from_market(self, condition_id: str) -> list[str]:
    """Discover trader addresses from market trades.

    Creates Trader records with backfill_complete=False.
    Returns list of newly discovered addresses.
    """
    trades = self.client.get_market_trades(condition_id)
    trader_addresses = {trade.trader for trade in trades}

    new_traders = []
    for address in trader_addresses:
        if not existing:
            trader = Trader(
                address=address,
                backfill_complete=False,  # KEY: Set to False on discovery
            )
            session.add(trader)
            new_traders.append(address)

    return new_traders
```

### Existing Backfill Method (Already Independent)
```python
# Source: src/pipeline/ingest.py lines 1248-1355
def ingest_trader_history_hybrid(
    self,
    trader_address: str,
    prefer_jbecker: bool = True,
) -> dict:
    """Ingest trader history using 4-tier hierarchy.

    Marks trader.backfill_complete=True on success.
    """
    # ... fetch from JBecker/API/Graph/Blockchain ...

    # Mark complete (line 1203-1204 in jbecker method)
    trader = session.query(Trader).filter_by(address=trader_address).first()
    if trader:
        trader.backfill_complete = True
        trader.last_active = datetime.utcnow()

    session.commit()
    return stats
```

### Query Pattern for State Filtering
```python
# Add to src/pipeline/queries.py
from sqlalchemy import select
from src.db.models import Trader

def get_traders_by_backfill_status(
    session,
    backfilled: bool
) -> list[Trader]:
    """Get traders filtered by backfill completion status.

    Args:
        session: SQLAlchemy session
        backfilled: True for completed, False for pending

    Returns:
        List of Trader ORM objects
    """
    stmt = (
        select(Trader)
        .where(Trader.backfill_complete == backfilled)
        .order_by(Trader.first_seen.desc())
    )
    return session.execute(stmt).scalars().all()
```

### CLI Command Pattern (Follows Existing Style)
```python
# Add to src/cli/commands.py
@cli.command()
@click.option("--niche", "-n", multiple=True, help="Niche category to scan")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def discover(niche, verbose):
    """Discover traders from active markets without backfilling.

    Example:
        polymarket discover
        polymarket discover --niche esports
    """
    logger.info(f"DISCOVER command started (niches={niche})")

    session_factory, client, category_filter, _, gamma_client = _get_dependencies()
    pipeline = IngestionPipeline(client, session_factory, category_filter, gamma_client=gamma_client)

    # Step 1: Ingest markets (same as sweep)
    markets_count = pipeline.ingest_targeted_markets(niches=niche) if niche else pipeline.ingest_active_markets()

    # Step 2: Discover traders (WITHOUT backfill)
    with get_session(session_factory) as session:
        markets = session.query(Market).filter_by(active=True).all()
        detail_markets = [m for m in markets if category_filter.requires_detail(m.category)]

        traders_discovered = 0
        for market in detail_markets:
            new_traders = pipeline.discover_traders_from_market(market.condition_id)
            traders_discovered += len(new_traders)

    console = Console()
    console.print(f"[green]Discovered {traders_discovered} new traders from {markets_count} markets[/green]")
    logger.info(f"DISCOVER command completed: {traders_discovered} traders from {markets_count} markets")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Monolithic sweep | Separated methods exist but not exposed | Phase 1-9 | Methods ready, just need CLI exposure |
| Manual state tracking | Database boolean flags | Phase 1 (Trader model) | Persistent state, query-able |
| Full re-processing | Incremental with backfill_complete | Phase 9 (JBecker integration) | Avoid re-downloading 2000+ trades per trader |

**Deprecated/outdated:**
- Running full sweep for discovery-only use case (wastes time on backfill)
- No visibility into which traders need processing (status command needed)

## Open Questions

1. **Should we support batch discovery (multiple markets at once)?**
   - What we know: Current code processes markets sequentially in loop
   - What's unclear: Whether parallelization would hit rate limits
   - Recommendation: Start sequential (existing pattern), add --parallel flag in Phase 12 if needed

2. **How to handle discovery of already-backfilled traders?**
   - What we know: `discover_traders_from_market()` checks `if not existing` before creating
   - What's unclear: Should we update `last_active` timestamp for re-discovered traders?
   - Recommendation: Update `last_active` even if trader exists (shows continued activity)

3. **Should backfill command support --limit for testing?**
   - What we know: Could process first N pending traders
   - What's unclear: Is this needed for typical use cases?
   - Recommendation: Add `--limit` flag (useful for testing without processing all 1000+ traders)

## Sources

### Primary (HIGH confidence)
- Existing codebase: `/Users/macbookair/Documents/project/test/rerun7/GSD_Polymarket/src/pipeline/ingest.py` - pipeline methods already separated
- Existing codebase: `/Users/macbookair/Documents/project/test/rerun7/GSD_Polymarket/src/db/models.py` - Trader.backfill_complete field exists (line 65)
- Existing codebase: `/Users/macbookair/Documents/project/test/rerun7/GSD_Polymarket/src/cli/commands.py` - established CLI patterns
- [SQLAlchemy 2.1 State Management Documentation](https://docs.sqlalchemy.org/en/21/orm/session_state_management.html) - boolean state tracking patterns
- [Click Advanced Patterns Documentation](https://click.palletsprojects.com/en/stable/advanced/) - command decoupling and groups

### Secondary (MEDIUM confidence)
- [Python Click CLI Build Guide 2026](https://oneuptime.com/blog/post/2026-01-30-python-click-cli-applications/view) - modern CLI patterns
- [Real Python Click Tutorial](https://realpython.com/python-click/) - composable CLI applications
- [SQLAlchemy 2.0 Session Basics](https://docs.sqlalchemy.org/en/20/orm/session_basics.html) - transaction management for state updates

### Tertiary (LOW confidence)
- [DDD Principles with SQLAlchemy 2026](https://johal.in/ddd-principles-python-aggregates-with-sqlalchemy-events-2026/) - event-based decoupling (overkill for our use case)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries already in use, no new dependencies
- Architecture: HIGH - Pipeline methods already separated, just need CLI exposure
- Pitfalls: HIGH - Backfill state pattern already implemented and tested in Phases 1-9

**Research date:** 2026-02-13
**Valid until:** 2026-04-13 (60 days - stable domain, no fast-moving dependencies)
