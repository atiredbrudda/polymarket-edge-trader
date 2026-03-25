# Phase 27: Hybrid Backfill Gap Fix - Context

**Gathered:** 2026-03-24
**Status:** Ready for planning
**Source:** Direct investigation in conversation

<domain>
## Phase Boundary

Fix the ~54-day trade data gap in the hybrid backfill pipeline. After backfill, traders should have continuous trade coverage from JBecker dataset cutoff (Jan 28, 2026) through present.

</domain>

<decisions>
## Implementation Decisions

### Bug 1: Graph Escalation Trigger (Critical)
- Line 2041 in `src/pipeline/ingest.py`: `if api_trade_count >= 100` checks `detail_count` which is post-deduplication count
- After JBecker trades already in DB, dedup reduces new inserts well below 100
- Fix: track raw API response count separately from deduplicated insert count
- The Graph tier (`ingest_trader_history_graph`) works correctly — it just never gets called

### Bug 2: API Gap Fill Has No Time Filtering
- Line 2034: `self.ingest_trader_history(trader_address)` calls the generic API method with no time context
- `src/api/client.py:258`: `get_trader_trades` hits `data-api.polymarket.com/trades?proxyWallet=X` — no pagination, no `after` param
- Returns ~100 most recent trades only — for active traders this covers hours, not weeks
- The `latest_timestamp` from JBecker is computed (line 2024) but never passed to the API call

### Strategy
- Primary fix: Make Graph escalation fire reliably (Bug 1) — Graph can fetch thousands of trades in seconds and covers the full gap
- Secondary: If API gap fill is kept, it should at least pass a time filter — but Graph is the real solution for large gaps
- Do NOT add API pagination (complex, rate-limit-heavy) — lean on Graph for bulk historical data

### Claude's Discretion
- Internal implementation of raw count tracking
- Whether to add `after_timestamp` param to API client or simplify the hybrid flow
- Test structure and coverage approach

</decisions>

<specifics>
## Specific Details from Investigation

### Data State (2026-03-24)
- 308,071 total trades, ALL ingested in last 24h
- 48,834 positions; 48,062 resolved
- Trade gap: 0 trades between 7-45 days ago across ALL traders
- JBecker dataset: 404M trades, block range 40M-82M, covers 2023-03-05 to 2026-01-28
- Graph trades in DB: 0 (tier never fired)

### Example: Top Trader 0x2652dd...
- 29,124 total trades (29,022 JBecker + 102 API)
- JBecker covers: Nov 12 2025 - Jan 28 2026
- API covers: Mar 23 2026 (yesterday only, ~4 hours)
- Missing: Jan 28 - Mar 23 = 54 days

### Key Code Locations
- Hybrid orchestrator: `src/pipeline/ingest.py:1967` (`ingest_trader_history_hybrid`)
- Graph escalation check: `src/pipeline/ingest.py:2041`
- API client (no pagination): `src/api/client.py:235` (`get_trader_trades`)
- API ingest (dedup): `src/pipeline/ingest.py:946` (detail_count increment)
- Graph client: `src/graph/client.py:82` (`get_trader_trades`)
- JBecker converter timestamps: `src/datasources/converters.py:18` (`block_number_to_timestamp`)

### Graph Client Capabilities
- Polymarket Orderbook subgraph: instant queries (3 sec for 2,000+ trades)
- Tested working with @Xero100i (2,024 trades fetched)
- API key in .env: THE_GRAPH_API_KEY
- Can query by trader address with timestamp filtering

</specifics>

<deferred>
## Deferred Ideas

- API pagination (complex, not needed if Graph works)
- Backfill progress tracking / resumability
- Parallel Graph queries for multiple traders

</deferred>

---

*Phase: 27-hybrid-backfill-gap-fix*
*Context gathered: 2026-03-24 via direct DB investigation*
