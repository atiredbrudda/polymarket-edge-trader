# Plan 26-01: Research Results

**Date:** TBD  
**Status:** In Progress  
**Worker:** TBD

---

## Timing Profile

**Command:** `polymarket discover --niche esports --closing-within 1h`

| Step | Duration | % of Total |
|------|----------|------------|
| `ingest_targeted_markets()` (Gamma API) | | |
| `discover_traders_from_market()` (Polymarket API) | | |
| `matcher.match()` (regex) | | |
| `extract_entities()` (LLM + retries) | | |
| **Total** | | 100% |

**Method:** Add timing instrumentation to `commands.py` temporarily, run command, record output.

---

## Regex Match Rate Analysis

**Query:**
```sql
SELECT 
    COUNT(*) as total,
    SUM(CASE WHEN team_a IS NOT NULL OR game IS NOT NULL THEN 1 ELSE 0 END) as with_entities
FROM market_entities 
WHERE condition_id IN (
    SELECT condition_id FROM markets 
    WHERE category LIKE '%esports%'
);
```

**Results:**
- Total esports markets with entity extraction: ___
- Markets with at least one entity: ___
- Match rate: ___%

**Sample unmatched questions** (to analyze pattern gaps):
```sql
SELECT question, game, tournament
FROM market_entities 
JOIN markets ON market_entities.condition_id = markets.condition_id
WHERE markets.category LIKE '%esports%'
  AND team_a IS NULL AND team_b IS NULL AND game IS NULL
LIMIT 10;
```

---

## Phase 21 Design Review

**Files read:**
- [ ] 21-01-PLAN.md
- [ ] 21-02-PLAN.md
- [ ] 21-01-SUMMARY.md
- [ ] 21-02-SUMMARY.md

**Key findings:**
- Was LLM intended to be synchronous? ___
- Expected regex match rate? ___
- Any notes on async/deferred processing? ___

**Quotes:**
> (paste relevant quotes from Phase 21 docs)

---

## LLM Error Patterns

**Log analysis:**
```bash
grep -i "overloaded\|529\|extraction.*failed" logs/*.log | wc -l
```

**Results:**
- Total LLM errors in recent runs: ___
- 529 Overloaded: ___
- 429 Rate limit: ___
- Other 5xx: ___

**Retry behavior:**
- Average retries per failed call: ___
- Total delay from retries: ___ seconds

---

## Recommendation

**Chosen approach:** Option ___ (from 26-00-PHASE.md)

**Justification:**
(based on timing data and Phase 21 design intent)

**Implementation notes:**
- What to keep from current design
- What to change
- What risks to watch for

---

## Next Steps

1. Review recommendation with reviewer (if unclear)
2. Proceed to 26-02 Implementation plan
3. Keep this document as reference for future debugging

---

## Appendix: Raw Data

(paste command output, SQL query results, log excerpts here)

## Timing Profile

**Command:** `polymarket discover --niche esports --closing-within 1h`
**Date:** 2026-03-23
**After time filter fix applied**

| Step | Duration | % of Total |
|------|----------|------------|
| `ingest_targeted_markets()` (Gamma API) | ~80s | ~90% |
| `discover_traders_from_market()` (Polymarket API) | (included above) | |
| `matcher.match()` (regex) | < 1s | < 1% |
| `extract_entities()` (LLM + retries) | ~7s | ~8% |
| **Total** | **87.7s** | **100%** |

**Key finding:** After fixing the time filter bug, command completes in **87 seconds** (not 7-15 minutes).

**Markets processed:**
- Markets scanned: 26 (in 1h window)
- Detail markets: 15
- New traders: 22

---

## Regex Match Rate Analysis

**From command output:**
- Pattern matched (regex): 6
- LLM calls: 9
- Total: 15
- **Regex match rate: 40%** (lower than expected ~60%)
- **LLM fallback rate: 60%**

**Note:** Higher LLM fallback than expected, but since total markets is small (15), the impact is minimal.

---

## Phase 21 Design Review

**Status:** Pending (will review after confirming if decoupling is still needed)

---

## LLM Error Patterns

**Observation:** No 529 errors in this run! Only 9 LLM calls completed without rate limiting.

**Reason:** With time filter fix, only 9 LLM calls needed (vs 164+ before). Well within rate limits.

---

## CRITICAL FINDING: Time Filter Fix Resolves Primary Issue

**Before fix:**
- Markets processed: 65,540+ (all historical "active" markets)
- Duration: 7-15 minutes (extrapolated to hours)
- LLM calls: 164+ with rate limiting → 529 errors

**After fix:**
- Markets processed: 26 (only future markets in 1h window)
- Duration: 87 seconds
- LLM calls: 9 (no rate limiting)

**Conclusion:** The **time filter bug was the root cause** of the 7-15 minute slowness.
With the fix applied, the command is now fast enough for practical use.

---

## Recommendation

**Primary fix:** Time filter lower bound (ALREADY APPLIED)

**Optional enhancements (Phase 26 scope):**
1. Still valuable: Show classification breakdown (regex vs LLM)
2. Still valuable: Add `--skip-llm` flag for even faster mode
3. Lower priority: Decouple LLM from loop (now that total calls is small)

**Revised approach:**
- Complete Phase 26 with lighter implementation
- Focus on UX improvements (terminal output, `--skip-llm` flag)
- Keep architecture simple since performance is now acceptable

---

## Next Steps

1. ✅ Time filter fix applied and verified
2. Proceed to 26-02: Add `--skip-llm` flag and improve terminal output
3. Skip complex decoupling (no longer critical)
4. Add deprecation warning fix for `datetime.utcnow()`


## Post-Implementation Testing (26-02)

**--skip-llm flag implemented and tested**

### Test Results

**Full mode (with LLM):**
- Duration: 118 seconds
- Markets: 49 scanned, 35 detail
- Regex matches: 11 (31%)
- LLM calls: 24 (69%)
- No 529 errors

**Fast mode (--skip-llm):**
- Duration: 76 seconds (36% faster)
- Markets: 49 scanned, 35 detail  
- Regex matches: 11 (31%)
- LLM calls: Skipped
- All markets still processed, entity classification just uses regex only

### Terminal Output

**Full mode:**
```
Discovery complete (118.1s)
  Markets scanned: 49
  Detail markets:  35
  New traders:     6
  Entities stored: 35
  Pattern matched: 11  LLM calls: 24
```

**Fast mode (--skip-llm):**
```
Discovery complete (75.5s)
  Markets scanned: 49
  Detail markets:  35
  New traders:     0
  Entities stored: 35
  Pattern matched: 11  LLM calls: Skipped
```

### Conclusion

**Time filter fix was the critical fix** - reduced processing from 7-15 minutes to ~2 minutes.

**--skip-llm flag is a nice optimization** - provides ~36% additional speedup for users who don't need entity classification.

