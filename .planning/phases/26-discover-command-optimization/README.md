# Phase 26 GSD Framework — Summary

**Created:** 2026-03-23  
**Status:** Ready for execution  
**Next:** Start Plan 26-01 (Research)

---

## What Was Created

A complete GSD (Goal-Solution-Deliverables) framework for optimizing the `polymarket discover` command.

### Structure

```
.planning/phases/26-discover-command-optimization/
├── 26-00-PHASE.md          # Phase overview, problem analysis, options
├── 26-00-SUMMARY.md        # This summary document
├── 26-01-PLAN.md           # Research & profiling tasks
├── 26-01-RESEARCH.md       # Template for research results
├── 26-02-PLAN.md           # Implementation tasks (code changes)
├── 26-02-IMPLEMENTATION.md # Template for implementation notes
├── 26-03-PLAN.md           # Testing & validation tasks
└── 26-03-VALIDATION.md     # Template for validation results

.planning/milestones/v1.3/
└── ROADMAP.md              # Milestone v1.3 charter
```

---

## Problem Being Solved

**Symptom:** `polymarket discover --niche esports --closing-within 3h` takes 7-15 minutes

**Root cause:**
1. Time filter bug (fixed) revealed pipeline is slow
2. Regex + LLM coupled in same loop iteration
3. ~40% of markets fail regex → LLM fallback
4. LLM hits 529 rate limits → 1-4s retries per call
5. 410 markets × 40% × 2-3 retries = 164+ slow LLM calls

**Plus:** Polymarket API calls (1s each) also contribute ~7 minutes

---

## Solution

**Phase 26 will:**
1. Decouple regex matching from LLM fallback
2. Add `--skip-llm` flag for fast discovery mode
3. Show classification breakdown in terminal output
4. Optionally defer LLM processing

**Expected result:**
- Fast mode: ~2 minutes (skip LLM)
- Full mode: ~5 minutes (with LLM, but user sees progress)
- Same functionality, just reorganized

---

## Execution Plan

### Step 1: Research (26-01)
**Goal:** Profile command to confirm timing hypotheses

**Tasks:**
- Add timing instrumentation
- Run command, measure each step
- Analyze regex match rate from database
- Review Phase 21 design docs
- Document findings in `26-01-RESEARCH.md`

**Output:** Research document with data to justify implementation approach

---

### Step 2: Implementation (26-02)
**Goal:** Decouple regex from LLM, add `--skip-llm` flag

**Tasks:**
- Modify `commands.py:1118-1143` discovery loop
- Separate regex matches (immediate) from LLM (queued)
- Add `--skip-llm` CLI flag
- Update terminal output to show breakdown
- Extract `store_entity()` helper function

**Output:** Working code with fast mode option

---

### Step 3: Testing (26-03)
**Goal:** Verify no regressions, measure improvement

**Tasks:**
- Test fast mode (`--skip-llm`)
- Test full mode (regex + LLM)
- Validate entity data integrity
- Run pytest suite
- Add new test coverage
- Document in `26-03-VALIDATION.md`

**Output:** Validation report, ready for review

---

## Files to Modify (Implementation Phase)

| File | Lines | Changes |
|------|-------|---------|
| `src/cli/commands.py` | 1118-1143 | Decouple regex + LLM |
| `src/cli/commands.py` | 1060-1070 | Add `--skip-llm` flag |
| `src/cli/commands.py` | 1164-1175 | Update terminal output |
| `src/extraction/pattern_matcher.py` | 84-103 | Enhance stats tracking |
| `tests/test_discovery.py` | TBD | Add new tests |

---

## Success Criteria

### Functional
- [ ] `--skip-llm` flag works
- [ ] Regex classification completes for all markets
- [ ] LLM fallback is optional/deferred
- [ ] Terminal shows breakdown

### Performance
- [ ] Fast mode: ≤2 minutes (1h window)
- [ ] Full mode: ≤5 minutes (1h window)
- [ ] No regression in entity extraction

### Quality
- [ ] All tests pass
- [ ] No cosmetic changes
- [ ] New test coverage added

---

## How to Start

**For the Worker:**

```bash
# 1. Check current state
git log --oneline -1
git status

# 2. Create research branch
git checkout main
git pull
git checkout -b worker/26-01-research

# 3. Read the phase plan
cat .planning/phases/26-discover-command-optimization/26-01-PLAN.md

# 4. Start with profiling (don't skip to implementation!)
# Add timing instrumentation, run command, measure
```

**Key principle:** Research first, implement second. Measure before optimizing.

---

## Review Protocol

**For the Reviewer:**

1. Review phase plan structure (26-00-PHASE.md)
2. Approve to start 26-01 research
3. After 26-01: review research findings
4. After 26-02: review code changes (watch for cosmetic changes)
5. After 26-03: review validation, merge to main

**Review checklist:**
- [ ] No cosmetic reformatting
- [ ] Tests updated for interface changes
- [ ] `--skip-llm` flag documented in help text
- [ ] Terminal output is clear and accurate
- [ ] No debug artifacts

---

## Related Documents

- `.planning/bugs/discover-command-time-filter-bug.md` — Time filter bug (fixed)
- `.planning/phases/21-market-entity-extraction/` — Original entity extraction
- `src/cli/commands.py:1118-1143` — Code to modify
- `.planning/AGENTS.md` — Worker/Reviewer protocol
- `.planning/HANDOFF_PROTOCOL.md` — Handoff procedures

---

## Estimated Effort

| Phase | Estimated Time | Complexity |
|-------|---------------|------------|
| 26-01 Research | 2-3 hours | Low |
| 26-02 Implementation | 3-4 hours | Medium |
| 26-03 Testing | 2-3 hours | Medium |
| **Total** | **7-10 hours** | |

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Polymarket API also slow (not just LLM) | Phase 26 focuses on LLM decoupling; API parallelization is future work |
| Regex match rate lower than expected | Data will show actual rate; can improve patterns in future phase |
| Breaking entity extraction | Comprehensive testing in 26-03 |
| User confusion with new flag | Clear help text, sensible default (full mode) |

---

## Next Phase Considerations (Future)

After Phase 26 completes, consider:
- Phase 27: Parallel Polymarket API calls (asyncio)
- Phase 28: Response caching layer
- Phase 29: Async LLM queue processing
- Phase 30: Progress indicators for long commands

But first: complete Phase 26 properly.

---

## Questions?

Refer to:
- 26-00-PHASE.md for problem analysis
- 26-01-PLAN.md for research tasks
- `.planning/AGENTS.md` for worker/reviewer protocol

**Good luck!** 🚀
