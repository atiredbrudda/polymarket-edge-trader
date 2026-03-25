# Plan 26-03: Validation Results

**Date:** TBD  
**Status:** Not started  
**Worker:** TBD

---

## Functional Tests

### Test 1: Fast mode (skip LLM)

**Command:**
```bash
time polymarket discover --niche esports --closing-within 1h --skip-llm
```

**Result:** ⬜ Pass / ⬜ Fail

**Output:**
```
(paste terminal output)
```

**Duration:** ___ minutes (target: ≤2 min)

---

### Test 2: Full mode (regex + LLM)

**Command:**
```bash
time polymarket discover --niche esports --closing-within 1h
```

**Result:** ⬜ Pass / ⬜ Fail

**Output:**
```
(paste terminal output)
```

**Duration:** ___ minutes (target: ≤5 min)

---

### Test 3: Other niches

**Commands:**
```bash
polymarket discover --niche crypto --closing-within 3h
polymarket discover --niche politics --closing-within 1d
```

**Result:** ⬜ Pass / ⬜ Fail

**Notes:**
(any errors or issues)

---

### Test 4: Edge cases

**Commands:**
```bash
polymarket discover --niche esports --closing-within 5m
polymarket discover --niche esports --closing-within 7d
```

**Result:** ⬜ Pass / ⬜ Fail

---

## Data Validation

### Entity integrity check

**SQL:**
```sql
SELECT COUNT(*) FROM market_entities 
WHERE extracted_at > datetime('now', '-1 hour');
```

**Result:** ___ rows

**Sample data:**
```sql
SELECT condition_id, team_a, team_b, game, tournament, market_type
FROM market_entities 
WHERE extracted_at > datetime('now', '-1 hour')
LIMIT 10;
```

**Output:**
```
(paste SQL output)
```

**Assessment:** ⬜ Valid / ⬜ Issues found

---

## Performance Benchmarks

| Metric | Before Fix | After Fix | Target | Pass? |
|--------|------------|-----------|--------|-------|
| Duration (1h, skip-LLM) | | | ≤2 min | ⬜ |
| Duration (1h, full) | | | ≤5 min | ⬜ |
| Regex match rate | ~60% | | ~60% | ⬜ |
| LLM calls | ~40% | | ~40% | ⬜ |
| 529 errors | frequent | | reduced | ⬜ |

---

## Regression Tests

**Command:**
```bash
pytest tests/test_discovery.py tests/test_pattern_matcher.py tests/test_llm_extractor.py -v
```

**Result:** ⬜ Pass / ⬜ Fail

**Output:**
```
(paste pytest output)
```

### Full test suite

**Command:**
```bash
pytest tests/ -q --tb=short
```

**Result:** ⬜ Pass / ⬜ Fail

**Failures (if any):**
```
(list any failures)
```

---

## New Test Coverage

**File:** `tests/test_discovery.py`

**Tests added:**
- [ ] `test_discover_classification_breakdown`
- [ ] `test_discover_skip_llm_flag`

**Test code:**
```python
# (paste test code)
```

**Result:** ⬜ Pass / ⬜ Fail

---

## Issues Found & Resolved

### Issue 1: (title)

**Description:** ...

**Resolution:** ...

**Commit:** ...

---

## Final Assessment

**Overall result:** ⬜ Ready to ship / ⬜ Needs fixes

**Summary:**
(brief summary of test results and confidence level)

**Recommendation:**
(proceed to review, or fix issues first)

---

## Sign-off

- [ ] All functional tests pass
- [ ] Performance targets met (or documented why not)
- [ ] Data validation passed
- [ ] No regressions in test suite
- [ ] New test coverage added
- [ ] Ready for reviewer approval

**Worker signature:** ___  
**Date:** ___
