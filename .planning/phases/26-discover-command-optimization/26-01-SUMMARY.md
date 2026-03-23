# Plan 26-01: Research — SUMMARY

**Date:** 2026-03-23  
**Status:** Complete  
**Branch:** worker/26-01-research

---

## What Was Done

Researched the discover command performance issue and discovered the root cause.

### Key Finding: Time Filter Bug Not Merged

The time filter lower bound fix was applied in a local commit but **never merged to main**. This was the actual root cause of the 7-15 minute slowness.

### Profiling Results

**Before time filter fix:**
- Markets processed: 65,540+ (all historical "active" markets)
- Duration: 7-15 minutes (extrapolated to hours)
- LLM calls: 164+ with rate limiting → 529 errors

**After time filter fix:**
- Markets processed: 26-49 (only future markets in time window)
- Duration: 75-120 seconds
- LLM calls: 9-24 (no rate limiting)

### Regex Match Rate

- Regex match rate: 31-40% (lower than expected ~60%)
- LLM fallback rate: 60-69%
- Despite high LLM fallback, total calls are now small enough that rate limiting is not an issue

### LLM Error Patterns

- **No 529 errors** observed after time filter fix
- With only 9-24 LLM calls per run, well within rate limits
- Retries still happen but complete quickly

---

## Critical Discovery

**The time filter bug fix was the primary solution.** The Phase 26 plan was created to address performance issues, but the real fix was already written — just not merged.

### What Happened

1. Time filter fix was committed locally (`9e5bf61`)
2. User merged a different branch (`worker/25-01-lift-scoring`)
3. Time filter fix was not included in the merge
4. User ran discover command, experienced 7-15 minute slowness
5. Phase 26 was created to "fix" the performance issue
6. Research revealed the time filter fix was missing

### Resolution

Applied the time filter fix to the current branch:
```python
if end_date_max:
    from datetime import datetime

    query = query.filter(
        Market.end_date > datetime.utcnow(),
        Market.end_date <= end_date_max
    )
```

This single change resolved the primary performance issue.

---

## Additional Enhancements

While the time filter was the critical fix, Phase 26 also identified valuable UX improvements:

1. **`--skip-llm` flag** — Skip LLM entity extraction for faster discovery (36% speedup)
2. **Classification breakdown** — Show regex vs LLM counts in terminal output
3. **Better terminal feedback** — Clear indication of what's happening

These are implemented in Plan 26-02.

---

## Files Modified

| File | Change |
|------|--------|
| `src/cli/commands.py:1111-1116` | Added time filter lower bound |
| `.planning/phases/26-discover-command-optimization/26-01-RESEARCH.md` | Research findings |

---

## Metrics

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Command duration (1h window) | 7-15 min | 75-120s | 6-12x faster |
| Markets processed | 65,540+ | 26-49 | 99.9% reduction |
| LLM calls | 164+ | 9-24 | 85-94% reduction |
| 529 errors | Frequent | None | Eliminated |

---

## Next Steps

Proceed to Plan 26-02: Implement `--skip-llm` flag and improved terminal output.

---

## Checklist

- [x] Profiled command execution
- [x] Identified root cause (time filter not merged)
- [x] Applied time filter fix
- [x] Documented findings
- [x] Recommended approach validated
- [ ] Ready for Plan 26-02 implementation
