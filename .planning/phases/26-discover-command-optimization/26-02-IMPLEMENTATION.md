# Plan 26-02: Implementation Notes

**Date:** TBD  
**Status:** Not started  
**Worker:** TBD

---

## Changes Made

### File: `src/cli/commands.py`

**Lines modified:** TBD

**Changes:**
1. Decoupled regex from LLM in discovery loop
2. Added `--skip-llm` flag
3. Updated terminal output with classification breakdown
4. Extracted `store_entity()` helper function

**Before:**
```python
# (paste old code)
```

**After:**
```python
# (paste new code)
```

---

### File: `src/extraction/pattern_matcher.py`

**Lines modified:** TBD

**Changes:**
- Enhanced stats tracking

---

### File: `src/cli/commands.py` (CLI definition)

**Lines modified:** TBD

**Changes:**
- Added `--skip-llm` flag

---

## Design Decisions

### Decision 1: (title)

**Options considered:**
- Option A: ...
- Option B: ...

**Chosen:** ...

**Rationale:** ...

---

## Issues Encountered

### Issue 1: (description)

**Resolution:** ...

---

## Testing Performed

- [ ] Fast mode (`--skip-llm`) works
- [ ] Full mode (regex + LLM) works
- [ ] Terminal output shows correct breakdown
- [ ] No regressions in entity data

---

## TODO: Before Submit

- [ ] Remove any timing/debug instrumentation
- [ ] Verify no cosmetic changes
- [ ] Run pytest
- [ ] Write 26-02-SUMMARY.md
