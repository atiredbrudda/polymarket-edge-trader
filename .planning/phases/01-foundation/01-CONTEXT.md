# Phase 1: Foundation - Context

**Gathered:** 2026-02-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Establish reliable data ingestion from Polymarket CLOB API and persistent local SQLite storage. This phase builds the data pipeline: fetching markets, trades, and trader histories, normalizing API responses, and persisting them with proper indexing. No analysis, scoring, or presentation — just reliable data in, data stored.

</domain>

<decisions>
## Implementation Decisions

### API data scope
- **Backfill depth:** 12 months of trader history when first discovered. Recent enough to evaluate expertise, avoids burning API calls on ancient data.
- **Trade fetching strategy:** Fetch ALL markets for each trader (needed for category concentration ratio in Phase 4), but only store eSports trades in full detail. Store aggregate summary for non-eSports activity (total volume, trade count, category breakdown).
- **Market metadata:** Store market metadata alongside trades — question text, end date, outcome, category. Needed downstream for classification (Phase 2) and display (Phase 7).
- **Data scope per trade:** Full trade records for eSports markets (trader, market, side, size, price, timestamp). Summary-only for non-eSports.

### Claude's Discretion
- Rate limiting strategy (how aggressive, backoff behavior, caching)
- Database schema design (table structure, indexing, denormalization)
- Project/package structure and module boundaries
- Config file format and location
- Error handling for API failures and incomplete data

</decisions>

<specifics>
## Specific Ideas

- Pipeline must be category-agnostic by design — eSports is the first case study, not a hard-coded assumption. The "fetch all, store eSports detail + summary for rest" pattern should generalize to any category.
- The 12-month backfill window is a starting default, not a hard limit. Should be configurable.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 01-foundation*
*Context gathered: 2026-02-05*
