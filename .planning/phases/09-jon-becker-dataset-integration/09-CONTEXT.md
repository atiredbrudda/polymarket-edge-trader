# Phase 9: Jon Becker Dataset Integration - Context

**Created:** 2026-02-12
**Source:** User clarification on cost-optimization strategy

## User Decisions (LOCKED)

### Decision 1: Cost-Optimized Fallback Hierarchy

**Decision:** JBecker Dataset is PRIMARY data source, not backup

**Rationale:**
- Bulk trader analysis (1,000+ traders) would consume massive Graph API units
- JBecker dataset provides FREE complete historical data (2020-2026)
- API provides FREE recent data (100 trades, within free tier)
- The Graph should only be used when API's 100-trade limit is insufficient
- Goal: Minimize API unit consumption while getting complete trader histories

**Locked Implementation:**
```
Fallback Order: JBecker (primary) → API (recent gap) → Graph (if needed) → Blockchain (last resort)

Flow:
1. Query JBecker dataset for ALL historical trades (free, instant)
2. Get latest trade timestamp from JBecker results
3. Query API for trades AFTER that timestamp (free, ≤100 trades)
4. If API returns 100 trades AND cursor indicates more exist, use Graph
5. Last resort: Blockchain for complete backfill (6-7 hours)
```

**What this means:**
- `ingest_trader_history_hybrid()` must try JBecker FIRST, not last
- JBecker is not a "backup tier" - it's the PRIMARY historical source
- The Graph is the expensive option, use sparingly
- For most traders, JBecker + API will be sufficient (free)

**Impact on Plans:**
- Plan 09-02 Task 2 must implement JBecker-first fallback logic
- Pipeline should deduplicate across sources (JBecker + API results)
- Must-haves should verify JBecker is queried before Graph

### Decision 2: Gap-Filling Strategy

**Decision:** Use timestamp-based querying to fill the gap between JBecker snapshot and current

**Rationale:**
- JBecker dataset is a static snapshot (Feb 2026 or earlier)
- Most traders won't have >100 trades since snapshot date
- API's 100-trade limit is sufficient for recent gap-filling
- Only heavy traders need Graph (expensive) for gap

**Locked Implementation:**
```python
# After getting JBecker trades
latest_jbecker_timestamp = max(trade.timestamp for trade in jbecker_trades)

# Query API for trades after snapshot
api_trades = api_client.get_trades(
    trader_address,
    start_time=latest_jbecker_timestamp + 1  # After last JBecker trade
)

# If API maxed out (100 trades) and cursor exists, consider Graph
if len(api_trades) == 100 and api_cursor:
    # User likely has more recent trades, use Graph
    graph_trades = graph_client.query_recent_trades(...)
```

**What this means:**
- Pipeline must track "latest trade date" from each source
- Deduplication works via trade_id (same as Phase 8)
- Incremental updates are timestamp-based, not full re-sync

## Claude's Discretion (Freedom Areas)

### Area 1: Batch Size Optimization
**Freedom:** Choose optimal batch size for JBecker ingestion
**Context:** Recommendation is 1,000 trades (vs 100 for API) since JBecker returns larger result sets
**Constraint:** Must be configurable via Settings

### Area 2: Missing Dataset UX
**Freedom:** Design error messages and download instructions
**Context:** User should see friendly message with download URL, not crash
**Constraint:** Must be testable without 33.5GB dataset

### Area 3: CLI Output Formats
**Freedom:** Choose table formatting, JSON structure, CSV column order
**Context:** Research command should support table/json/csv output
**Constraint:** Follow existing CLI formatter patterns from Phase 7

### Area 4: Test Fixture Design
**Freedom:** Choose fixture size and sample trades
**Context:** 100-trade fixture recommended, must match JBecker schema
**Constraint:** Fixtures must be <10MB for CI/CD performance

## Deferred Ideas (Out of Scope)

### Deferred 1: Incremental JBecker Updates
**Idea:** Download only new trades from Jon Becker's dataset
**Reason:** JBecker dataset is static snapshot; incremental updates would require different data source
**Future:** Phase 10+ could add periodic re-download or streaming updates

### Deferred 2: Automatic Dataset Download
**Idea:** Auto-download 33.5GB on first use
**Reason:** Too large for automatic download; user should explicitly download
**Future:** Could add `polymarket setup-jbecker` command to assist download

### Deferred 3: Market Metadata Enrichment Priority
**Idea:** Prefer JBecker's markets Parquet over API for metadata
**Reason:** Focus on trade ingestion first; market metadata can use existing API flow
**Future:** Phase 10+ could optimize market metadata to use JBecker's markets files

## Architecture Summary

### Data Tier Hierarchy (Cost-Optimized)

| Tier | Source | Cost | Speed | Use Case |
|------|--------|------|-------|----------|
| 1 | JBecker Dataset | FREE | Seconds | All historical trades (2020-2026) |
| 2 | API | FREE* | Fast | Recent trades (<100 since snapshot) |
| 3 | The Graph | COSTS UNITS | Fast | Heavy traders (>100 recent trades) |
| 4 | Blockchain | FREE | Slow (6-7h) | Complete backfill fallback |

*API free within tier limits

### Integration Pattern

```
User requests trader history
    ↓
Query JBecker (get bulk historical)
    ↓
Get latest_timestamp from results
    ↓
Query API (get trades after latest_timestamp, ≤100)
    ↓
Deduplicate by trade_id
    ↓
If API returned 100 AND cursor exists:
    → Query Graph (get remaining recent trades)
    ↓
    Deduplicate by trade_id
    ↓
Store all trades via pipeline
```

### Success Criteria (Updated)

1. ✅ System queries JBecker FIRST (not as fallback)
2. ✅ API fills gap for recent trades (timestamp-based)
3. ✅ The Graph only used when API insufficient (cost-optimized)
4. ✅ Deduplication works across all sources (trade_id)
5. ✅ Bulk analysis (1,000 traders) minimizes Graph API usage

## References

- **Handoff Document:** PHASE_9_HANDOFF.md (original 3-tier strategy)
- **Research:** 09-RESEARCH.md (DuckDB patterns, security)
- **User Clarification:** 2026-02-12 - Cost optimization is primary goal
