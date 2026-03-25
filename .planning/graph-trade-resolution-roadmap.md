# Graph Trade Resolution Roadmap

**Date:** 2026-03-25  
**Author:** opencode  
**Based on:** `graph-trade-data-structure-research.md`, `market-outcome-coverage-research.md`

---

## Problem Summary

Two bottlenecks blocking position resolution:

| Problem | Metric | Root Cause |
|---------|--------|------------|
| **Matching** | 72% trades orphaned (`graph_` placeholders) | Token catalog lookup fails (11.4% match rate) |
| **Resolution** | 91% markets lack `outcome` | No GammaEvent row for 136K markets |

**Impact:** 26,238 positions cannot be resolved (27% of total positions)

---

## Phase 1: Token Catalog Expansion

**Goal:** Reduce `graph_` placeholders from 72% → <10%

### 1.1 Discovery
- [ ] Audit CLOB API `/tokens` endpoint availability
- [ ] Check existing token catalog coverage (`SELECT COUNT(*) FROM token_catalog`)
- [ ] Identify high-value tokens (most trades with `graph_` placeholders)

### 1.2 Implementation
- [ ] Add `get_all_tokens()` method to `src/api/client.py`
- [ ] Build `polymarket build-token-catalog` CLI command
- [ ] Populate `token_catalog` table with `token_id` → `condition_id` mapping

### 1.3 Backfill
- [ ] Create migration script: `migrate_graph_market_ids.py`
- [ ] Re-process `graph_` trades with resolved `condition_id`s
- [ ] Update `Trade.market_id` from `graph_...` → real `condition_id`

### 1.4 Validation
- [ ] Measure new token catalog coverage (target: >90%)
- [ ] Measure reduction in `graph_` trades (target: <10%)
- [ ] Verify position building for previously orphaned trades

**Expected Outcome:**
- Match ~500K-1M orphaned trades to real markets
- Token catalog coverage: 11.4% → 90%+

**Files:**
- `src/api/client.py` — Add token endpoints
- `src/cli/commands.py` — Add `build-token-catalog` command
- `scripts/migrate_graph_market_ids.py` — Backfill migration

**Priority:** HIGH (upstream blocker for resolution)

---

## Phase 2: Market Outcome Resolution

**Goal:** Resolve markets from 8% → 60%+ coverage

### 2.1 Gamma API Bulk Resolution
- [ ] Run `polymarket resolve-markets-from-events` (Phase 29 existing command)
- [ ] Measure coverage: how many of 136K markets resolved?
- [ ] Log 404/delisted markets for fallback

### 2.2 CLOB API Fallback
- [ ] Add `get_market_outcome(condition_id)` to `src/api/client.py`
- [ ] Query `/markets/{conditionId}` for Gamma API 404s
- [ ] Handle delisted markets (mark as "cannot resolve")

### 2.3 Position Resolution
- [ ] Run `polymarket resolve-positions` on newly resolved markets
- [ ] Measure position resolution rate (target: 27% → 80%+ resolved)
- [ ] Log remaining blocked positions and root causes

### 2.4 Validation
- [ ] Markets resolved: 12,356 → 80,000+ (target: 60%+ coverage)
- [ ] Positions resolved: 70,822 → 200,000+ (target: 80%+ coverage)
- [ ] Document remaining blind spots and why they can't be resolved

**Expected Outcome:**
- Populate `markets.outcome` for 60%+ of markets
- Unblock 26K positions stuck in resolution

**Files:**
- `src/gamma/events_resolver.py` — Existing Phase 29 resolver
- `src/api/client.py` — Add market outcome endpoint
- `src/cli/commands.py` — Add fallback resolution command

**Priority:** HIGH (directly unblocks position scoring)

---

## Phase 3: Real-time Prevention

**Goal:** Zero new `graph_` placeholders

### 3.1 Prefetch Integration
- [ ] Add token catalog prefetch to `ingest-trades` command
- [ ] Check token catalog before creating `graph_` placeholder
- [ ] Auto-register new tokens discovered during ingestion

### 3.2 Alerting
- [ ] Log unknown tokens to `unknown_tokens` table for manual review
- [ ] Add metrics: `graph_placeholder_creation_rate`
- [ ] Alert when rate exceeds threshold (e.g., >5% new trades)

### 3.3 Monitoring Dashboard
- [ ] Track token catalog coverage over time
- [ ] Track `graph_` placeholder rate over time
- [ ] Track market resolution rate over time

**Expected Outcome:**
- Zero new `graph_` placeholders from ingestion
- Manual review queue for unknown tokens
- Real-time visibility into data quality

**Files:**
- `src/pipeline/ingest.py` — Add token catalog prefetch
- `src/graph/converters.py` — Update fallback logic
- `src/db/models.py` — Add `UnknownToken` tracking table

**Priority:** MEDIUM (prevents future problems)

---

## Phase 4: Advanced Recovery (Optional)

**Goal:** Recover remaining orphaned trades via alternative methods

### 4.1 Blockchain Event Scanning
- [ ] Scan Conditional Token Factory contract for `Transfer` events
- [ ] Extract `token_id` → `condition_id` mapping from events
- [ ] Backfill tokens not in CLOB API

### 4.2 Subgraph Enhancement
- [ ] Query alternative Graph subgraphs (if available)
- [ ] Check if Polymarket has public token registry subgraph
- [ ] Integrate additional data sources

### 4.3 Community Data Sources
- [ ] Check if Polyscan/polygonscan has token metadata
- [ ] Query Dune Analytics datasets for token mappings
- [ ] Cross-reference with other Polymarket data providers

**Expected Outcome:**
- Recover edge case tokens not in official APIs
- Comprehensive token coverage (>99%)

**Files:**
- `src/blockchain/` — Add token contract scanning
- `src/graph/client.py` — Add alternative subgraph queries

**Priority:** LOW (only if Phase 1-2 insufficient)

---

## Success Metrics

| Metric | Current | Phase 1 Target | Phase 2 Target | Final Target |
|--------|---------|----------------|----------------|--------------|
| Token catalog coverage | 11.4% | 90%+ | 90%+ | 95%+ |
| Trades with real `condition_id` | 27.2% | 80%+ | 80%+ | 90%+ |
| Markets with `outcome` | 8.3% | 8.3% | 60%+ | 80%+ |
| Positions resolved | 72.9% | 72.9% | 80%+ | 90%+ |
| `graph_` placeholder rate | 72.8% | <20% | <20% | <10% |

---

## Dependencies

```
Phase 1 (Token Catalog)
       │
       ▼
Phase 2 (Market Resolution) ← Requires Phase 1 completion
       │
       ▼
Phase 3 (Prevention) ← Can run parallel with Phase 2
       │
       ▼
Phase 4 (Advanced Recovery) ← Optional, only if needed
```

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| CLOB API rate limits | HIGH | MEDIUM | Batch requests, add retry logic |
| Token endpoints unavailable | MEDIUM | HIGH | Fallback to blockchain scanning (Phase 4) |
| Gamma API incomplete coverage | HIGH | MEDIUM | CLOB API fallback (Phase 2.2) |
| Migration corrupts data | LOW | HIGH | Test on subset, add rollback script |
| Delisted markets unresolvable | HIGH | LOW | Accept as permanent blind spot |

---

## Estimated Effort

| Phase | Complexity | Time Estimate | Blockers |
|-------|------------|---------------|----------|
| Phase 1 | MEDIUM | 2-3 days | API endpoint availability |
| Phase 2 | MEDIUM | 2-3 days | Phase 1 completion |
| Phase 3 | LOW | 1-2 days | None (can run parallel) |
| Phase 4 | HIGH | 5-7 days | Only if needed |

**Total:** 5-8 days for Phases 1-3 (core solution)

---

## Next Immediate Actions

1. **Audit CLOB API token endpoints:**
   ```bash
   curl -s "https://clob.polymarket.com/api/tokens" | jq '. | length'
   ```

2. **Check current token catalog size:**
   ```bash
   psql polymarket -c "SELECT COUNT(*) FROM token_catalog;"
   ```

3. **Check `graph_` trade distribution:**
   ```bash
   psql polymarket -c "
     SELECT COUNT(*), 
            SUBSTRING(market_id FROM 1 FOR 20) as market_prefix
     FROM trades 
     WHERE market_id LIKE 'graph_%'
     GROUP BY market_prefix
     ORDER BY COUNT DESC
     LIMIT 10;
   "
   ```

4. **Run Phase 29 resolver (baseline measurement):**
   ```bash
   polymarket resolve-markets-from-events --verbose
   ```

---

## Appendix: Key Statistics

### Current State (2026-03-25)

```
Total trades:              2,529,922
├── Real condition_id:       688,364 (27.2%)
└── graph_ placeholder:    1,841,558 (72.8%) ← Phase 1 target

Total markets:               148,997
├── Resolved (outcome):       12,356 (8.3%)
└── Unresolved:              136,641 (91.7%) ← Phase 2 target

Total positions:              97,060
├── Resolved:                 70,822 (72.9%)
└── Unresolved:               26,238 (27.1%) ← Ultimate blocker
```

### Token Catalog Coverage

```
Tokens in catalog:           136,641
Estimated total tokens:    1,194,000
Coverage:                     11.4% ← Phase 1 target: 90%+
```

---

## Related Documents

- `market-outcome-coverage-research.md` — Problem identification
- `graph-trade-data-structure-research.md` — Data structure deep dive
- `src/graph/converters.py` — Where `graph_` placeholders are created
- `src/gamma/events_resolver.py` — Phase 29 resolver implementation
- `src/db/models.py` — TokenCatalog, Trade, Market models

---

**Status:** Pending approval  
**Review Queue:** Add to `.planning/REVIEW_QUEUE.md`
