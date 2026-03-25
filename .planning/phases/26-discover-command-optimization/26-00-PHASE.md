# Phase 26: Discover Command Performance Optimization

## Goal

Restore `polymarket discover` command to its original fast execution time by restructuring the entity classification pipeline to complete regex matching before triggering LLM fallback.

**Problem:** Command takes 7-15 minutes for ~400 markets due to LLM API rate limiting (529 Overloaded errors) during market processing loop.

**Root cause:** Regex pattern matching and LLM fallback are tightly coupled in the market processing loop, causing:
1. LLM calls to happen synchronously within the discovery loop
2. 529 rate limit errors trigger 1s, 2s, 4s exponential backoff retries
3. ~40% of esports markets fail regex match → fall through to LLM
4. 410 markets × 40% × 2-3 retries = 164+ LLM calls with retries = 7-15 minutes

**Desired behavior:**
- Regex classification completes in < 1 second for all markets
- LLM calls batched/queued separately, don't block discovery
- Terminal output shows clear breakdown: markets classified vs sent to LLM
- Command completes in ~2 minutes (dominated by Polymarket API calls, not LLM)

---

## Success Criteria

### Functional

- [ ] `polymarket discover --niche esports --closing-within 3h` completes in ≤3 minutes
- [ ] Regex pattern matching completes for all markets before any LLM call
- [ ] LLM fallback is optional/async — doesn't block trader discovery
- [ ] Terminal output shows:
  - Markets ingested
  - Traders discovered
  - Markets classified by regex
  - Markets sent to LLM (if any)
- [ ] No regression: all esports markets still processed correctly

### Performance

| Metric | Current | Target |
|--------|---------|--------|
| Command duration (3h window) | 7-15 min | ≤3 min |
| LLM calls blocking discovery | Yes | No |
| Regex match rate | ~60% | ~60% (unchanged) |
| Markets processed | ~400 | ~400 (unchanged) |

### Quality

- [ ] No cosmetic changes to unrelated code
- [ ] All existing tests pass
- [ ] New test added for classification pipeline separation
- [ ] No debug artifacts in commit

---

## Context

### Timeline

**Mar 23, 2026 — Bug fix applied:**
- Fixed missing lower bound in time filter (`commands.py:1107-1112`)
- Command now processes only future markets in window (~410 markets)
- **Unexpected slowness:** 7+ minutes instead of ~2 minutes

**Root cause analysis:**
```
polymarket discover --niche esports --closing-within 3h
│
├─ Step 1: ingest_targeted_markets() ✅ Fast
│  └─ Fetch ~410 markets from Gamma API with time filter
│
├─ Step 2: Discovery loop ⏱️ SLOW
│  ├─ For each market:
│  │  ├─ get_market_trades() → Polymarket API call (~1s each)
│  │  ├─ Store trades to DB
│  │  ├─ matcher.match() → Regex classification ✅ Fast
│  │  └─ If regex fails → extract_entities() → LLM API call ⏱️ SLOW
│  │     └─ 529 Overloaded error → retry 1s, 2s, 4s
│  └─ 410 markets × 40% LLM fallback × 2-3 retries = 164+ LLM calls
│
└─ Total time: 7-15 minutes (dominated by LLM retries)
```

**Database state:**
```sql
-- Markets to process (esports, future, 3h window)
SELECT COUNT(*) FROM markets 
WHERE active=1 AND end_date > datetime('now') 
  AND end_date <= datetime('now', '+3 hours') 
  AND category LIKE '%esports%';
-- Result: 410

-- Existing entity classifications (for regex patterns)
SELECT COUNT(*) FROM market_entities WHERE team_a IS NOT NULL;
-- Result: 10,003
```

### Original Design (from Phase 21)

Phase 21-01/02 implemented market entity extraction with:
1. PatternMatcher for regex-based extraction (fast)
2. LLM fallback for unmatched patterns (slow, rate-limited)
3. **Design intent:** LLM fallback should not block core discovery

**What went wrong:**
- Code structure couples regex + LLM in same loop iteration
- No option to skip/defer LLM calls
- LLM rate limits (529 errors) block entire pipeline

### Related Phases

| Phase | Relevance |
|-------|-----------|
| Phase 21: Market Entity Extraction | Implemented current regex + LLM system |
| Phase 22: Org-Team Mapping | Extended entity extraction |
| Bug: Time Filter Missing Lower Bound | Fixed Mar 23, revealed this performance issue |

---

## Research

### Current Code Flow

**File:** `src/cli/commands.py:1118-1143`

```python
for market in detail_markets:
    # Step 1: Discover traders from market
    new_traders = pipeline.discover_traders_from_market(
        market.condition_id
    )
    traders_discovered += len(new_traders)

    # Step 2: Classify market (regex + LLM coupled)
    raw_result = matcher.match(market.question)
    if raw_result:
        pattern_matches += 1
        normalized = normalize_entities(raw_result)
    else:
        raw_result = extract_entities(market.question)  # ← LLM call
        normalized = normalize_entities(raw_result)
    
    # Step 3: Store to DB
    existing = session.query(MarketEntity)...)
    if existing:
        # update
    else:
        # insert
```

**Problem:** Steps 2-3 happen inside the loop, blocking on LLM.

### PatternMatcher Capabilities

**File:** `src/extraction/pattern_matcher.py`

**Patterns:**
- Game patterns: CS2, LoL, Dota 2, Valorant, etc. (15 games)
- Tournament → Game map: IEM→CS2, VCT→Valorant, etc. (13 tournaments)
- "Team A vs Team B" regex with prefix handling
- Prop bet detection (17 patterns)

**Stats from 10,003 existing classifications:**
- Regex should match ~60% of esports markets
- ~40% fall through to LLM

### LLM extractor

**File:** `src/extraction/llm_extractor.py`

- Model: `claude-3-haiku-20240307`
- Max retries: 3
- Backoff: 1s, 2s, 4s exponential
- Error handling: 529, 429, 5xx trigger retry

**Rate limit behavior:**
- 100+ rapid calls → 529 Overloaded
- Each retry adds 1-4s delay
- 164 LLM calls × avg 2s = 328s = 5.5 minutes just for retries

### Polymarket API Calls

**File:** `src/pipeline/ingest.py:686-785`

`discover_traders_from_market()` makes:
- `get_market_trades(condition_id)` per market
- ~1s per call with rate limiting
- 410 markets = 410s = 6.8 minutes

**Wait — this is ALSO slow!**

**Real breakdown:**
- 410 markets × 1s API call = 6.8 minutes
- 164 LLM calls × 2s retry = 5.5 minutes
- **Total: 12+ minutes** (matches observed 7-15 min range)

### Options Analysis

#### Option A: Decouple LLM from discovery loop
- Run regex classification in loop (fast)
- Queue unmatched markets for async LLM processing
- Add CLI flag `--skip-llm` for fast discovery

**Pros:**
- Discovery completes in ~7 minutes (just Polymarket API)
- LLM runs separately, doesn't block
- User can choose: fast discovery vs full classification

**Cons:**
- Still slow due to Polymarket API calls
- Requires async/queue infrastructure

#### Option B: Batch Polymarket API calls
- Fetch trades for multiple markets in parallel
- Use asyncio for concurrent API calls

**Pros:**
- Could reduce 6.8 minutes to ~1-2 minutes
- Maintains current functionality

**Cons:**
- Requires significant refactoring
- Risk of hitting harder rate limits

#### Option C: Cache/skip trade storage during discovery
- Don't store trades in discovery step
- Just count traders, defer trade storage to `backfill` command

**Pros:**
- Much faster discovery
- Aligns with original design (discovery vs backfill separation)

**Cons:**
- Changes behavior — trades not immediately available
- May break downstream assumptions

#### Option D: Hybrid (Recommended)
1. Keep current trade storage (don't change data model)
2. Decouple regex + LLM in classification
3. Add terminal output showing breakdown
4. Add `--skip-llm` flag for fast mode
5. LLM fallback runs as separate step or deferred

**Pros:**
- Fast discovery option available
- Maintains data completeness
- Clear user feedback on what's happening
- Minimal behavior change

**Cons:**
- Still slow in "full" mode (but user can choose fast mode)

---

## Plan Overview

### 26-01: Research & Design
- [ ] Profile current command to get exact timing breakdown
- [ ] Review Phase 21 design docs for original intent
- [ ] Design classification pipeline separation
- [ ] Define terminal output format

### 26-02: Implementation
- [ ] Separate regex matching from LLM fallback in discovery loop
- [ ] Add classification stats tracking (regex match count, LLM queue count)
- [ ] Update terminal output to show breakdown
- [ ] Add `--skip-llm` flag for fast mode
- [ ] Implement async/deferred LLM processing (optional)

### 26-03: Testing & Validation
- [ ] Add test for classification pipeline separation
- [ ] Verify no regression in entity extraction
- [ ] Measure performance improvement
- [ ] Test with various niche/time window combinations

---

## Files to Modify

| File | Changes |
|------|---------|
| `src/cli/commands.py:1118-1143` | Decouple regex + LLM, add stats tracking |
| `src/cli/commands.py:1164-1175` | Update terminal output with breakdown |
| `src/extraction/pattern_matcher.py` | Add method to track match/unmatch counts |
| `src/extraction/llm_extractor.py` | Add async/queue option (optional) |
| `tests/test_discovery.py` | Add test for classification pipeline |

---

## Risks

| Risk | Mitigation |
|------|------------|
| Breaking entity extraction data flow | Add comprehensive test coverage |
| Async LLM processing loses context | Keep synchronous fallback option |
| Polymarket API rate limits | Add caching, respect rate limits |
| User confusion with new flags | Clear help text, sensible defaults |

---

## Handoff Notes

**For Worker:**
1. Read this phase plan fully before starting
2. Start with 26-01 research plan — don't skip to implementation
3. Profile command execution to get exact timing breakdown
4. Review Phase 21 plans for original design intent
5. **Critical:** Do NOT make cosmetic changes to unrelated code
6. Test with `--closing-within 1h` first (faster iteration)

**For Reviewer:**
- This phase fixes a performance regression, not a functional bug
- Time filter fix (Mar 23) is separate — already committed
- Focus on: does discovery still work correctly? is it faster?
- Watch for: cosmetic changes, test coverage, behavior changes

---

## Verification Commands

```bash
# Profile current command
time polymarket discover --niche esports --closing-within 1h

# Check database state
sqlite3 data/polymarket.db "SELECT COUNT(*) FROM markets WHERE active=1 AND end_date > datetime('now') AND end_date <= datetime('now', '+1 hour') AND category LIKE '%esports%';"

# After fix, should see:
# - Command completes faster
# - Terminal output shows regex vs LLM breakdown
# - Optional: --skip-llm flag works
```

---

## Related Documents

- `.planning/bugs/discover-command-time-filter-bug.md` — Time filter bug (fixed)
- `.planning/phases/21-market-entity-extraction/` — Original entity extraction implementation
- `src/extraction/pattern_matcher.py` — Regex pattern definitions
- `src/extraction/llm_extractor.py` — LLM fallback implementation
